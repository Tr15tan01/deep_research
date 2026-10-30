"""Server-side usage limits and plan entitlements."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any

from app.core.config import get_settings
from app.core.errors import AppError, LimitExceeded
from app.core.security import as_utc, utcnow
from app.db.mongo import Collections, aggregate, col


@dataclass(frozen=True)
class PlanLimits:
    plan: str
    label: str
    daily_jobs: int
    concurrent_jobs: int
    monthly_cost_usd: float
    allowed_modes: tuple[str, ...]
    max_uploads_per_job: int
    price_label: str = ""


ALL_MODES = ("quick", "standard", "deep", "academic", "competitive", "technology", "market", "documents", "verify_claim",
             "counterarguments")


def plan_catalog() -> dict[str, PlanLimits]:
    s = get_settings()
    return {
        "free": PlanLimits("free", "Free", daily_jobs=min(5, s.DAILY_RESEARCH_JOBS_PER_USER), concurrent_jobs=1,
                           monthly_cost_usd=min(2.0, s.MONTHLY_COST_LIMIT_USD_PER_USER),
                           allowed_modes=("quick", "standard", "verify_claim", "documents"), max_uploads_per_job=2),
        "pro": PlanLimits("pro", "Pro", daily_jobs=s.DAILY_RESEARCH_JOBS_PER_USER,
                          concurrent_jobs=s.MAX_CONCURRENT_RESEARCH_JOBS_PER_USER,
                          monthly_cost_usd=s.MONTHLY_COST_LIMIT_USD_PER_USER, allowed_modes=ALL_MODES,
                          max_uploads_per_job=s.MAX_RESEARCH_UPLOADS_PER_JOB),
    }


def development_limits() -> PlanLimits:
    s = get_settings()
    return PlanLimits("unlimited-dev" if not s.is_production else "default", "Development limits",
                      daily_jobs=s.DAILY_RESEARCH_JOBS_PER_USER, concurrent_jobs=s.MAX_CONCURRENT_RESEARCH_JOBS_PER_USER,
                      monthly_cost_usd=s.MONTHLY_COST_LIMIT_USD_PER_USER, allowed_modes=ALL_MODES,
                      max_uploads_per_job=s.MAX_RESEARCH_UPLOADS_PER_JOB)


async def entitlements(user: dict[str, Any]) -> dict[str, Any]:
    """Resolve the user's effective limits. Never trusts the client; reads subscription state."""
    s = get_settings()
    if not s.BILLING_ENABLED:
        lim = development_limits()
        return {"limits": lim, "billing_enabled": False, "subscription": None, "can_start_jobs": True, "reason": None}
    sub = await col(Collections.subscriptions).find_one({"user_id": user["_id"]})
    catalog = plan_catalog()
    status = (sub or {}).get("status")
    plan = (sub or {}).get("plan", "free")
    can_start = True
    reason = None
    if status in ("active", "trialing"):
        lim = catalog.get(plan, catalog["free"])
    elif status == "past_due":
        grace_until = as_utc((sub or {}).get("grace_until"))
        in_grace = bool(grace_until and grace_until > utcnow())
        lim = catalog.get(plan, catalog["free"]) if in_grace else catalog["free"]
        if in_grace and not s.BILLING_GRACE_ALLOWS_NEW_JOBS:
            can_start, reason = False, "Your payment failed. Update your payment method to start new research."
        elif not in_grace:
            reason = "Your payment failed and the grace period ended; you are on the Free plan limits."
    else:
        lim = catalog["free"]
    return {"limits": lim, "billing_enabled": True, "subscription": sub, "can_start_jobs": can_start, "reason": reason}


async def month_cost(user_id: str) -> float:
    start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = await aggregate(col(Collections.usage_records), [
        {"$match": {"user_id": user_id, "created_at": {"$gte": start}, "cost_usd_est": {"$ne": None}}},
        {"$group": {"_id": None, "total": {"$sum": "$cost_usd_est"}}},
    ])
    return float(rows[0]["total"]) if rows else 0.0


async def usage_snapshot(user: dict[str, Any]) -> dict[str, Any]:
    ent = await entitlements(user)
    lim: PlanLimits = ent["limits"]
    jobs = col(Collections.research_jobs)
    from app.jobs.lifecycle import ACTIVE_STATUSES, RUNNABLE_IDLE

    active = await jobs.count_documents({"user_id": user["_id"], "kind": "research",
                                         "status": {"$in": list(ACTIVE_STATUSES) + list(RUNNABLE_IDLE)}})
    daily = await jobs.count_documents({"user_id": user["_id"], "kind": "research",
                                        "created_at": {"$gte": utcnow() - timedelta(days=1)}})
    cost = await month_cost(user["_id"])
    return {"plan": asdict(lim), "billing_enabled": ent["billing_enabled"], "active_jobs": active, "jobs_last_24h": daily,
            "month_cost_usd_est": round(cost, 4), "can_start_jobs": ent["can_start_jobs"], "notice": ent["reason"],
            "cost_note": "Costs are estimates from a configurable pricing table, not provider invoices."}


async def check_can_start(user: dict[str, Any], mode: str, uploads: int) -> PlanLimits:
    snap = await usage_snapshot(user)
    lim = PlanLimits(**{**snap["plan"], "allowed_modes": tuple(snap["plan"]["allowed_modes"])})
    if not snap["can_start_jobs"]:
        raise AppError(snap["notice"] or "Your plan does not allow new research right now.", code="billing_required",
                       status_code=402)
    if mode not in lim.allowed_modes:
        raise LimitExceeded(f"The {mode.replace('_', ' ')} mode is not included in your plan.", code="mode_not_allowed")
    if snap["active_jobs"] >= lim.concurrent_jobs:
        raise LimitExceeded(f"You already have {snap['active_jobs']} research job(s) running. Wait for one to finish or cancel it.",
                            code="concurrency_limit", status_code=429)
    if snap["jobs_last_24h"] >= lim.daily_jobs:
        raise LimitExceeded("You have reached your daily research limit. Try again later.", code="daily_limit", status_code=429)
    if lim.monthly_cost_usd and snap["month_cost_usd_est"] >= lim.monthly_cost_usd:
        raise LimitExceeded("You have reached this month's usage budget.", code="monthly_budget")
    if uploads > lim.max_uploads_per_job:
        raise LimitExceeded(f"Your plan allows up to {lim.max_uploads_per_job} documents per research job.",
                            code="upload_limit")
    return lim
