"""Redis connection. Redis is used for queue delivery, rate limits, pub/sub wakeups and
caches. It is never the durable source of truth."""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("redis")

_redis: Any = None
MEMORY_REDIS_SCHEME = "memory://"


async def connect_redis(url: str | None = None) -> Any:
    global _redis
    settings = get_settings()
    url = url if url is not None else settings.REDIS_URL
    if not url or url.startswith(MEMORY_REDIS_SCHEME):
        if not url and settings.is_production:
            raise RuntimeError("REDIS_URL is required in production (use memory:// for single-process hosting)")
        import fakeredis

        # In-process Redis: fine when the API and the worker share one process (EMBEDDED_WORKER=1).
        # Contents vanish on restart; MongoDB stays the source of truth and the reconciler re-enqueues jobs.
        _redis = fakeredis.FakeAsyncRedis(decode_responses=True)
        log.warning("using_in_memory_redis", note="per-process; requires a single API instance with EMBEDDED_WORKER=1")
        return _redis
    import redis.asyncio as aioredis

    _redis = aioredis.from_url(url, decode_responses=True, socket_timeout=5, socket_connect_timeout=5,
                               health_check_interval=30, retry_on_timeout=True)
    return _redis


def use_redis(client: Any) -> None:
    global _redis
    _redis = client


def get_redis() -> Any:
    if _redis is None:
        raise RuntimeError("redis not initialised")
    return _redis


async def redis_ping() -> bool:
    try:
        return bool(await get_redis().ping())
    except Exception:  # noqa: BLE001
        return False


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        try:
            await _redis.aclose()
        except Exception:  # noqa: BLE001
            pass
    _redis = None
