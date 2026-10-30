"""Per-job execution context: budgets, atomic usage accounting, events and cancellation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from pymongo import ReturnDocument

from app.core.logging import get_logger
from app.core.security import as_utc, utcnow
from app.db.mongo import Collections, col, new_id
from app.db.redis import get_redis

log = get_logger("job")
MAX_EVENTS_PER_JOB = 3000
ESSENTIAL_EVENTS = {"status", "stage", "error", "completed", "failed", "cancelled", "retry", "report"}


class BudgetExceeded(Exception):
    def __init__(self, resource: str, message: str | None = None) -> None:
        self.resource = resource
        super().__init__(message or f"budget exhausted: {resource}")


class JobCancelled(Exception):
    pass


class DeadlineExceeded(Exception):
    pass


@dataclass
class Budgets:
    max_search_calls: int
    max_sources: int
    max_tool_calls: int
    max_output_tokens: int
    max_cost_usd: float
    max_duration_seconds: int
    max_iterations: int
    max_subquestions: int
    results_per_query: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JobContext:
    job_id: str
    user_id: str
    budgets: Budgets
    deadline_at: datetime | None
    is_demo: bool = False
    lease_token: str | None = None
    stage: str = "queued"
    _event_count_cache: int = field(default=0, repr=False)

    # --- Cancellation & deadline --------------------------------------------------------
    async def check_alive(self) -> None:
        job = await col(Collections.research_jobs).find_one({"_id": self.job_id}, {"cancel_requested": 1, "lease": 1})
        if not job:
            raise JobCancelled("job deleted")
        if job.get("cancel_requested"):
            raise JobCancelled("cancel requested")
        if self.lease_token and (job.get("lease") or {}).get("token") != self.lease_token:
            # Another worker owns the job now (our lease expired); stop immediately.
            raise JobCancelled("lease lost")
        if self.deadline_at and utcnow() >= as_utc(self.deadline_at):  # type: ignore[operator]
            raise DeadlineExceeded()

    def seconds_left(self) -> float:
        if not self.deadline_at:
            return float("inf")
        return (as_utc(self.deadline_at) - utcnow()).total_seconds()  # type: ignore[operator]

    # --- Usage --------------------------------------------------------------------------
    async def usage(self) -> dict[str, Any]:
        job = await col(Collections.research_jobs).find_one({"_id": self.job_id}, {"usage": 1})
        return (job or {}).get("usage", {})

    # Calls held back during the gathering phases so synthesis/verification can always run.
    final_reserve_calls: int = 0

    async def reserve_tool_call(self, kind: str) -> None:
        """Atomically reserve one tool call (and one search call when kind == 'search').

        While ``final_reserve_calls`` > 0 (gathering phases), that many calls stay reserved
        for synthesis and validation."""
        limit = self.budgets.max_tool_calls - (self.final_reserve_calls if kind != "llm-final" else 0)
        q: dict[str, Any] = {"_id": self.job_id, "usage.tool_calls": {"$lt": max(limit, 0)}}
        inc: dict[str, int] = {"usage.tool_calls": 1}
        if kind == "search":
            q["usage.search_calls"] = {"$lt": self.budgets.max_search_calls}
            inc["usage.search_calls"] = 1
        res = await col(Collections.research_jobs).find_one_and_update(q, {"$inc": inc}, projection={"_id": 1})
        if res is None:
            raise BudgetExceeded("search_calls" if kind == "search" else "tool_calls")

    async def add_usage(self, **inc: float) -> None:
        if inc:
            await col(Collections.research_jobs).update_one({"_id": self.job_id},
                                                            {"$inc": {f"usage.{k}": v for k, v in inc.items()}})

    async def remaining_output_tokens(self) -> int:
        u = await self.usage()
        return max(0, self.budgets.max_output_tokens - int(u.get("output_tokens", 0)))

    async def remaining_cost(self) -> float:
        u = await self.usage()
        return max(0.0, self.budgets.max_cost_usd - float(u.get("cost_usd_est", 0.0)))

    # --- Events -------------------------------------------------------------------------
    async def emit(self, type_: str, message: str, data: dict[str, Any] | None = None, *, stage: str | None = None,
                   level: str = "info") -> int | None:
        return await emit_event(self.job_id, self.user_id, type_, message, data, stage=stage or self.stage, level=level)

    async def set_stage(self, stage: str, status: str | None = None, message: str | None = None) -> None:
        self.stage = stage
        upd: dict[str, Any] = {"stage": stage, "updated_at": utcnow()}
        if status:
            upd["status"] = status
        await col(Collections.research_jobs).update_one({"_id": self.job_id}, {"$set": upd})
        await self.emit("stage", message or stage, {"stage": stage, "status": status}, stage=stage)


async def emit_event(job_id: str, user_id: str, type_: str, message: str, data: dict[str, Any] | None = None, *,
                     stage: str | None = None, level: str = "info") -> int | None:
    jobs = col(Collections.research_jobs)
    job = await jobs.find_one_and_update({"_id": job_id}, {"$inc": {"event_seq": 1}},
                                         projection={"event_seq": 1}, return_document=ReturnDocument.AFTER)
    if job is None:
        return None
    seq = int(job["event_seq"])
    if seq > MAX_EVENTS_PER_JOB and type_ not in ESSENTIAL_EVENTS:
        return None  # keep execution history bounded
    evt = {
        "_id": new_id("evt"),
        "job_id": job_id,
        "user_id": user_id,
        "seq": seq,
        "type": type_,
        "stage": stage,
        "level": level,
        "message": message[:500],
        "data": data or {},
        "created_at": utcnow(),
    }
    await col(Collections.job_events).insert_one(evt)
    try:
        await get_redis().publish(f"job:{job_id}:events", json.dumps({"seq": seq}))
    except Exception:  # noqa: BLE001 — SSE falls back to polling Mongo
        pass
    return seq
