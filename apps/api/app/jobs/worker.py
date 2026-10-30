"""Background worker: claims jobs, runs them with heartbeats and checkpoints, and maps
every failure to a precise, user-actionable outcome."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import socket
from datetime import timedelta
from typing import Any

from pymongo.errors import AutoReconnect, ConnectionFailure, NetworkTimeout, PyMongoError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import as_utc, utcnow
from app.db.mongo import Collections, col, new_id
from app.jobs import lifecycle, queue
from app.llm.base import USER_MESSAGES, ErrorKind, LLMError
from app.llm.config_store import ModelRef
from app.llm.service import AIService
from app.research.context import BudgetExceeded, DeadlineExceeded, JobCancelled, JobContext, emit_event
from app.research.modes import MODES, budgets_for
from app.research.pipeline import Deps, PauseForApproval, StepFailed, StepRetryable, run_graph
from app.research.reports import build_partial_report
from app.research.schemas import ResearchState
from app.search.service import SearchService

log = get_logger("worker")

NON_RETRYABLE_RESUMABLE = {ErrorKind.AUTH, ErrorKind.QUOTA, ErrorKind.BILLING, ErrorKind.NOT_CONFIGURED,
                           ErrorKind.MODEL_NOT_FOUND, ErrorKind.UNSUPPORTED, ErrorKind.CONTEXT_OVERFLOW}


def make_context(job: dict[str, Any], token: str) -> JobContext:
    b = budgets_for(job["mode"], job.get("options", {}).get("budget_overrides"))
    return JobContext(job_id=job["_id"], user_id=job["user_id"], budgets=b, deadline_at=job.get("deadline_at"),
                      is_demo=bool(job.get("is_demo")), lease_token=token, stage=job.get("stage") or "queued")


async def _notify(user_id: str, job: dict[str, Any], kind: str, title: str, body: str) -> None:
    try:
        await col(Collections.notifications).insert_one({
            "_id": new_id("ntf"), "user_id": user_id, "kind": kind, "title": title, "body": body,
            "link": f"/research/{job['_id']}", "read": False, "created_at": utcnow()})
    except Exception:  # noqa: BLE001
        pass


class Worker:
    def __init__(self, concurrency: int | None = None, worker_id: str | None = None) -> None:
        s = get_settings()
        self.concurrency = concurrency or s.WORKER_CONCURRENCY
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}"
        self.stopping = asyncio.Event()
        self.active: dict[str, asyncio.Task[Any]] = {}

    # --- loop ---------------------------------------------------------------------------
    async def run(self, install_signals: bool = True) -> None:
        if install_signals:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                with contextlib.suppress(NotImplementedError, RuntimeError):
                    loop.add_signal_handler(sig, self.stopping.set)
        log.info("worker_started", worker_id=self.worker_id, concurrency=self.concurrency)
        tasks = [asyncio.create_task(self._consumer(i)) for i in range(self.concurrency)]
        tasks.append(asyncio.create_task(self._reconciler()))
        await self.stopping.wait()
        log.info("worker_stopping", active=len(self.active))
        # Graceful shutdown: let in-flight steps reach a checkpoint, then release.
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        log.info("worker_stopped")

    async def _reconciler(self) -> None:
        s = get_settings()
        started = utcnow().isoformat()
        while not self.stopping.is_set():
            try:
                import json as _json

                from app.db.redis import get_redis

                await get_redis().set(f"dr:workers:{self.worker_id}", _json.dumps({
                    "id": self.worker_id, "active_jobs": list(self.active), "concurrency": self.concurrency,
                    "started_at": started, "seen_at": utcnow().isoformat()}), ex=int(max(30, s.WORKER_POLL_SECONDS * 8)))
            except Exception:  # noqa: BLE001,S110
                pass
            try:
                stats = await lifecycle.reconcile()
                touch_health_file(s.WORKER_HEALTH_FILE)
                if stats["redispatched"] or stats["cancelled"]:
                    log.info("reconciled", **stats)
            except Exception as e:  # noqa: BLE001
                log.warning("reconcile_failed", error=type(e).__name__)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.stopping.wait(), timeout=max(5.0, s.WORKER_POLL_SECONDS * 3))

    async def _consumer(self, idx: int) -> None:
        s = get_settings()
        while not self.stopping.is_set():
            job_id: str | None = None
            try:
                job_id = await queue.dequeue(timeout=s.WORKER_POLL_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — Redis down: fall back to polling Mongo
                log.warning("dequeue_failed", error=type(e).__name__)
                await asyncio.sleep(s.WORKER_POLL_SECONDS)
            try:
                job = await lifecycle.claim(job_id, self.worker_id) if job_id else await lifecycle.claim(None, self.worker_id)
            except PyMongoError as e:
                log.warning("claim_failed", error=type(e).__name__)
                await asyncio.sleep(s.WORKER_POLL_SECONDS)
                continue
            if job is None:
                continue
            task = asyncio.create_task(self.process(job))
            self.active[job["_id"]] = task
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                # Shutdown requested: give the job a short window to checkpoint, then release its lease.
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(task, timeout=20)
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(BaseException):
                        await task
                raise
            finally:
                self.active.pop(job["_id"], None)

    # --- execution ----------------------------------------------------------------------
    async def process(self, job: dict[str, Any]) -> None:
        token = job["lease"]["token"]
        s = get_settings()
        now = utcnow()
        jobs = col(Collections.research_jobs)
        sets: dict[str, Any] = {}
        if not job.get("started_at"):
            sets["started_at"] = now
        if not job.get("deadline_at"):
            budget = budgets_for(job["mode"], job.get("options", {}).get("budget_overrides"))
            remaining = max(60, budget.max_duration_seconds - int(job.get("elapsed_seconds_before_pause", 0)))
            sets["deadline_at"] = now + timedelta(seconds=remaining)
            job["deadline_at"] = sets["deadline_at"]
        elif job["status"] in lifecycle.ACTIVE_STATUSES and int(job.get("run_count", 1)) > 1:
            # Recovered after the previous worker stopped (crash, or a sleeping free-tier host). Time spent with
            # no worker alive is not research time, so move the deadline forward by that gap.
            saved = as_utc((job.get("checkpoint") or {}).get("saved_at"))
            deadline = as_utc(job.get("deadline_at"))
            if saved and deadline and now > saved:
                gap = now - saved
                sets["deadline_at"] = deadline + gap
                job["deadline_at"] = sets["deadline_at"]
                log.info("deadline_extended_after_recovery", job_id=job["_id"], seconds=int(gap.total_seconds()))
        if job["status"] in lifecycle.RUNNABLE_IDLE:
            sets["status"] = "planning" if job.get("kind", "research") == "research" else "synthesizing"
        if sets:
            await jobs.update_one({"_id": job["_id"], "lease.token": token}, {"$set": sets})
        ctx = make_context(job, token)
        hb = asyncio.create_task(self._heartbeat(job["_id"], token))
        try:
            kind = job.get("kind", "research")
            if kind == "research":
                await self._run_research(job, ctx, token)
            elif kind == "regenerate_section":
                await self._run_regenerate(job, ctx, token)
            elif kind == "export":
                from app.services.exports import run_export_job

                await run_export_job(job, ctx, token)
            else:
                await lifecycle.finish(job["_id"], token, "failed",
                                       last_error={"code": "unknown_kind", "message": "Unknown job type."})
        except asyncio.CancelledError:
            # Graceful shutdown: release the lease so another worker resumes from the checkpoint.
            await jobs.update_one({"_id": job["_id"], "lease.token": token},
                                  {"$set": {"status": "queued", "lease": None, "updated_at": utcnow()}})
            await queue.enqueue(job["_id"])
            raise
        finally:
            hb.cancel()
            with contextlib.suppress(BaseException):
                await hb
        del s

    async def _heartbeat(self, job_id: str, token: str) -> None:
        s = get_settings()
        while True:
            await asyncio.sleep(s.WORKER_HEARTBEAT_SECONDS)
            try:
                if not await lifecycle.heartbeat(job_id, token):
                    log.warning("lease_lost", job_id=job_id)
                    return
            except Exception as e:  # noqa: BLE001
                log.warning("heartbeat_failed", job_id=job_id, error=type(e).__name__)

    async def _run_research(self, job: dict[str, Any], ctx: JobContext, token: str) -> None:
        opts = job.get("options", {})
        cp = (job.get("checkpoint") or {}).get("state")
        state = ResearchState.model_validate(cp) if cp else ResearchState(
            job_id=job["_id"], user_id=job["user_id"], question=job["question"], mode=job["mode"], options=opts,
            clarifications=job.get("clarifications", []))
        # Options edited while paused (plan approval) are applied to the checkpoint by the API.
        user_choice = ModelRef(**opts["model"]) if opts.get("model") else None
        ai = await AIService.create(user_id=job["user_id"], job=ctx, user_choice=user_choice,
                                    use_user_key=bool(opts.get("use_own_key")))
        search = await SearchService.create(job=ctx, user_id=job["user_id"])
        jobs = col(Collections.research_jobs)
        await jobs.update_one({"_id": job["_id"]}, {"$set": {"model_config": ai.describe()}})
        if job.get("run_count", 1) > 1 and cp:
            await ctx.emit("recovery", f"Resuming from checkpoint at step “{state.next}”",
                           {"next": state.next, "run": job.get("run_count")})

        async def persist(st: ResearchState) -> None:
            if not await lifecycle.save_checkpoint(job["_id"], token, st.model_dump(mode="json")):
                raise JobCancelled("lease lost")

        deps = Deps(ctx=ctx, ai=ai, search=search, mode=MODES.get(job["mode"], MODES["standard"]), persist=persist)
        try:
            final = await run_graph(state, deps)
            await lifecycle.finish(job["_id"], token, "completed", stage="done", last_error=None)
            await emit_event(job["_id"], job["user_id"], "completed", "Research complete",
                             {"report_id": final.report_id}, stage="done")
            await _notify(job["user_id"], job, "research_completed", "Research complete", job["question"][:140])
        except PauseForApproval:
            started = as_utc(job.get("started_at")) or utcnow()
            elapsed = int((utcnow() - started).total_seconds()) + int(job.get("elapsed_seconds_before_pause", 0))
            await lifecycle.finish(job["_id"], token, "awaiting_approval", stage="awaiting_approval",
                                   deadline_at=None, elapsed_seconds_before_pause=elapsed)
            await emit_event(job["_id"], job["user_id"], "status", "Plan ready for your review", {"status": "awaiting_approval"},
                             stage="planning")
            await _notify(job["user_id"], job, "plan_ready", "Research plan ready for review", job["question"][:140])
        except JobCancelled as e:
            await self._handle_cancel(job, ctx, token, state_from(job, state), str(e))
        except DeadlineExceeded:
            await self._fail(job, ctx, token, "deadline_exceeded",
                             "The research reached its maximum duration before finishing.", resumable=False,
                             partial_reason="time limit reached")
        except StepFailed as e:
            await self._fail(job, ctx, token, e.code, e.message, resumable=e.resumable,
                             partial_reason=f"stopped: {e.code.replace('_', ' ')}")
        except StepRetryable as e:
            await self._retry(job, ctx, token, {"code": "transient", "message": e.reason, "retryable": True}, e.retry_after)
        except BudgetExceeded as e:
            await self._fail(job, ctx, token, "budget_exhausted", f"The research reached its {e.resource.replace('_', ' ')} budget.",
                             resumable=False, partial_reason="budget reached")
        except LLMError as e:
            if e.kind == ErrorKind.BUDGET:
                await self._fail(job, ctx, token, "budget_exhausted", USER_MESSAGES[ErrorKind.BUDGET], resumable=False,
                                 partial_reason="budget reached")
            elif e.retryable:
                await self._retry(job, ctx, token, {"code": e.kind.value, "message": e.user_message, "provider": e.provider,
                                                    "retryable": True}, e.retry_after)
            else:
                await self._fail(job, ctx, token, e.kind.value, e.user_message,
                                 resumable=e.kind in NON_RETRYABLE_RESUMABLE, partial_reason=f"AI provider error: {e.kind.value}")
        except (AutoReconnect, ConnectionFailure, NetworkTimeout) as e:
            log.warning("job_db_error", job_id=job["_id"], error=type(e).__name__)
            with contextlib.suppress(Exception):
                await self._retry(job, ctx, token, {"code": "database_unavailable",
                                                    "message": "The database was temporarily unavailable.", "retryable": True})
        except Exception as e:  # noqa: BLE001 — unexpected: bounded retries then dead-letter
            log.exception("job_unexpected_error", job_id=job["_id"], error_type=type(e).__name__)
            from app.core.tracking import capture

            capture(e, job_id=job["_id"], stage=ctx.stage)
            await self._retry(job, ctx, token, {"code": "internal_error",
                                                "message": "An unexpected error occurred while running the research.",
                                                "retryable": True})
        finally:
            await ai.aclose()
            await search.aclose()

    async def _current_state(self, job_id: str, fallback: ResearchState) -> ResearchState:
        j = await col(Collections.research_jobs).find_one({"_id": job_id}, {"checkpoint": 1})
        cp = ((j or {}).get("checkpoint") or {}).get("state")
        return ResearchState.model_validate(cp) if cp else fallback

    async def _retry(self, job: dict[str, Any], ctx: JobContext, token: str, error: dict[str, Any],
                     retry_after: float | None = None) -> None:
        latest = await col(Collections.research_jobs).find_one({"_id": job["_id"]}) or job
        outcome = await lifecycle.schedule_retry(latest, token, error, retry_after)
        if outcome == "dead_lettered":
            await emit_event(job["_id"], job["user_id"], "failed", error["message"] + " Automatic retries are exhausted.",
                             {**error, "dead_lettered": True}, stage=ctx.stage, level="error")
            st = await self._current_state(job["_id"], ResearchState(job_id=job["_id"], user_id=job["user_id"],
                                                                      question=job["question"], mode=job["mode"]))
            await self._partial(st, ctx, "repeated failures")
            await _notify(job["user_id"], job, "research_failed", "Research failed", error["message"][:200])
        else:
            await emit_event(job["_id"], job["user_id"], "retry", f"{error['message']} Retrying automatically.",
                             {**error, "outcome": outcome}, stage=ctx.stage, level="warning")

    async def _fail(self, job: dict[str, Any], ctx: JobContext, token: str, code: str, message: str, *, resumable: bool,
                    partial_reason: str) -> None:
        st = await self._current_state(job["_id"], ResearchState(job_id=job["_id"], user_id=job["user_id"],
                                                                  question=job["question"], mode=job["mode"]))
        await self._partial(st, ctx, partial_reason)
        await lifecycle.finish(job["_id"], token, "failed",
                               last_error={"code": code, "message": message, "retryable": False, "resumable": resumable,
                                           "at": utcnow()})
        await emit_event(job["_id"], job["user_id"], "failed", message, {"code": code, "resumable": resumable},
                         stage=ctx.stage, level="error")
        await _notify(job["user_id"], job, "research_failed", "Research stopped", message[:200])

    async def _partial(self, st: ResearchState, ctx: JobContext, reason: str) -> None:
        try:
            ctx.lease_token = None  # partial-report writes must not be blocked by lease checks
            await build_partial_report(st, ctx, reason)
        except Exception as e:  # noqa: BLE001
            log.warning("partial_report_failed", job_id=ctx.job_id, error=type(e).__name__)

    async def _handle_cancel(self, job: dict[str, Any], ctx: JobContext, token: str, st: ResearchState, reason: str) -> None:
        latest = await col(Collections.research_jobs).find_one({"_id": job["_id"]}) or {}
        if latest.get("cancel_requested"):
            st = await self._current_state(job["_id"], st)
            await self._partial(st, ctx, "cancelled by user")
            await col(Collections.research_jobs).update_one(
                {"_id": job["_id"]}, {"$set": {"status": "cancelled", "lease": None, "finished_at": utcnow(), "updated_at": utcnow()}})
            await emit_event(job["_id"], job["user_id"], "cancelled", "Research cancelled", {}, stage=ctx.stage)
        else:
            log.warning("job_stopped_lease_lost", job_id=job["_id"], reason=reason)

    async def _run_regenerate(self, job: dict[str, Any], ctx: JobContext, token: str) -> None:
        from app.research.reports import regenerate_section

        opts = job.get("options", {})
        parent = await col(Collections.research_jobs).find_one({"_id": opts["parent_job_id"], "user_id": job["user_id"]})
        report = await col(Collections.research_reports).find_one({"_id": opts["report_id"], "user_id": job["user_id"]})
        ai = await AIService.create(user_id=job["user_id"], job=ctx)
        try:
            if not parent or not report:
                raise StepFailed("not_found", "The report to update no longer exists.")
            await ctx.set_stage("writing", status="synthesizing", message="Regenerating section")
            # Evidence lives under the parent job; charge usage to this job but read the parent's ledger.
            new = await regenerate_section(parent, report, opts["section_id"], opts.get("instruction", ""), ctx, ai)
            await lifecycle.finish(job["_id"], token, "completed", stage="done", report_id=new["_id"],
                                   report_version=new["version"])
            await emit_event(job["_id"], job["user_id"], "completed", "Section regenerated",
                             {"report_id": new["_id"], "version": new["version"]}, stage="done")
            await emit_event(parent["_id"], job["user_id"], "report", f"Section regenerated (version {new['version']})",
                             {"report_id": new["_id"], "version": new["version"]}, stage="done")
        except StepFailed as e:
            await lifecycle.finish(job["_id"], token, "failed", last_error={"code": e.code, "message": e.message})
        except LLMError as e:
            if e.retryable:
                await self._retry(job, ctx, token, {"code": e.kind.value, "message": e.user_message, "retryable": True},
                                  e.retry_after)
            else:
                await lifecycle.finish(job["_id"], token, "failed", last_error={"code": e.kind.value, "message": e.user_message})
                await emit_event(job["_id"], job["user_id"], "failed", e.user_message, {"code": e.kind.value}, level="error")
        finally:
            await ai.aclose()


def state_from(job: dict[str, Any], state: ResearchState) -> ResearchState:
    return state


def touch_health_file(path: str) -> None:
    """Liveness signal for container health checks: refreshed after each successful reconcile
    (which proves both MongoDB and the event loop are responsive)."""
    if not path:
        return
    with contextlib.suppress(OSError), open(path, "a", encoding="utf-8"):
        os.utime(path, None)


def health_check(path: str, max_age_seconds: float) -> bool:
    import time

    try:
        return time.time() - os.path.getmtime(path) <= max_age_seconds
    except OSError:
        return False


async def main() -> None:
    from app.core.logging import configure_logging
    from app.db.mongo import connect, ensure_indexes
    from app.db.redis import connect_redis

    s = get_settings()
    configure_logging(s.LOG_LEVEL, s.log_json)
    for w in s.config_warnings:
        log.warning("config_warning", message=w)
    await connect()
    await ensure_indexes()
    await connect_redis()
    await Worker().run()


if __name__ == "__main__":
    asyncio.run(main())
