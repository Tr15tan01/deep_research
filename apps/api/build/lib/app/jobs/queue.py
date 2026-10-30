"""Redis-backed job delivery.

Redis only *delivers* job IDs (wake-ups). MongoDB is the durable source of truth: a job is
accepted once its document is persisted; workers claim jobs with an atomic lease in Mongo,
so duplicate deliveries are harmless (idempotent dispatch) and lost deliveries are
recovered by the reconciler, which re-enqueues runnable jobs found in Mongo.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.db.redis import get_redis

log = get_logger("queue")
QUEUE_KEY = "dr:queue:jobs"
DEAD_LETTER_KEY = "dr:queue:dead"


async def enqueue(job_id: str) -> bool:
    try:
        await get_redis().lpush(QUEUE_KEY, job_id)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("enqueue_failed", job_id=job_id, error=type(e).__name__)
        return False


async def dequeue(timeout: float) -> str | None:
    res = await get_redis().brpop([QUEUE_KEY], timeout=max(1, int(timeout)))
    if not res:
        return None
    _key, job_id = res
    return job_id


async def push_dead_letter(job_id: str) -> None:
    try:
        r = get_redis()
        await r.lpush(DEAD_LETTER_KEY, job_id)
        await r.ltrim(DEAD_LETTER_KEY, 0, 999)
    except Exception:  # noqa: BLE001
        pass


async def queue_depth() -> int | None:
    try:
        return int(await get_redis().llen(QUEUE_KEY))
    except Exception:  # noqa: BLE001
        return None
