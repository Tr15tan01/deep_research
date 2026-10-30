"""Administrator API: users, AI providers/models, pricing, usage, jobs and system health."""

from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from app.auth.deps import Principal, require_admin
from app.auth.service import ROLES, public_user, revoke_all_sessions
from app.core import ratelimit
from app.core.config import get_settings
from app.core.errors import AppError, NotFound
from app.core.security import utcnow
from app.db.mongo import Collections, aggregate, col, ping
from app.db.redis import get_redis, redis_ping
from app.jobs import lifecycle, queue
from app.llm.base import LLMError
from app.llm.capabilities import resolve_capabilities
from app.llm.config_store import (
    PROVIDERS,
    SEARCH_KEY_PROVIDERS,
    AIConfig,
    AllowedModel,
    CapabilityOverride,
    ModelRef,
    PriceEntry,
    credential_status,
    get_api_key,
    load_config,
    refresh_search_keys,
    save_config,
    set_api_key,
)
from app.llm.service import build_provider, test_connection
from app.search.service import configured_search_providers
from app.services.audit import audit

router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# --- Users --------------------------------------------------------------------------------------

class UserUpdate(BaseModel):
    role: str | None = None
    status: str | None = Field(default=None, pattern="^(active|disabled)$")


@router.get("/users")
async def users(q: str | None = Query(default=None, max_length=200), limit: int = Query(default=50, ge=1, le=200),
                skip: int = Query(default=0, ge=0)) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        query["$or"] = [{"email": rx}, {"name": rx}]
    items = await col(Collections.users).find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(None)
    total = await col(Collections.users).count_documents(query)
    out = []
    for u in items:
        pu = public_user(u) | {"status": u.get("status", "active"), "last_login_at": u.get("last_login_at")}
        pu["jobs"] = await col(Collections.research_jobs).count_documents({"user_id": u["_id"], "kind": "research"})
        out.append(pu)
    return {"items": out, "total": total}


