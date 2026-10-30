"""Distributed fixed-window rate limiting backed by Redis.

If Redis is unreachable, limits *fail open* (requests proceed) and a warning is logged:
rate limiting is abuse mitigation, while authentication/authorization remain enforced
independently. Job acceptance, which needs Redis for delivery, fails closed elsewhere.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import RateLimited
from app.core.logging import get_logger
from app.db.redis import get_redis

log = get_logger("ratelimit")


@dataclass(frozen=True)
class Limit:
    name: str
    max_requests: int
    window_seconds: int


AUTH_LOGIN = Limit("auth_login", 10, 300)
AUTH_REGISTER = Limit("auth_register", 5, 3600)
AUTH_EMAIL = Limit("auth_email", 5, 3600)  # password reset / verification resend
AUTH_REFRESH = Limit("auth_refresh", 60, 300)
RESEARCH_CREATE = Limit("research_create", 20, 3600)
API_GENERAL = Limit("api_general", 600, 60)
UPLOAD = Limit("upload", 40, 3600)
PROVIDER_TEST = Limit("provider_test", 20, 300)


def client_ip(request: Request) -> str:
    """Resolve the client IP, trusting only the configured number of proxy hops."""
    if get_settings().INTERNAL_PROXY_TOKEN:
        # Requests can only arrive through our own web proxy (InternalTokenMiddleware), which reports the
        # client IP it saw in X-DR-Client-IP after discarding any client-supplied value.
        forwarded = request.headers.get("x-dr-client-ip", "").strip()
        if forwarded:
            return forwarded[:64]
    hops = get_settings().TRUSTED_PROXY_HOPS
    xff = request.headers.get("x-forwarded-for", "")
    if hops > 0 and xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    return request.client.host if request.client else "unknown"


async def hit(limit: Limit, key: str) -> tuple[bool, int]:
    """Returns (allowed, retry_after_seconds)."""
    if not get_settings().RATE_LIMIT_ENABLED:
        return True, 0
    window = int(time.time() // limit.window_seconds)
    rkey = f"rl:{limit.name}:{key}:{window}"
    try:
        r = get_redis()
        pipe = r.pipeline()
        pipe.incr(rkey)
        pipe.expire(rkey, limit.window_seconds + 5)
        count, _ = await pipe.execute()
    except Exception as e:  # noqa: BLE001
        log.warning("rate_limit_backend_unavailable", limit=limit.name, error=type(e).__name__)
        return True, 0
    if int(count) > limit.max_requests:
        retry_after = limit.window_seconds - int(time.time() % limit.window_seconds)
        return False, max(retry_after, 1)
    return True, 0


async def enforce(limit: Limit, *keys: str) -> None:
    for key in keys:
        allowed, retry_after = await hit(limit, key)
        if not allowed:
            raise RateLimited(headers={"Retry-After": str(retry_after)}, details={"retry_after_seconds": retry_after})
