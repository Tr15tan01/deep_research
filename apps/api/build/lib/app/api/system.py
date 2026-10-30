"""Health endpoints and public (non-secret) configuration."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.auth.deps import require_admin
from app.auth.google import google_available
from app.core.config import get_settings
from app.core.errors import NotFound
from app.db.mongo import ping
from app.db.redis import redis_ping
from app.llm.config_store import get_api_key, load_config
from app.research.modes import MODES
from app.search.service import SearchService
from app.services.mailer import DEV_OUTBOX

router = APIRouter(tags=["system"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready() -> JSONResponse:
    db = await ping()
    rd = await redis_ping()
    ok = db and rd
    return JSONResponse({"status": "ready" if ok else "not_ready", "checks": {"database": db, "queue": rd}},
                        status_code=200 if ok else 503)


@router.get("/health/dependencies", dependencies=[Depends(require_admin)])
@router.get("/api/v1/admin/dependencies", dependencies=[Depends(require_admin)])
async def dependencies() -> dict[str, Any]:
    """Detailed dependency status — admin only, never exposes secrets or hostnames."""
    s = get_settings()
    cfg = await load_config()
    ai_ok = False
    if cfg.default:
        key, _ = await get_api_key(cfg.default.provider)
        ai_ok = bool(key)
    return {"database": await ping(), "redis": await redis_ping(), "ai_configured": ai_ok or s.DEMO_MODE,
            "search_configured": (await SearchService.create()).available(), "smtp_configured": s.smtp_configured,
            "google_auth": google_available() if s.GOOGLE_AUTH_ENABLED else "disabled"}


@router.get("/api/v1/public/config")
async def public_config() -> dict[str, Any]:
    s = get_settings()
    cfg = await load_config()
    ai_ready = s.DEMO_MODE
    if not ai_ready and cfg.default:
        key, _ = await get_api_key(cfg.default.provider)
        ai_ready = bool(key)
    return {
        "app_name": s.APP_NAME,
        "environment": "production" if s.is_production else s.APP_ENV,
        "features": {
            "google_auth": s.GOOGLE_AUTH_ENABLED,
            "google_auth_configured": google_available(),
            "email_verification": s.email_verification_required,
            "password_reset": s.PASSWORD_RESET_ENABLED,
            "public_signup": s.PUBLIC_SIGNUP_ENABLED,
            "billing": s.BILLING_ENABLED,
            "uploads": s.FILE_UPLOADS_ENABLED,
            "charts": s.CHARTS_ENABLED,
            "public_sharing": s.PUBLIC_REPORT_SHARING_ENABLED,
            "user_model_selection": s.ALLOW_USER_MODEL_SELECTION,
            "user_api_keys": s.ALLOW_USER_API_KEYS,
            "demo_mode": s.DEMO_MODE,
            "content_safety": s.CONTENT_SAFETY_ENABLED,
        },
        "setup": {"ai_ready": ai_ready, "search_ready": s.DEMO_MODE or (await SearchService.create()).available(),
                  "scholarly_search": s.SCHOLARLY_SEARCH_ENABLED},
        "limits": {"max_file_size_mb": s.MAX_FILE_SIZE_MB, "max_uploads_per_job": s.MAX_RESEARCH_UPLOADS_PER_JOB,
                   "max_question_chars": 4000},
        "modes": [m.public() for m in MODES.values()],
    }


@router.get("/api/v1/dev/outbox")
async def dev_outbox() -> dict[str, Any]:
    """Development/test only: emails captured instead of being sent (no SMTP configured)."""
    s = get_settings()
    if s.is_production or s.smtp_configured:
        raise NotFound()
    return {"items": list(DEV_OUTBOX)[::-1]}