@router.patch("/users/{user_id}")
async def update_user(user_id: str, body: UserUpdate, request: Request, admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    user = await col(Collections.users).find_one({"_id": user_id})
    if not user:
        raise NotFound("User not found.")
    upd: dict[str, Any] = {"updated_at": utcnow()}
    if body.role is not None:
        if body.role not in ROLES:
            raise AppError("Unknown role.", code="invalid_role", status_code=422)
        if user_id == admin.id and body.role != "ADMIN":
            raise AppError("You cannot remove your own admin role.", code="self_demotion", status_code=409)
        upd["role"] = body.role
    if body.status is not None:
        if user_id == admin.id:
            raise AppError("You cannot disable your own account.", code="self_disable", status_code=409)
        upd["status"] = body.status
    await col(Collections.users).update_one({"_id": user_id}, {"$set": upd})
    if body.status == "disabled" or body.role is not None:
        await revoke_all_sessions(user_id, reason="admin_change")
    await audit("admin.user_updated", actor_id=admin.id, target_id=user_id, ip=ratelimit.client_ip(request),
                metadata={k: v for k, v in body.model_dump().items() if v is not None})
    return {"user": public_user({**user, **upd})}


# --- Providers & models ------------------------------------------------------------------------

class ProviderConfigIn(BaseModel):
    default: ModelRef | None = None
    tasks: dict[str, ModelRef | None] | None = None
    cheap: ModelRef | None = None
    fallback: ModelRef | None = None
    allowed_user_models: list[AllowedModel] | None = None
    openai_compatible_base_url: str | None = Field(default=None, max_length=300)
    clear: list[str] = Field(default_factory=list, description="Fields to reset: cheap, fallback, default")


class KeyIn(BaseModel):
    provider: str
    api_key: str | None = Field(default=None, max_length=500)


class TestIn(BaseModel):
    provider: str
    model: str = Field(min_length=1, max_length=200)


async def _health_snapshot(kind: str, names: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        r = get_redis()
        for n in names:
            h = await r.hgetall(f"health:{kind}:{n}")
            out[n] = h or None
    except Exception:  # noqa: BLE001
        pass
    return out


@router.get("/providers")
async def providers() -> dict[str, Any]:
    await refresh_search_keys(force=True)
    cfg = await load_config()
    s = get_settings()
    caps = {}
    refs = [r for r in [cfg.default, cfg.cheap, cfg.fallback, *cfg.tasks.values(), *cfg.allowed_user_models] if r]
    for r in refs:
        caps[r.key] = resolve_capabilities(r, cfg).as_dict()
    return {
        "config": cfg.model_dump(mode="json", exclude={"discovered"}),
        "credentials": await credential_status(),
        "capabilities": caps,
        "health": await _health_snapshot("llm", list(PROVIDERS)),
        "search": {"configured": configured_search_providers(), "primary": s.SEARCH_PROVIDER,
                   "credentials": await credential_status(SEARCH_KEY_PROVIDERS),
                   "fallback_enabled": s.SEARCH_FALLBACK_ENABLED,
                   "health": await _health_snapshot("search", ["firecrawl", "tavily", "brave", "openalex", "builtin"])},
        "policy": {"allow_user_model_selection": s.ALLOW_USER_MODEL_SELECTION, "allow_user_api_keys": s.ALLOW_USER_API_KEYS,
                   "fallback_enabled": s.AI_FALLBACK_ENABLED, "demo_mode": s.DEMO_MODE},
        "health_note": "Health reflects real calls made by the system (last success/error) and explicit connection tests.",
    }


@router.put("/providers")
async def update_providers(body: ProviderConfigIn, request: Request, admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    cfg = await load_config()
    data = body.model_dump(exclude_unset=True, exclude={"clear"})
    if "tasks" in data and data["tasks"] is not None:
        bad = [t for t in data["tasks"] if t not in ("planning", "extraction", "verification", "synthesis", "charts")]
        if bad:
            raise AppError(f"Unknown task(s): {', '.join(bad)}", code="invalid_task", status_code=422)
    if body.openai_compatible_base_url:
        url = body.openai_compatible_base_url.strip()
        if not (url.startswith("https://") or (not get_settings().is_production and url.startswith("http://"))):
            raise AppError("The base URL must use https.", code="invalid_base_url", status_code=422)
    merged = AIConfig.model_validate({**cfg.model_dump(), **{k: v for k, v in data.items() if v is not None}})
    for f in body.clear:
        if f in ("cheap", "fallback", "default"):
            setattr(merged, f, None)
    await save_config(merged, admin.id)
    await audit("admin.providers_updated", actor_id=admin.id, ip=ratelimit.client_ip(request),
                metadata={"fields": sorted(data.keys()), "cleared": body.clear})
    return {"config": merged.model_dump(mode="json", exclude={"discovered"})}


@router.put("/providers/keys")
async def update_key(body: KeyIn, request: Request, admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    if body.provider not in (*PROVIDERS, *SEARCH_KEY_PROVIDERS):
        raise AppError("Unknown provider.", code="invalid_provider", status_code=422)
    status = (await credential_status((*PROVIDERS, *SEARCH_KEY_PROVIDERS)))[body.provider]
    if status["source"] == "environment":
        raise AppError("This key is set by an environment variable and can only be changed there.",
                       code="key_managed_by_environment", status_code=409)
    await set_api_key(body.provider, (body.api_key or "").strip() or None, admin.id)
    await refresh_search_keys(force=True)
    await audit("admin.provider_key_updated", actor_id=admin.id, ip=ratelimit.client_ip(request),
                metadata={"provider": body.provider, "removed": not body.api_key})
    return {"credentials": await credential_status(), "search_credentials": await credential_status(SEARCH_KEY_PROVIDERS)}


@router.post("/providers/test")
async def test_provider(body: TestIn, admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    await ratelimit.enforce(ratelimit.PROVIDER_TEST, f"user:{admin.id}")
    if body.provider not in (*PROVIDERS, "demo"):
        raise AppError("Unknown provider.", code="invalid_provider", status_code=422)
    cfg = await load_config()
    return await test_connection(ModelRef(provider=body.provider, model=body.model), cfg)  # type: ignore[arg-type]


@router.get("/providers/{provider}/models")
async def discover_models(provider: str, admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    """Live model discovery from the provider's API; stores reported limits as capabilities."""
    await ratelimit.enforce(ratelimit.PROVIDER_TEST, f"user:{admin.id}")
    if provider not in PROVIDERS:
        raise AppError("Unknown provider.", code="invalid_provider", status_code=422)
    key, _src = await get_api_key(provider)
    if not key:
        return {"ok": False, "error": "not_configured", "message": "Add an API key first.", "models": []}
    cfg = await load_config()
    prov = build_provider(provider, key, base_url=cfg.openai_compatible_base_url)
    try:
        models = await prov.list_models()
    except LLMError as e:
        return {"ok": False, "error": e.kind.value, "message": e.user_message, "models": []}
    finally:
        await prov.aclose()
    for m in models:
        if m.context_window or m.max_output_tokens:
            cfg.discovered[f"{provider}:{m.id}"] = {"context_window": m.context_window, "max_output_tokens": m.max_output_tokens,
                                                    "at": utcnow().isoformat()}
    await save_config(cfg, admin.id)
    return {"ok": True, "models": [m.model_dump() for m in models]}


class CapIn(BaseModel):
    provider: str
    model: str
    override: CapabilityOverride | None = None


@router.put("/providers/capabilities")
async def set_capabilities(body: CapIn, request: Request, admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    cfg = await load_config()
    key = f"{body.provider}:{body.model}"
    if body.override is None:
        cfg.capability_overrides.pop(key, None)
    else:
        cfg.capability_overrides[key] = body.override
    await save_config(cfg, admin.id)
    await audit("admin.capabilities_updated", actor_id=admin.id, ip=ratelimit.client_ip(request), metadata={"model": key})
    return {"capabilities": resolve_capabilities(ModelRef(provider=body.provider, model=body.model), cfg).as_dict()}  # type: ignore[arg-type]


class PriceIn(BaseModel):
    provider: str
    model: str
    price: PriceEntry | None = None


@router.put("/pricing")
async def set_price(body: PriceIn, request: Request, admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    cfg = await load_config()
    key = f"{body.provider}:{body.model}"
    if body.price is None:
        cfg.pricing.pop(key, None)
    else:
        cfg.pricing[key] = body.price
    await save_config(cfg, admin.id)
    await audit("admin.pricing_updated", actor_id=admin.id, ip=ratelimit.client_ip(request), metadata={"model": key})
    return {"pricing": {k: v.model_dump() for k, v in cfg.pricing.items()}}


# --- Usage --------------------------------------------------------------------------------------

@router.get("/usage")
async def usage_overview(days: int = Query(default=30, ge=1, le=365)) -> dict[str, Any]:
    since = utcnow() - timedelta(days=days)
    uc = col(Collections.usage_records)
    by_model = await aggregate(uc, [
        {"$match": {"created_at": {"$gte": since}, "kind": "llm"}},
        {"$group": {"_id": {"provider": "$provider", "model": "$model"}, "calls": {"$sum": 1},
                    "errors": {"$sum": {"$cond": [{"$ifNull": ["$error", False]}, 1, 0]}},
                    "input_tokens": {"$sum": "$input_tokens"}, "output_tokens": {"$sum": "$output_tokens"},
                    "cost": {"$sum": {"$ifNull": ["$cost_usd_est", 0]}},
                    "unknown_cost_calls": {"$sum": {"$cond": [{"$eq": ["$cost_known", False]}, 1, 0]}}}},
        {"$sort": {"cost": -1}}])
    by_search = await aggregate(uc, [
        {"$match": {"created_at": {"$gte": since}, "kind": "search"}},
        {"$group": {"_id": "$provider", "calls": {"$sum": 1}, "errors": {"$sum": {"$cond": [{"$eq": ["$ok", False]}, 1, 0]}}}}])
    by_user = await aggregate(uc, [
        {"$match": {"created_at": {"$gte": since}}},
        {"$group": {"_id": "$user_id", "calls": {"$sum": 1}, "cost": {"$sum": {"$ifNull": ["$cost_usd_est", 0]}},
                    "output_tokens": {"$sum": {"$ifNull": ["$output_tokens", 0]}}}},
        {"$sort": {"cost": -1}}, {"$limit": 25}])
    emails = {u["_id"]: u["email"] for u in await col(Collections.users).find(
        {"_id": {"$in": [r["_id"] for r in by_user if r["_id"]]}}, {"email": 1}).to_list(None)}
    # Alerts: unusual consumption in the last 24h relative to the window's daily average.
    day = utcnow() - timedelta(days=1)
    recent = await aggregate(uc, [{"$match": {"created_at": {"$gte": day}}},
                                  {"$group": {"_id": "$user_id", "calls": {"$sum": 1},
                                              "cost": {"$sum": {"$ifNull": ["$cost_usd_est", 0]}}}}])
    avg_by_user = {r["_id"]: r["calls"] / max(days, 1) for r in by_user}
    alerts = [{"user_id": r["_id"], "email": emails.get(r["_id"]), "calls_24h": r["calls"], "cost_24h": round(r["cost"], 4),
               "reason": "24h usage is more than 5× the user's daily average"}
              for r in recent if r["_id"] and r["calls"] > 50 and r["calls"] > 5 * avg_by_user.get(r["_id"], 0)]
    cfg = await load_config()
    return {"by_model": [{**r["_id"], **{k: v for k, v in r.items() if k != "_id"}} for r in by_model],
            "by_search_provider": [{"provider": r["_id"], "calls": r["calls"], "errors": r["errors"]} for r in by_search],
            "top_users": [{"user_id": r["_id"], "email": emails.get(r["_id"]), "calls": r["calls"], "cost": round(r["cost"], 4),
                           "output_tokens": r["output_tokens"]} for r in by_user],
            "alerts": alerts, "pricing": {k: v.model_dump() for k, v in cfg.pricing.items()},
            "note": "Costs are estimates from the configured pricing table (with as-of dates), not provider invoices."}


# --- Jobs ---------------------------------------------------------------------------------------

@router.get("/jobs")
async def jobs(status: str | None = None, dead_lettered: bool | None = None, limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    q: dict[str, Any] = {}
    if status:
        q["status"] = status
    if dead_lettered is not None:
        q["dead_lettered"] = dead_lettered
    items = await col(Collections.research_jobs).find(q, {"checkpoint": 0}).sort("created_at", -1).limit(limit).to_list(None)
    counts = await aggregate(col(Collections.research_jobs), [{"$group": {"_id": "$status", "n": {"$sum": 1}}}])
    # Admins see operational metadata, not report contents.
    return {"items": [{"id": j["_id"], "user_id": j["user_id"], "kind": j.get("kind"), "mode": j.get("mode"),
                       "status": j["status"], "stage": j.get("stage"), "attempts": j.get("attempts", 0),
                       "dead_lettered": bool(j.get("dead_lettered")), "last_error": j.get("last_error"),
                       "lease": {k: v for k, v in (j.get("lease") or {}).items() if k != "token"} or None,
                       "usage": j.get("usage", {}), "created_at": j.get("created_at"), "updated_at": j.get("updated_at"),
                       "question_preview": j["question"][:80]} for j in items],
            "counts": {c["_id"]: c["n"] for c in counts}, "queue_depth": await queue.queue_depth()}


@router.post("/jobs/{job_id}/retry")
async def admin_retry(job_id: str, request: Request, admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    res = await col(Collections.research_jobs).update_one(
        {"_id": job_id, "status": {"$in": ["failed", "waiting_for_retry"]}},
        {"$set": {"status": "queued", "attempts": 0, "next_attempt_at": None, "dead_lettered": False, "lease": None,
                  "deadline_at": None, "started_at": None, "updated_at": utcnow()}})
    if not res.modified_count:
        raise AppError("Only failed or waiting jobs can be retried.", code="invalid_state", status_code=409)
    await queue.enqueue(job_id)
    await audit("admin.job_retried", actor_id=admin.id, target_id=job_id, ip=ratelimit.client_ip(request))
    return {"queued": True}


@router.post("/jobs/{job_id}/cancel")
async def admin_cancel(job_id: str, request: Request, admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    await col(Collections.research_jobs).update_one({"_id": job_id}, {"$set": {"cancel_requested": True}})
    await audit("admin.job_cancelled", actor_id=admin.id, target_id=job_id, ip=ratelimit.client_ip(request))
    return {"cancel_requested": True}


@router.post("/jobs/reconcile")
async def admin_reconcile(admin: Principal = Depends(require_admin)) -> dict[str, Any]:
    return await lifecycle.reconcile()


# --- System health & audit -------------------------------------------------------------------------

@router.get("/system-health")
async def system_health() -> dict[str, Any]:
    s = get_settings()
    workers = []
    try:
        r = get_redis()
        async for key in r.scan_iter(match="dr:workers:*", count=100):
            raw = await r.get(key)
            if raw:
                workers.append(json.loads(raw))
    except Exception:  # noqa: BLE001
        pass
    stuck = await col(Collections.research_jobs).count_documents(
        {"status": {"$in": list(lifecycle.ACTIVE_STATUSES)}, "lease.expires_at": {"$lt": utcnow()}})
    return {
        "database": {"ok": await ping(), "kind": "in-memory (NOT durable)" if s.uses_memory_db else "mongodb"},
        "redis": {"ok": await redis_ping(), "kind": "in-memory (dev)" if not s.REDIS_URL else "redis"},
        "queue_depth": await queue.queue_depth(),
        "workers": workers,
        "embedded_worker": s.EMBEDDED_WORKER,
        "jobs_with_expired_leases": stuck,
        "config_warnings": s.config_warnings,
        "flags": {k: getattr(s, k) for k in ("DEMO_MODE", "BILLING_ENABLED", "GOOGLE_AUTH_ENABLED", "RATE_LIMIT_ENABLED",
                                             "AUDIT_LOG_ENABLED", "CONTENT_SAFETY_ENABLED", "FILE_UPLOADS_ENABLED",
                                             "CHARTS_ENABLED", "PUBLIC_REPORT_SHARING_ENABLED", "PUBLIC_SIGNUP_ENABLED",
                                             "ALLOW_USER_MODEL_SELECTION", "ALLOW_USER_API_KEYS")}
        | {"EMAIL_VERIFICATION": s.email_verification_required},
        "environment": s.APP_ENV,
    }


@router.get("/audit")
async def audit_logs(limit: int = Query(default=100, ge=1, le=500), action: str | None = None) -> dict[str, Any]:
    q: dict[str, Any] = {}
    if action:
        q["action"] = {"$regex": "^" + re.escape(action)}
    items = await col(Collections.audit_logs).find(q).sort("created_at", -1).limit(limit).to_list(None)
    return {"items": [{"id": a["_id"], **{k: a.get(k) for k in ("action", "actor_id", "target_id", "ip", "outcome",
                                                                  "metadata", "created_at")}} for a in items]}
