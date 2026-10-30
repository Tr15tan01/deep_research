"""Billing provider abstraction with a Paddle Billing implementation.

Security model:
  * Entitlements are granted only from verified webhooks or server-side API reconciliation
    — never from a frontend "payment success" redirect.
  * Webhooks are HMAC-verified (Paddle-Signature: ts=…;h1=…) with a timestamp tolerance,
    processed idempotently (unique event_id) and applied in occurred_at order.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timedelta
from typing import Any, Protocol

import httpx

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.security import as_utc, utcnow
from app.db.mongo import Collections, col, new_id

log = get_logger("billing")
SIGNATURE_TOLERANCE_SECONDS = 300


class BillingProvider(Protocol):
    async def create_checkout(self, user: dict[str, Any], plan: str) -> str: ...
    async def cancel(self, subscription_id: str) -> dict[str, Any]: ...
    async def portal_url(self, customer_id: str) -> str | None: ...
    async def fetch_subscription(self, subscription_id: str) -> dict[str, Any]: ...


def verify_paddle_signature(raw_body: bytes, header: str | None, secret: str, now: float | None = None) -> bool:
    if not header or not secret:
        return False
    parts = dict(p.split("=", 1) for p in header.split(";") if "=" in p)
    ts, h1 = parts.get("ts"), parts.get("h1")
    if not ts or not h1 or not ts.isdigit():
        return False
    if abs((now or time.time()) - int(ts)) > SIGNATURE_TOLERANCE_SECONDS:
        return False
    expected = hmac.new(secret.encode(), f"{ts}:".encode() + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, h1)


class PaddleProvider:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        s = get_settings()
        self.base = "https://api.paddle.com" if s.PADDLE_ENVIRONMENT == "production" else "https://sandbox-api.paddle.com"
        self.client = client or httpx.AsyncClient(timeout=20)
        self.headers = {"Authorization": f"Bearer {s.PADDLE_API_KEY}", "Content-Type": "application/json"}

    async def _req(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        try:
            r = await self.client.request(method, self.base + path, headers=self.headers, **kw)
        except httpx.HTTPError as e:
            raise AppError("The payment provider is unreachable. Please try again.", code="billing_unavailable",
                           status_code=503) from e
        if r.status_code >= 400:
            log.warning("paddle_error", status=r.status_code, path=path)
            raise AppError("The payment provider rejected the request.", code="billing_provider_error", status_code=502)
        return r.json()

    async def create_checkout(self, user: dict[str, Any], plan: str) -> str:
        price_id = get_settings().paddle_price_ids.get(plan)
        if not price_id:
            raise AppError("This plan is not available for purchase.", code="plan_unavailable", status_code=422)
        data = await self._req("POST", "/transactions", json={
            "items": [{"price_id": price_id, "quantity": 1}],
            "custom_data": {"user_id": user["_id"], "plan": plan},
            "collection_mode": "automatic"})
        url = ((data.get("data") or {}).get("checkout") or {}).get("url")
        if not url:
            raise AppError("Checkout is not configured in the payment provider (no default payment link).",
                           code="checkout_unavailable", status_code=503)
        return url

    async def cancel(self, subscription_id: str) -> dict[str, Any]:
        return (await self._req("POST", f"/subscriptions/{subscription_id}/cancel",
                                json={"effective_from": "next_billing_period"})).get("data", {})

    async def portal_url(self, customer_id: str) -> str | None:
        data = await self._req("POST", f"/customers/{customer_id}/portal-sessions", json={})
        return (((data.get("data") or {}).get("urls") or {}).get("general") or {}).get("overview")

    async def fetch_subscription(self, subscription_id: str) -> dict[str, Any]:
        return (await self._req("GET", f"/subscriptions/{subscription_id}")).get("data", {})


def get_billing_provider() -> BillingProvider:
    return PaddleProvider()


def _plan_for_price(price_id: str | None) -> str:
    for plan, pid in get_settings().paddle_price_ids.items():
        if pid == price_id:
            return plan
    return "free"


def _parse_ts(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None


async def apply_subscription(sub: dict[str, Any], occurred_at: datetime | None, source: str) -> str:
    """Upsert local subscription state from a Paddle subscription object. Older events are ignored."""
    s = get_settings()
    custom = sub.get("custom_data") or {}
    subs = col(Collections.subscriptions)
    existing = await subs.find_one({"provider_subscription_id": sub.get("id")})
    user_id = custom.get("user_id") or (existing or {}).get("user_id")
    if not user_id:
        return "ignored_no_user"
    if existing and occurred_at and existing.get("last_event_at") and as_utc(existing["last_event_at"]) > occurred_at:
        return "ignored_stale"
    status = sub.get("status")  # active | trialing | past_due | paused | canceled
    items = sub.get("items") or []
    price_id = ((items[0] if items else {}).get("price") or {}).get("id")
    plan = _plan_for_price(price_id)
    now = utcnow()
    upd: dict[str, Any] = {
        "user_id": user_id, "provider": "paddle", "provider_subscription_id": sub.get("id"),
        "customer_id": sub.get("customer_id"), "status": status, "plan": plan, "price_id": price_id,
        "current_period_end": _parse_ts((sub.get("current_billing_period") or {}).get("ends_at")),
        "scheduled_change": sub.get("scheduled_change"), "last_event_at": occurred_at or now, "updated_at": now,
        "last_source": source,
    }
    if status == "past_due" and not (existing or {}).get("grace_until"):
        upd["grace_until"] = now + timedelta(days=s.BILLING_GRACE_DAYS)
    if status in ("active", "trialing"):
        upd["grace_until"] = None
    await subs.update_one({"user_id": user_id}, {"$set": upd, "$setOnInsert": {"_id": new_id("sub"), "created_at": now}},
                          upsert=True)
    await col(Collections.users).update_one({"_id": user_id}, {"$set": {"plan": plan if status in ("active", "trialing", "past_due") else "free"}})
    return "applied"


async def handle_webhook(event: dict[str, Any]) -> str:
    event_id = event.get("event_id") or event.get("notification_id")
    if not event_id:
        return "ignored_no_id"
    billing = col(Collections.billing_events)
    try:
        await billing.insert_one({"_id": new_id("bev"), "event_id": event_id, "type": event.get("event_type"),
                                  "occurred_at": event.get("occurred_at"), "received_at": utcnow(), "status": "processing"})
    except Exception:  # noqa: BLE001 — duplicate key => already processed (idempotent)
        return "duplicate"
    etype = event.get("event_type", "")
    data = event.get("data") or {}
    occurred = _parse_ts(event.get("occurred_at"))
    try:
        if etype.startswith("subscription."):
            result = await apply_subscription(data, occurred, f"webhook:{etype}")
        elif etype == "transaction.payment_failed":
            uid = (data.get("custom_data") or {}).get("user_id")
            if uid:
                await col(Collections.notifications).insert_one({
                    "_id": new_id("ntf"), "user_id": uid, "kind": "payment_failed", "title": "Payment failed",
                    "body": "Your payment did not go through. Your reports are safe; update your payment method to keep your plan.",
                    "link": "/settings/billing", "read": False, "created_at": utcnow()})
            result = "notified"
        else:
            result = "ignored_type"
        await billing.update_one({"event_id": event_id}, {"$set": {"status": result, "processed_at": utcnow()}})
        return result
    except Exception:
        # Allow the provider's redelivery to retry this event.
        await billing.delete_one({"event_id": event_id})
        raise
