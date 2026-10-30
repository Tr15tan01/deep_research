"""Durable job lifecycle in MongoDB: leases, heartbeats, checkpoints, retries, dead-letter
and reconciliation."""

from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

from pymongo import ReturnDocument

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import new_token, utcnow
from app.db.mongo import Collections, col
from app.jobs import queue

log = get_logger("lifecycle")

ACTIVE_STATUSES = ("planning", "searching", "extracting", "verifying", "synthesizing")
RUNNABLE_IDLE = ("queued", "waiting_for_retry")
TERMINAL = ("completed", "failed", "cancelled")
OPEN_STATUSES = (*RUNNABLE_IDLE, *ACTIVE_STATUSES, "awaiting_approval")


def retry_delay_seconds(attempt: int, base: float = 15.0, cap: float = 900.0) -> float:
    """Exponential backoff with jitter for job-level retries."""
    exp = min(cap, base * (2 ** max(0, attempt - 1)))
    return exp / 2 + random.uniform(0, exp / 2)


async def claim(job_id: str | None, worker_id: str) -> dict[str, Any] | None:
    """Atomically take ownership of a runnable job (or any runnable job if job_id is None)."""
    s = get_settings()
    now = utcnow()
    token = new_token(16)
    lease = {"owner": worker_id, "token": token, "expires_at": now + timedelta(seconds=s.WORKER_LEASE_SECONDS),
             "heartbeat_at": now, "acquired_at": now}
    q: dict[str, Any] = {
        "cancel_requested": {"$ne": True},
        "$or": [
            {"status": {"$in": list(RUNNABLE_IDLE)}, "$or": [{"next_attempt_at": None}, {"next_attempt_at": {"$lte": now}}],
             "$and": [{"$or": [{"lease": None}, {"lease.expires_at": {"$lt": now}}]}]},
            # Crash recovery: a running job whose worker stopped heart-beating.
            {"status": {"$in": list(ACTIVE_STATUSES)}, "lease.expires_at": {"$lt": now}},
        ],
    }
    if job_id:
        q["_id"] = job_id
    job = await col(Collections.research_jobs).find_one_and_update(
        q, {"$set": {"lease": lease, "updated_at": now}, "$inc": {"run_count": 1}},
        sort=[("created_at", 1)], return_document=ReturnDocument.AFTER)
    if job and job.get("run_count", 1) > 1 and job.get("status") in ACTIVE_STATUSES:
        log.warning("recovered_job_after_lease_expiry", job_id=job["_id"], previous_status=job.get("status"))
    return job


async def heartbeat(job_id: str, token: str) -> bool:
    s = get_settings()
    now = utcnow()
    res = await col(Collections.research_jobs).update_one(
        {"_id": job_id, "lease.token": token},
        {"$set": {"lease.expires_at": now + timedelta(seconds=s.WORKER_LEASE_SECONDS), "lease.heartbeat_at": now}})
    return res.matched_count == 1


async def save_checkpoint(job_id: str, token: str, state: dict[str, Any]) -> bool:
    res = await col(Collections.research_jobs).update_one(
        {"_id": job_id, "lease.token": token},
        {"$set": {"checkpoint": {"next": state.get("next"), "state": state, "saved_at": utcnow()}, "updated_at": utcnow()},
         "$inc": {"checkpoint_version": 1}})
    return res.matched_count == 1


async def finish(job_id: str, token: str, status: str, **fields: Any) -> bool:
    upd = {"status": status, "lease": None, "updated_at": utcnow(), **fields}
    if status in TERMINAL:
        upd["finished_at"] = utcnow()
    res = await col(Collections.research_jobs).update_one({"_id": job_id, "lease.token": token}, {"$set": upd})
    return res.matched_count == 1


async def schedule_retry(job: dict[str, Any], token: str, error: dict[str, Any],
                         retry_after: float | None = None) -> str:
    """Bounded retry with exponential backoff + jitter; dead-letters after MAX_JOB_ATTEMPTS."""
    s = get_settings()
    attempts = int(job.get("attempts", 0)) + 1
    max_attempts = int(job.get("max_attempts") or s.MAX_JOB_ATTEMPTS)
    err = {**error, "at": utcnow(), "attempt": attempts}
    jobs = col(Collections.research_jobs)
    if attempts >= max_attempts:
        await jobs.update_one({"_id": job["_id"], "lease.token": token},
                              {"$set": {"status": "failed", "lease": None, "attempts": attempts, "dead_lettered": True,
                                        "last_error": {**err, "message": error.get("message", "") +
                                                       " Automatic retries are exhausted."},
                                        "finished_at": utcnow(), "updated_at": utcnow()},
                               "$push": {"error_history": {"$each": [err], "$slice": -20}}})
        await queue.push_dead_letter(job["_id"])
        return "dead_lettered"
    delay = max(retry_after or 0, retry_delay_seconds(attempts))
    await jobs.update_one({"_id": job["_id"], "lease.token": token},
                          {"$set": {"status": "waiting_for_retry", "lease": None, "attempts": attempts,
                                    "next_attempt_at": utcnow() + timedelta(seconds=delay), "last_error": err,
                                    "updated_at": utcnow()},
                           "$push": {"error_history": {"$each": [err], "$slice": -20}}})
    return f"retry_in_{int(delay)}s"


async def reconcile(limit: int = 200) -> dict[str, int]:
    """Re-dispatch jobs that are runnable in Mongo but may have lost their Redis delivery,
    and recover jobs whose lease expired (worker crash)."""
    now = utcnow()
    jobs = col(Collections.research_jobs)
    runnable = await jobs.find({
        "cancel_requested": {"$ne": True},
        "$or": [
            {"status": {"$in": list(RUNNABLE_IDLE)}, "$or": [{"next_attempt_at": None}, {"next_attempt_at": {"$lte": now}}],
             "$and": [{"$or": [{"lease": None}, {"lease.expires_at": {"$lt": now}}]}]},
            {"status": {"$in": list(ACTIVE_STATUSES)}, "lease.expires_at": {"$lt": now}},
        ],
    }, {"_id": 1}).limit(limit).to_list(None)
    for j in runnable:
        await queue.enqueue(j["_id"])
    # Jobs whose cancellation was requested while not running: finalise cancellation.
    stale_cancel = await jobs.find({"cancel_requested": True, "status": {"$in": list(RUNNABLE_IDLE) + ["awaiting_approval"]},
                                    "$or": [{"lease": None}, {"lease.expires_at": {"$lt": now}}]}, {"_id": 1, "user_id": 1}).to_list(None)
    for j in stale_cancel:
        await jobs.update_one({"_id": j["_id"], "status": {"$nin": list(TERMINAL)}},
                              {"$set": {"status": "cancelled", "lease": None, "finished_at": now, "updated_at": now}})
    return {"redispatched": len(runnable), "cancelled": len(stale_cancel)}
