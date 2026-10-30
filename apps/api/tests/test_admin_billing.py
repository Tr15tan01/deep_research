"""Admin authorization, provider configuration, credential handling, and the billing module."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from tests.conftest import ApiClient, make_admin


async def _admin(make_client: Any, email: str = "admin@example.com") -> ApiClient:
    c = await make_client()
    await c.register(email)
    await make_admin(email)
    return c


async def test_admin_endpoints_require_admin(client: ApiClient) -> None:
    await client.register("user@example.com")
    for path in ("/api/v1/admin/users", "/api/v1/admin/providers", "/api/v1/admin/usage", "/api/v1/admin/jobs",
                 "/api/v1/admin/system-health", "/health/dependencies"):
        assert (await client.get(path)).status_code == 403, path
    assert (await client.put("/api/v1/admin/providers", json={})).status_code == 403


async def test_bootstrap_admin(make_client: Any, env: Any) -> None:
    # Behave like a real deployment (the in-memory dev DB relaxes the verification requirement).
    env(ADMIN_BOOTSTRAP_EMAILS="boss@example.com", MONGODB_URI="mongodb://db.invalid:27017")
    c = await make_client()
    r = await c.register("boss@example.com")
    assert r.json()["user"]["role"] == "USER"  # unverified accounts are never auto-promoted
    from app.db.mongo import Collections, col

    await col(Collections.users).update_one({"email": "boss@example.com"}, {"$set": {"email_verified": True}})
    c.c.cookies.clear()
    r = await c.login("boss@example.com")
    assert r.json()["user"]["role"] == "ADMIN"


async def test_provider_config_and_encrypted_keys(make_client: Any) -> None:
    from app.db.mongo import Collections, col

    c = await _admin(make_client)
    r = await c.put("/api/v1/admin/providers", json={
        "default": {"provider": "anthropic", "model": "exact-model-id-2026"},
        "tasks": {"extraction": {"provider": "gemini", "model": "cheap-model"}},
        "allowed_user_models": [{"provider": "openai", "model": "gpt-x", "label": "GPT X"}]})
    assert r.status_code == 200, r.text
    r = await c.put("/api/v1/admin/providers/keys", json={"provider": "anthropic", "api_key": "sk-ant-supersecretvalue1234"})
    assert r.status_code == 200
    creds = r.json()["credentials"]["anthropic"]
    assert creds["configured"] and creds["source"] == "admin_store" and creds["masked"].endswith("1234")
    stored = await col(Collections.app_settings).find_one({"_id": "ai_credentials"})
    assert "supersecret" not in json.dumps(stored, default=str)  # encrypted at rest
    page = await c.get("/api/v1/admin/providers")
    assert "supersecret" not in page.text
    assert page.json()["config"]["default"]["model"] == "exact-model-id-2026"
    bad = await c.put("/api/v1/admin/providers", json={"tasks": {"nonsense": None}})
    assert bad.status_code == 422


async def test_env_key_is_read_only(make_client: Any, env: Any) -> None:
    env(OPENAI_API_KEY="sk-env-0000000000000000")
    c = await _admin(make_client)
    r = await c.put("/api/v1/admin/providers/keys", json={"provider": "openai", "api_key": "sk-other"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "key_managed_by_environment"


async def test_connection_test_reports_missing_key(make_client: Any) -> None:
    c = await _admin(make_client)
    r = await c.post("/api/v1/admin/providers/test", json={"provider": "gemini", "model": "m"})
    assert r.json()["ok"] is False and r.json()["error"] == "not_configured"


async def test_user_model_selection_policy(make_client: Any, env: Any) -> None:
    env(DEMO_MODE="0", ALLOW_USER_MODEL_SELECTION="0", AI_PROVIDER="openai", AI_MODEL="base", OPENAI_API_KEY="sk-1234567890123456",
        TAVILY_API_KEY="tvly-k")
    c = await make_client()
    await c.register("picker@example.com")
    r = await c.post("/api/v1/research", json={"question": "Some research question here", "mode": "quick",
                                                "options": {"model": {"provider": "openai", "model": "base"}}})
    assert r.status_code == 403 and r.json()["error"]["code"] == "model_selection_disabled"
    env(DEMO_MODE="0", ALLOW_USER_MODEL_SELECTION="1", AI_PROVIDER="openai", AI_MODEL="base", OPENAI_API_KEY="sk-1234567890123456",
        TAVILY_API_KEY="tvly-k")
    r = await c.post("/api/v1/research", json={"question": "Some research question here", "mode": "quick",
                                                "options": {"model": {"provider": "openai", "model": "unapproved"}}})
    assert r.status_code == 403 and r.json()["error"]["code"] == "model_not_allowed"


async def test_admin_cannot_demote_self_and_disable_revokes(make_client: Any) -> None:
    c = await _admin(make_client)
    me = (await c.get("/api/v1/auth/me")).json()["user"]
    r = await c.patch(f"/api/v1/admin/users/{me['id']}", json={"role": "USER"})
    assert r.status_code == 409
    u = await make_client()
    await u.register("victim@example.com")
    vid = (await u.get("/api/v1/auth/me")).json()["user"]["id"]
    assert (await c.patch(f"/api/v1/admin/users/{vid}", json={"status": "disabled"})).status_code == 200
    assert (await u.get("/api/v1/auth/me")).status_code == 401


async def test_admin_health_and_public_config(make_client: Any) -> None:
    c = await _admin(make_client)
    h = (await c.get("/api/v1/admin/system-health")).json()
    assert h["database"]["ok"] and "flags" in h
    pub = (await c.get("/api/v1/public/config")).json()
    assert pub["features"]["billing"] is False and "GEMINI_API_KEY" not in json.dumps(pub)
    ready = await c.get("/health/ready")
    assert ready.status_code == 200


# --- Billing ------------------------------------------------------------------------------------

def _sign(body: bytes, secret: str, ts: int | None = None) -> str:
    ts = ts or int(time.time())
    return f"ts={ts};h1=" + hmac.new(secret.encode(), f"{ts}:".encode() + body, hashlib.sha256).hexdigest()


async def test_billing_disabled_is_inert(client: ApiClient) -> None:
    await client.register("free@example.com")
    assert (await client.get("/api/v1/billing/plans")).json() == {"enabled": False, "plans": []}
    assert (await client.post("/api/v1/billing/checkout", json={"plan": "pro"})).status_code == 404
    sub = (await client.get("/api/v1/billing/subscription")).json()
    assert sub["enabled"] is False and sub["usage"]["can_start_jobs"] is True


async def test_billing_webhooks(make_client: Any, env: Any) -> None:
    from app.db.mongo import Collections, col

    env(BILLING_ENABLED="1", PADDLE_API_KEY="pdl_test", PADDLE_WEBHOOK_SECRET="whsec", PADDLE_PRICE_IDS="pro:pri_pro")
    c = await make_client()
    await c.register("payer@example.com")
    uid = (await c.get("/api/v1/auth/me")).json()["user"]["id"]

    def event(eid: str, status: str, occurred: str) -> bytes:
        return json.dumps({"event_id": eid, "event_type": "subscription.updated", "occurred_at": occurred,
                           "data": {"id": "sub_1", "status": status, "customer_id": "ctm_1",
                                    "items": [{"price": {"id": "pri_pro"}}], "custom_data": {"user_id": uid}}}).encode()

    body = event("evt_1", "active", "2026-10-01T10:00:00Z")
    bad = await c.c.post("/api/v1/billing/webhook", content=body, headers={"paddle-signature": _sign(body, "wrong")})
    assert bad.status_code == 401
    stale_sig = await c.c.post("/api/v1/billing/webhook", content=body,
                               headers={"paddle-signature": _sign(body, "whsec", ts=int(time.time()) - 3600)})
    assert stale_sig.status_code == 401
    ok = await c.c.post("/api/v1/billing/webhook", content=body, headers={"paddle-signature": _sign(body, "whsec")})
    assert ok.json()["result"] == "applied"
    dup = await c.c.post("/api/v1/billing/webhook", content=body, headers={"paddle-signature": _sign(body, "whsec")})
    assert dup.json()["result"] == "duplicate"
    older = event("evt_0", "canceled", "2026-09-01T10:00:00Z")  # delayed delivery of an older event
    r = await c.c.post("/api/v1/billing/webhook", content=older, headers={"paddle-signature": _sign(older, "whsec")})
    assert r.json()["result"] == "ignored_stale"
    sub = await col(Collections.subscriptions).find_one({"user_id": uid})
    assert sub["status"] == "active" and sub["plan"] == "pro"
    past_due = event("evt_2", "past_due", "2026-10-05T10:00:00Z")
    await c.c.post("/api/v1/billing/webhook", content=past_due, headers={"paddle-signature": _sign(past_due, "whsec")})
    s = (await c.get("/api/v1/billing/subscription")).json()
    assert s["subscription"]["status"] == "past_due" and s["subscription"]["grace_until"] is not None
    assert s["usage"]["plan"]["plan"] == "pro"  # within grace period


async def test_free_plan_limits_when_billing_enabled(make_client: Any, env: Any) -> None:
    env(BILLING_ENABLED="1", PADDLE_API_KEY="pdl_test", PADDLE_WEBHOOK_SECRET="whsec", DEMO_MODE="1")
    c = await make_client()
    await c.register("freeuser@example.com")
    r = await c.post("/api/v1/research", json={"question": "Deep question about demo topics", "mode": "deep"})
    assert r.status_code == 402 and r.json()["error"]["code"] == "mode_not_allowed"


async def test_search_keys_saved_in_admin_console(make_client: Any, env: Any) -> None:
    """Search keys can be stored encrypted in MongoDB (shared by API and workers), env keys win."""
    from app.db.mongo import Collections, col
    from app.llm.config_store import reset_search_key_cache
    from app.search.service import SearchService

    c = await _admin(make_client)
    body = (await c.get("/api/v1/admin/providers")).json()
    assert body["search"]["credentials"]["tavily"]["configured"] is False
    assert not (await SearchService.create()).available()

    r = await c.put("/api/v1/admin/providers/keys", json={"provider": "tavily", "api_key": "tvly-admin-stored-key-9876"})
    assert r.status_code == 200, r.text
    assert r.json()["search_credentials"]["tavily"] == {
        "configured": True, "source": "admin_store", "masked": "••••9876",
        "updated_at": r.json()["search_credentials"]["tavily"]["updated_at"]}
    stored = await col(Collections.app_settings).find_one({"_id": "ai_credentials"})
    assert "tvly-admin-stored-key-9876" not in json.dumps(stored, default=str)  # encrypted at rest
    assert "tvly-admin" not in (await c.get("/api/v1/admin/providers")).text  # never echoed

    reset_search_key_cache()  # a different process (e.g. the worker) starts with an empty cache
    svc = await SearchService.create()
    assert svc.order == ["tavily"] and svc._provider("tavily").api_key == "tvly-admin-stored-key-9876"
    assert (await c.get("/api/v1/public/config")).json()["setup"]["search_ready"] is True

    # Environment keys are authoritative and cannot be overwritten from the UI.
    env(FIRECRAWL_API_KEY="fc-env-key-1234567890abcdef")
    r = await c.put("/api/v1/admin/providers/keys", json={"provider": "firecrawl", "api_key": "fc-other"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "key_managed_by_environment"
    assert (await c.put("/api/v1/admin/providers/keys", json={"provider": "bing", "api_key": "x"})).status_code == 422

    # Removing the stored key takes effect immediately.
    assert (await c.put("/api/v1/admin/providers/keys", json={"provider": "tavily", "api_key": None})).status_code == 200
    assert "tavily" not in (await SearchService.create()).order
