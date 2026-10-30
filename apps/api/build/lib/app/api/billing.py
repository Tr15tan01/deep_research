"""Billing API (optional module; fully inert when BILLING_ENABLED=0)."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.auth.deps import Principal, current_principal
from app.billing.paddle import (
    apply_subscription,
    get_billing_provider,
    handle_webhook,
    verify_paddle_signature,
)
from app.core.config import get_settings
from app.core.errors import AppError, FeatureDisabled
from app.core.logging import get_logger
from app.db.mongo import Collections, col
from app.services.audit import audit
from app.services.limits import plan_catalog, usage_snapshot

log = get_logger("billing_api")
router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


def _require_billing() -> None:
    if not get_settings().BILLING_ENABLED:
        raise FeatureDisabled("Billing is not enabled.")


class CheckoutIn(BaseModel):
    plan: str


@router.get("/plans")
async def plans() -> dict[str, Any]:
    s = get_settings()
    if not s.BILLING_ENABLED:
        return {"enabled": False, "plans": []}
    prices = s.paddle_price_ids
    return {"enabled": True, "grace_days": s.BILLING_GRACE_DAYS, "grace_allows_new_jobs": s.BILLING_GRACE_ALLOWS_NEW_JOBS,
            "plans": [{**asdict(p), "purchasable": p.plan in prices} for p in plan_catalog().values()]}


@router.get("/subscription")
async def subscription(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    snap = await usage_snapshot(principal.user)
    sub = await col(Collections.subscriptions).find_one({"user_id": principal.id})
    return {"enabled": get_settings().BILLING_ENABLED, "usage": snap,
            "subscription": {k: sub.get(k) for k in ("status", "plan", "current_period_end", "grace_until", "scheduled_change",
                                                     "updated_at")} if sub else None}


@router.post("/checkout")
async def checkout(body: CheckoutIn, request: Request, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    _require_billing()
    url = await get_billing_provider().create_checkout(principal.user, body.plan)
    await audit("billing.checkout_started", actor_id=principal.id, metadata={"plan": body.plan})
    # The redirect back is NOT proof of payment; entitlements change only via verified webhooks/reconciliation.
    return {"checkout_url": url}


@router.post("/cancel")
async def cancel(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    _require_billing()
    sub = await col(Collections.subscriptions).find_one({"user_id": principal.id})
    if not sub or not sub.get("provider_subscription_id"):
        raise AppError("You don't have an active subscription.", code="no_subscription", status_code=404)
    data = await get_billing_provider().cancel(sub["provider_subscription_id"])
    if data:
        await apply_subscription(data, None, "api:cancel")
    await audit("billing.cancel_requested", actor_id=principal.id)
    return {"status": "cancel_scheduled", "message": "Your plan stays active until the end of the billing period."}


@router.post("/portal")
async def portal(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    _require_billing()
    sub = await col(Collections.subscriptions).find_one({"user_id": principal.id})
    if not sub or not sub.get("customer_id"):
        raise AppError("No billing account yet.", code="no_customer", status_code=404)
    url = await get_billing_provider().portal_url(sub["customer_id"])
    if not url:
        raise AppError("The billing portal is unavailable.", code="portal_unavailable", status_code=503)
    return {"portal_url": url}


@router.post("/reconcile")
async def reconcile(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    """Pull authoritative subscription state from the provider (covers delayed/missed webhooks)."""
    _require_billing()
    sub = await col(Collections.subscriptions).find_one({"user_id": principal.id})
    if not sub or not sub.get("provider_subscription_id"):
        return {"status": "no_subscription"}
    data = await get_billing_provider().fetch_subscription(sub["provider_subscription_id"])
    data.setdefault("custom_data", {})["user_id"] = principal.id
    return {"status": await apply_subscription(data, None, "api:reconcile")}


@router.post("/webhook")
async def webhook(request: Request) -> dict[str, Any]:
    s = get_settings()
    if not s.BILLING_ENABLED:
        raise FeatureDisabled()
    raw = await request.body()
    if len(raw) > 1_000_000:
        raise AppError("Payload too large.", code="payload_too_large", status_code=413)
    if not verify_paddle_signature(raw, request.headers.get("paddle-signature"), s.PADDLE_WEBHOOK_SECRET):
        log.warning("webhook_signature_invalid")
        raise AppError("Invalid signature.", code="invalid_signature", status_code=401)
    try:
        event = json.loads(raw)
    except ValueError as e:
        raise AppError("Invalid JSON.", code="invalid_payload", status_code=400) from e
    result = await handle_webhook(event)
    return {"result": result}
