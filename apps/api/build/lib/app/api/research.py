"""Research jobs, live events (SSE + polling), sources, evidence, reports and exports."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from pymongo import DESCENDING
from pymongo.errors import DuplicateKeyError

from app.auth.deps import Principal, current_principal, verified_principal
from app.core import ratelimit
from app.core.config import get_settings
from app.core.errors import AppError, ConfigurationRequired, Conflict, NotFound, ServiceUnavailable
from app.core.security import hash_token, new_token, utcnow
from app.db.mongo import Collections, col, new_id
from app.db.redis import get_redis, redis_ping
from app.jobs import queue
from app.jobs.lifecycle import ACTIVE_STATUSES, OPEN_STATUSES, RUNNABLE_IDLE, TERMINAL
from app.llm.config_store import ModelRef, get_api_key, get_user_api_key, load_config
from app.research.citations import paragraph_plain
from app.research.modes import MODES, budgets_for
from app.research.reports import bibliography, cited_numbers, render_markdown
from app.search.service import SearchService
from app.services.audit import audit
from app.services.exports import charts_csv
from app.services.limits import check_can_start

router = APIRouter(prefix="/api/v1/research", tags=["research"])
_DOMAIN_RE = re.compile(r"^(\*\.)?([a-z0-9-]+\.)+[a-z]{2,}$")


# ============================================================================================
# Schemas
# ============================================================================================

class BudgetOverrides(BaseModel):
    max_sources: int | None = Field(default=None, ge=1, le=300)
    max_search_calls: int | None = Field(default=None, ge=1, le=500)
    max_duration_seconds: int | None = Field(default=None, ge=60, le=6 * 3600)
    max_cost_usd: float | None = Field(default=None, gt=0, le=1000)


class ResearchOptions(BaseModel):
    include_domains: list[str] = Field(default_factory=list, max_length=20)
    exclude_domains: list[str] = Field(default_factory=list, max_length=50)
    date_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    language: str | None = Field(default=None, pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    source_preferences: list[Literal["official", "academic", "news", "industry", "documentation", "statistics"]] = Field(
        default_factory=list, max_length=6)
    review_plan: bool = False
    upload_ids: list[str] = Field(default_factory=list, max_length=100)
    model: ModelRef | None = None
    use_own_key: bool = False
    budget_overrides: BudgetOverrides | None = None

    @field_validator("include_domains", "exclude_domains")
    @classmethod
    def _domains(cls, v: list[str]) -> list[str]:
        out = []
        for d in v:
            d = d.strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0]
            if d and not _DOMAIN_RE.match(d):
                raise ValueError(f"invalid domain: {d[:60]}")
            if d:
                out.append(d)
        return out


class CreateResearch(BaseModel):
    question: str = Field(min_length=8, max_length=4000)
    mode: str = "standard"
    options: ResearchOptions = Field(default_factory=ResearchOptions)
    template_id: str | None = None

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        if v not in MODES:
            raise ValueError("unknown research mode")
        return v


class ApprovePlan(BaseModel):
    subquestions: list[dict[str, Any]] | None = Field(default=None, max_length=10)
    clarifications: list[str] = Field(default_factory=list, max_length=5)


class FollowUp(BaseModel):
    question: str = Field(min_length=8, max_length=4000)
    mode: str = "quick"


class RegenerateIn(BaseModel):
    instruction: str = Field(default="", max_length=1000)


class FeedbackIn(BaseModel):
    kind: Literal["citation_incorrect", "claim_incorrect", "missing_source", "quality", "other"]
    evidence_id: str | None = Field(default=None, max_length=20)
    section_id: str | None = Field(default=None, max_length=40)
    paragraph_id: str | None = Field(default=None, max_length=40)
    rating: int | None = Field(default=None, ge=1, le=5)
    note: str = Field(default="", max_length=2000)


class ExportIn(BaseModel):
    format: Literal["pdf", "docx"]
    version: int | None = None


# ============================================================================================
# Helpers
# ============================================================================================

def public_job(job: dict[str, Any]) -> dict[str, Any]:
    m = MODES.get(job.get("mode", "standard"))
    return {
        "id": job["_id"], "kind": job.get("kind", "research"), "question": job["question"], "title": job.get("title"),
        "mode": job["mode"], "mode_label": m.label if m else job["mode"], "status": job["status"], "stage": job.get("stage"),
        "options": {k: v for k, v in (job.get("options") or {}).items() if k not in ("use_own_key",)},
        "plan": job.get("plan") or ((job.get("checkpoint") or {}).get("state") or {}).get("plan"),
        "clarifications": job.get("clarifications", []),
        "assessment": ((job.get("checkpoint") or {}).get("state") or {}).get("assessment"),
        "usage": job.get("usage", {}), "budgets": job.get("budgets", {}), "model_config": job.get("model_config"),
        "fallbacks": job.get("fallbacks", []), "attempts": job.get("attempts", 0), "last_error": job.get("last_error"),
        "dead_lettered": bool(job.get("dead_lettered")), "cancel_requested": bool(job.get("cancel_requested")),
        "report_id": job.get("report_id"), "report_version": job.get("report_version"), "partial": bool(job.get("partial")),
        "is_demo": bool(job.get("is_demo")), "parent_job_id": (job.get("options") or {}).get("parent_job_id"),
        "event_seq": job.get("event_seq", 0), "next_attempt_at": job.get("next_attempt_at"),
        "created_at": job.get("created_at"), "started_at": job.get("started_at"), "finished_at": job.get("finished_at"),
        "deadline_at": job.get("deadline_at"), "updated_at": job.get("updated_at"),
        "resumable": job["status"] == "failed" and bool((job.get("last_error") or {}).get("resumable") or job.get("dead_lettered")),
    }


async def get_owned_job(job_id: str, principal: Principal) -> dict[str, Any]:
    job = await col(Collections.research_jobs).find_one({"_id": job_id, "user_id": principal.id})
    if not job:
        raise NotFound("Research not found.")
    return job


async def ensure_ai_ready(opts: ResearchOptions, user_id: str) -> None:
    s = get_settings()
    cfg = await load_config()
    if s.DEMO_MODE:
        return
    ref = opts.model or cfg.default
    if ref is None:
        raise ConfigurationRequired("No AI model is configured yet. An administrator must choose a provider and exact "
                                    "model in Admin → Providers.", code="ai_not_configured")
    if opts.model:
        if not s.ALLOW_USER_MODEL_SELECTION:
            raise AppError("Model selection is disabled by policy.", code="model_selection_disabled", status_code=403)
        if opts.model.key not in {m.key for m in cfg.allowed_user_models} and (not cfg.default or opts.model.key != cfg.default.key):
            raise AppError("That model is not on the approved list.", code="model_not_allowed", status_code=403)
    if opts.use_own_key:
        if not s.ALLOW_USER_API_KEYS:
            raise AppError("Using your own API key is disabled by policy.", code="byok_disabled", status_code=403)
        if not await get_user_api_key(user_id, ref.provider):
            raise AppError(f"You have not saved an API key for {ref.provider}.", code="byok_missing", status_code=400)
        return
    key, _ = await get_api_key(ref.provider)
    if not key:
        raise ConfigurationRequired(f"The {ref.provider} provider has no API key configured. An administrator must add "
                                    "one in Admin → Providers.", code="ai_key_missing")


async def _insert_and_enqueue(job: dict[str, Any]) -> dict[str, Any]:
    if not await redis_ping():
        # Without the queue we cannot promise timely execution; refuse rather than pretend.
        raise ServiceUnavailable("The research queue is temporarily unavailable. Please try again in a minute.",
                                 code="queue_unavailable")
    try:
        await col(Collections.research_jobs).insert_one(job)
    except DuplicateKeyError:
        existing = await col(Collections.research_jobs).find_one({"user_id": job["user_id"],
                                                                  "idempotency_key": job.get("idempotency_key")})
        if existing:
            return existing
        raise
    # Durably accepted at this point; if the push fails the reconciler dispatches it.
    await queue.enqueue(job["_id"])
    return job


def new_job_doc(user_id: str, question: str, mode: str, options: dict[str, Any], *, kind: str = "research",
                idempotency_key: str | None = None) -> dict[str, Any]:
    s = get_settings()
    now = utcnow()
    b = budgets_for(mode, options.get("budget_overrides"))
    return {
        "_id": new_id("job"), "user_id": user_id, "kind": kind, "question": question, "mode": mode, "options": options,
        "status": "queued", "stage": "queued", "cancel_requested": False, "attempts": 0, "max_attempts": s.MAX_JOB_ATTEMPTS,
        "next_attempt_at": None, "lease": None, "checkpoint": None, "checkpoint_version": 0, "event_seq": 0,
        "usage": {"tool_calls": 0, "search_calls": 0, "llm_calls": 0, "input_tokens": 0, "output_tokens": 0,
                  "extracted_pages": 0, "cost_usd_est": 0.0},
        "budgets": b.as_dict(), "is_demo": s.DEMO_MODE, "idempotency_key": idempotency_key, "fallbacks": [],
        "created_at": now, "updated_at": now, "run_count": 0,
    }


# ============================================================================================
# Routes
# ============================================================================================

@router.get("/modes")
async def modes() -> dict[str, Any]:
    return {"items": [m.public() for m in MODES.values()]}


@router.post("", status_code=202)
async def create_research(body: CreateResearch, request: Request, principal: Principal = Depends(verified_principal),
                          idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=100)) -> dict[str, Any]:
    s = get_settings()
    await ratelimit.enforce(ratelimit.RESEARCH_CREATE, f"user:{principal.id}")
    if idempotency_key:
        existing = await col(Collections.research_jobs).find_one({"user_id": principal.id, "idempotency_key": idempotency_key})
        if existing:
            return {"job": public_job(existing), "duplicate": True}
    opts = body.options
    if opts.upload_ids:
        if not s.FILE_UPLOADS_ENABLED:
            raise AppError("File uploads are disabled.", code="feature_disabled", status_code=404)
        if len(opts.upload_ids) > s.MAX_RESEARCH_UPLOADS_PER_JOB:
            raise AppError(f"At most {s.MAX_RESEARCH_UPLOADS_PER_JOB} documents per research job.", code="too_many_uploads",
                           status_code=422)
        owned = await col(Collections.uploads).count_documents({"_id": {"$in": opts.upload_ids}, "user_id": principal.id,
                                                                "status": "ready"})
        if owned != len(set(opts.upload_ids)):
            raise AppError("One or more documents are missing, still processing, or not yours.", code="invalid_uploads",
                           status_code=422)
    await check_can_start(principal.user, body.mode, len(opts.upload_ids))
    await ensure_ai_ready(opts, principal.id)
    if MODES[body.mode].web and not s.DEMO_MODE and not (await SearchService.create()).available():
        raise ConfigurationRequired("No web search provider is configured. An administrator must add a Firecrawl, Tavily "
                                    "or Brave API key (or use the uploaded-documents mode).", code="search_not_configured")
    options = opts.model_dump(mode="json", exclude_none=True)
    if body.template_id:
        options["template_id"] = body.template_id
    job = new_job_doc(principal.id, body.question.strip(), body.mode, options, idempotency_key=idempotency_key)
    job = await _insert_and_enqueue(job)
    await audit("research.created", actor_id=principal.id, target_id=job["_id"], ip=ratelimit.client_ip(request),
                metadata={"mode": body.mode})
    return {"job": public_job(job)}


@router.get("")
async def list_research(principal: Principal = Depends(current_principal), status: str | None = None,
                        q: str | None = Query(default=None, max_length=200), limit: int = Query(default=20, ge=1, le=100),
                        before: str | None = None) -> dict[str, Any]:
    query: dict[str, Any] = {"user_id": principal.id, "kind": "research"}
    if status == "active":
        query["status"] = {"$in": [*ACTIVE_STATUSES, *RUNNABLE_IDLE, "awaiting_approval"]}
    elif status:
        query["status"] = status
    if q:
        query["question"] = {"$regex": re.escape(q), "$options": "i"}
    if before:
        ref = await col(Collections.research_jobs).find_one({"_id": before, "user_id": principal.id}, {"created_at": 1})
        if ref:
            query["created_at"] = {"$lt": ref["created_at"]}
    items = await col(Collections.research_jobs).find(query, {"checkpoint": 0}).sort("created_at", DESCENDING).limit(limit + 1).to_list(None)
    has_more = len(items) > limit
    items = items[:limit]
    return {"items": [public_job(j) for j in items], "next_cursor": items[-1]["_id"] if has_more else None}


@router.get("/{job_id}")
async def get_research(job_id: str, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    job = await get_owned_job(job_id, principal)
    counts = {
        "sources": await col(Collections.research_sources).count_documents({"job_id": job_id}),
        "sources_extracted": await col(Collections.research_sources).count_documents({"job_id": job_id, "status": "extracted"}),
        "evidence_verified": await col(Collections.research_evidence).count_documents({"job_id": job_id, "verified": True}),
        "evidence_discarded": await col(Collections.research_evidence).count_documents({"job_id": job_id, "verified": False}),
    }
    return {"job": public_job(job), "counts": counts}


@router.get("/{job_id}/events")
async def poll_events(job_id: str, principal: Principal = Depends(current_principal), after: int = Query(default=0, ge=0),
                      limit: int = Query(default=200, ge=1, le=500)) -> dict[str, Any]:
    job = await get_owned_job(job_id, principal)
    events = await col(Collections.job_events).find({"job_id": job_id, "seq": {"$gt": after}}).sort("seq", 1).limit(limit).to_list(None)
    return {"events": [_event_out(e) for e in events], "job": public_job(job)}


def _event_out(e: dict[str, Any]) -> dict[str, Any]:
    return {"seq": e["seq"], "type": e["type"], "stage": e.get("stage"), "level": e.get("level", "info"),
            "message": e["message"], "data": e.get("data", {}), "at": e["created_at"].isoformat() + "Z"
            if e.get("created_at") and e["created_at"].tzinfo is None else str(e.get("created_at"))}


@router.get("/{job_id}/stream")
async def stream_events(job_id: str, request: Request, principal: Principal = Depends(current_principal),
                        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
                        after: int | None = Query(default=None, ge=0)) -> StreamingResponse:
    await get_owned_job(job_id, principal)
    start = after if after is not None else (int(last_event_id) if last_event_id and last_event_id.isdigit() else 0)

    async def gen() -> Any:
        last = start
        pubsub = None
        try:
            try:
                pubsub = get_redis().pubsub()
                await pubsub.subscribe(f"job:{job_id}:events")
            except Exception:  # noqa: BLE001 — fall back to polling
                pubsub = None
            yield "retry: 3000\n\n"
            idle_ticks = 0
            while True:
                if await request.is_disconnected():
                    break
                events = await col(Collections.job_events).find({"job_id": job_id, "seq": {"$gt": last}}).sort("seq", 1).limit(200).to_list(None)
                for e in events:
                    last = e["seq"]
                    yield f"id: {e['seq']}\nevent: progress\ndata: {json.dumps(_event_out(e), default=str)}\n\n"
                job = await col(Collections.research_jobs).find_one({"_id": job_id}, {"checkpoint": 0})
                if job is None:
                    yield "event: end\ndata: {\"reason\": \"deleted\"}\n\n"
                    break
                if not events:
                    idle_ticks += 1
                    if job["status"] in (*TERMINAL, "awaiting_approval", "waiting_for_retry") and idle_ticks > 1:
                        yield f"event: status\ndata: {json.dumps(public_job(job), default=str)}\n\n"
                        if job["status"] in TERMINAL:
                            yield "event: end\ndata: {\"reason\": \"finished\"}\n\n"
                            break
                    if idle_ticks % 8 == 0:
                        yield ": keep-alive\n\n"
                else:
                    idle_ticks = 0
                if pubsub is not None:
                    try:
                        await pubsub.get_message(ignore_subscribe_messages=True, timeout=2.0)
                    except Exception:  # noqa: BLE001
                        pubsub = None
                        await asyncio.sleep(1.5)
                else:
                    await asyncio.sleep(1.5)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe()
                    await pubsub.aclose()
                except Exception:  # noqa: BLE001,S110
                    pass

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
                                      "Connection": "keep-alive"})


@router.post("/{job_id}/cancel")
async def cancel(job_id: str, request: Request, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    job = await get_owned_job(job_id, principal)
    if job["status"] in TERMINAL:
        return {"job": public_job(job)}
    jobs = col(Collections.research_jobs)
    await jobs.update_one({"_id": job_id}, {"$set": {"cancel_requested": True, "cancel_requested_at": utcnow()}})
    # Not running (queued/waiting/awaiting approval): cancel immediately.
    await jobs.update_one({"_id": job_id, "status": {"$in": [*RUNNABLE_IDLE, "awaiting_approval"]},
                           "$or": [{"lease": None}, {"lease.expires_at": {"$lt": utcnow()}}]},
                          {"$set": {"status": "cancelled", "finished_at": utcnow(), "lease": None}})
    from app.research.context import emit_event

    await emit_event(job_id, principal.id, "status", "Cancellation requested", {"cancel_requested": True})
    await audit("research.cancelled", actor_id=principal.id, target_id=job_id, ip=ratelimit.client_ip(request))
    return {"job": public_job(await get_owned_job(job_id, principal))}


@router.post("/{job_id}/resume")
async def resume(job_id: str, principal: Principal = Depends(verified_principal)) -> dict[str, Any]:
    job = await get_owned_job(job_id, principal)
    if job["status"] not in ("failed", "waiting_for_retry"):
        raise Conflict("Only failed or waiting jobs can be resumed.")
    if job.get("kind", "research") == "research":
        await ensure_ai_ready(ResearchOptions.model_validate({k: v for k, v in (job.get("options") or {}).items()
                                                              if k in ResearchOptions.model_fields}), principal.id)
    if not await redis_ping():
        raise ServiceUnavailable("The research queue is temporarily unavailable.", code="queue_unavailable")
    res = await col(Collections.research_jobs).update_one(
        {"_id": job_id, "status": {"$in": ["failed", "waiting_for_retry"]}},
        {"$set": {"status": "queued", "attempts": 0, "next_attempt_at": None, "dead_lettered": False, "lease": None,
                  "deadline_at": None, "elapsed_seconds_before_pause": 0, "started_at": None, "updated_at": utcnow(),
                  "cancel_requested": False},
         "$push": {"resumes": utcnow()}})
    if res.modified_count:
        from app.research.context import emit_event

        await emit_event(job_id, principal.id, "status", "Resumed by user — continuing from the last checkpoint",
                         {"status": "queued"})
        await queue.enqueue(job_id)
    return {"job": public_job(await get_owned_job(job_id, principal))}


@router.post("/{job_id}/approve")
async def approve_plan(job_id: str, body: ApprovePlan, principal: Principal = Depends(verified_principal)) -> dict[str, Any]:
    job = await get_owned_job(job_id, principal)
    if job["status"] != "awaiting_approval":
        raise Conflict("This research is not waiting for plan approval.")
    state = (job.get("checkpoint") or {}).get("state")
    if not state:
        raise Conflict("No plan to approve.")
    plan = state["plan"]
    if body.subquestions is not None:
        subs = []
        for i, sq in enumerate(body.subquestions[:10]):
            q = str(sq.get("question", "")).strip()[:400]
            if len(q) < 5:
                continue
            queries = [str(x).strip()[:200] for x in (sq.get("queries") or []) if str(x).strip()][:3] or [q[:200]]
            subs.append({"id": f"Q{i + 1}", "question": q, "rationale": str(sq.get("rationale", ""))[:400],
                         "source_types": [], "queries": queries, "status": "open", "missing": ""})
        if not subs:
            raise AppError("The plan needs at least one sub-question.", code="invalid_plan", status_code=422)
        plan["subquestions"] = subs
        plan["edited_by_user"] = True
    state["plan"] = plan
    clar = [c.strip()[:500] for c in body.clarifications if c.strip()]
    state["clarifications"] = (state.get("clarifications") or []) + clar
    state["options"] = {**state.get("options", {}), "plan_approved": True}
    state["next"] = "search"
    await col(Collections.research_jobs).update_one(
        {"_id": job_id, "status": "awaiting_approval"},
        {"$set": {"status": "queued", "checkpoint.state": state, "checkpoint.next": "search", "plan": plan,
                  "options.plan_approved": True, "clarifications": state["clarifications"], "updated_at": utcnow()}})
    from app.research.context import emit_event

    await emit_event(job_id, principal.id, "plan", "Plan approved" + (" (edited)" if body.subquestions is not None else ""), plan)
    await queue.enqueue(job_id)
    return {"job": public_job(await get_owned_job(job_id, principal))}


@router.delete("/{job_id}")
async def delete_research(job_id: str, request: Request, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    job = await get_owned_job(job_id, principal)
    if job["status"] in OPEN_STATUSES and job["status"] not in ("awaiting_approval", "waiting_for_retry", "queued"):
        await col(Collections.research_jobs).update_one({"_id": job_id}, {"$set": {"cancel_requested": True}})
        raise Conflict("This research is still running. It has been asked to stop; delete it again once it has stopped.")
    from app.services.account import delete_job_data

    await delete_job_data(job_id, principal.id)
    await audit("research.deleted", actor_id=principal.id, target_id=job_id, ip=ratelimit.client_ip(request))
    return {"deleted": True}


# --- Sources & evidence -------------------------------------------------------------------------

def _source_out(s: dict[str, Any]) -> dict[str, Any]:
    return {k: s.get(k) for k in ("number", "url", "canonical_url", "final_url", "domain", "title", "snippet", "provider",
                                   "published_at", "published_at_basis", "author", "publisher", "status", "source_type",
                                   "source_type_basis", "source_type_reason", "relevance", "reliability_notes",
                                   "content_kind", "word_count", "injection_flags", "inaccessible_reason", "retrieved_at",
                                   "subquestion_ids", "extract_provider", "extract_warnings", "metadata", "rank_score",
                                   "is_demo")} | {"id": s["_id"]}


@router.get("/{job_id}/sources")
async def list_sources(job_id: str, principal: Principal = Depends(current_principal), status: str | None = None,
                       source_type: str | None = None) -> dict[str, Any]:
    await get_owned_job(job_id, principal)
    q: dict[str, Any] = {"job_id": job_id, "user_id": principal.id}
    if status:
        q["status"] = status
    if source_type:
        q["source_type"] = source_type
    items = await col(Collections.research_sources).find(q).sort("number", 1).to_list(None)
    ev_counts: dict[str, int] = {}
    for e in await col(Collections.research_evidence).find({"job_id": job_id, "verified": True}, {"source_id": 1}).to_list(None):
        ev_counts[e["source_id"]] = ev_counts.get(e["source_id"], 0) + 1
    return {"items": [_source_out(s) | {"verified_evidence": ev_counts.get(s["_id"], 0)} for s in items]}


@router.get("/{job_id}/sources/{source_id}")
async def source_detail(job_id: str, source_id: str, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    await get_owned_job(job_id, principal)
    s = await col(Collections.research_sources).find_one({"_id": source_id, "job_id": job_id, "user_id": principal.id})
    if not s:
        raise NotFound("Source not found.")
    evidence = await col(Collections.research_evidence).find({"job_id": job_id, "source_id": source_id}).sort("number", 1).to_list(None)
    content = await col(Collections.source_contents).find_one({"source_id": source_id})
    text = (content or {}).get("text", "")
    passages = []
    for e in evidence:
        idx = text.find(e["quote"]) if text else -1
        ctx_before = text[max(0, idx - 280): idx] if idx >= 0 else ""
        ctx_after = text[idx + len(e["quote"]): idx + len(e["quote"]) + 280] if idx >= 0 else ""
        passages.append({"evidence_id": e["id"], "claim": e["claim"], "quote": e["quote"], "verified": e["verified"],
                         "match_method": e.get("match_method"), "stance": e.get("stance"), "kind": e.get("kind"),
                         "subquestion_id": e.get("subquestion_id"), "context_before": ctx_before, "context_after": ctx_after})
    return {"source": _source_out(s), "passages": passages, "excerpt": text[:1500],
            "content_kind": (content or {}).get("content_kind"), "content_hash": (content or {}).get("content_hash")}


@router.get("/{job_id}/evidence")
async def list_evidence(job_id: str, principal: Principal = Depends(current_principal), include_discarded: bool = False) -> dict[str, Any]:
    await get_owned_job(job_id, principal)
    q: dict[str, Any] = {"job_id": job_id, "user_id": principal.id}
    if not include_discarded:
        q["verified"] = True
    items = await col(Collections.research_evidence).find(q).sort("number", 1).to_list(None)
    return {"items": [{k: e.get(k) for k in ("id", "kind", "source_id", "source_number", "subquestion_id", "claim", "quote",
                                              "stance", "claim_type", "verified", "match_method", "match_score",
                                              "source_type", "published", "domain", "metric", "entity", "value", "unit",
                                              "period")} for e in items]}


# --- Reports -------------------------------------------------------------------------------------

async def _report(job_id: str, principal: Principal, version: int | None) -> dict[str, Any]:
    q: dict[str, Any] = {"job_id": job_id, "user_id": principal.id, "version": {"$gte": 1}}
    if version:
        q["version"] = version
    rep = await col(Collections.research_reports).find_one(q, sort=[("version", DESCENDING)])
    if not rep:
        raise NotFound("No report yet.")
    return rep


def report_out(rep: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    out = {k: v for k, v in rep.items() if k not in ("_id", "draft", "user_id", "share_token_hash")}
    out["id"] = rep["_id"]
    out["bibliography"] = bibliography(sources, cited_numbers(rep))
    out["shared"] = bool(rep.get("share_token_hash"))
    return out


@router.get("/{job_id}/report")
async def get_report(job_id: str, principal: Principal = Depends(current_principal), version: int | None = None) -> dict[str, Any]:
    await get_owned_job(job_id, principal)
    rep = await _report(job_id, principal, version)
    sources = await col(Collections.research_sources).find({"job_id": job_id}).sort("number", 1).to_list(None)
    return {"report": report_out(rep, sources)}


@router.get("/{job_id}/report/versions")
async def report_versions(job_id: str, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    await get_owned_job(job_id, principal)
    items = await col(Collections.research_reports).find(
        {"job_id": job_id, "user_id": principal.id, "version": {"$gte": 1}},
        {"version": 1, "status": 1, "created_at": 1, "change_note": 1, "title": 1}).sort("version", DESCENDING).to_list(None)
    return {"items": [{"id": i["_id"], "version": i["version"], "status": i["status"], "created_at": i["created_at"],
                       "change_note": i.get("change_note"), "title": i.get("title")} for i in items]}


@router.get("/{job_id}/report/diff")
async def report_diff(job_id: str, a: int, b: int, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    import difflib

    await get_owned_job(job_id, principal)
    ra, rb = await _report(job_id, principal, a), await _report(job_id, principal, b)

    def sec_text(r: dict[str, Any]) -> dict[str, tuple[str, str]]:
        return {s["id"]: (s["title"], "\n\n".join(paragraph_plain(p) for p in s["paragraphs"])) for s in r.get("sections", [])}

    sa, sb = sec_text(ra), sec_text(rb)
    changes = []
    for sid in list(dict.fromkeys([*sa, *sb])):
        ta, tb = sa.get(sid, ("", "")), sb.get(sid, ("", ""))
        if ta != tb:
            diff = list(difflib.unified_diff(ta[1].split(". "), tb[1].split(". "), lineterm="", n=1))
            changes.append({"section_id": sid, "title_a": ta[0], "title_b": tb[0], "diff": diff[2:200]})
    return {"a": a, "b": b, "changes": changes}


@router.post("/{job_id}/report/sections/{section_id}/regenerate", status_code=202)
async def regenerate(job_id: str, section_id: str, body: RegenerateIn, principal: Principal = Depends(verified_principal)) -> dict[str, Any]:
    job = await get_owned_job(job_id, principal)
    rep = await _report(job_id, principal, None)
    if not any(s["id"] == section_id for s in rep.get("sections", [])):
        raise NotFound("Section not found.")
    await ensure_ai_ready(ResearchOptions(), principal.id)
    running = await col(Collections.research_jobs).count_documents({"user_id": principal.id, "kind": "regenerate_section",
                                                                    "options.parent_job_id": job_id,
                                                                    "status": {"$nin": list(TERMINAL)}})
    if running:
        raise Conflict("A section of this report is already being regenerated.")
    regen = new_job_doc(principal.id, job["question"], job["mode"],
                        {"parent_job_id": job_id, "report_id": rep["_id"], "section_id": section_id,
                         "instruction": body.instruction}, kind="regenerate_section")
    regen["budgets"] = {**regen["budgets"], "max_tool_calls": 12}
    regen = await _insert_and_enqueue(regen)
    return {"job": public_job(regen)}


@router.post("/{job_id}/followup", status_code=202)
async def followup(job_id: str, body: FollowUp, principal: Principal = Depends(verified_principal)) -> dict[str, Any]:
    parent = await get_owned_job(job_id, principal)
    if body.mode not in MODES:
        raise AppError("Unknown mode.", code="invalid_mode", status_code=422)
    await check_can_start(principal.user, body.mode, 0)
    opts = {k: v for k, v in (parent.get("options") or {}).items() if k in ("include_domains", "exclude_domains", "language",
                                                                            "date_from", "date_to", "model")}
    opts["parent_job_id"] = job_id
    await ensure_ai_ready(ResearchOptions.model_validate({k: v for k, v in opts.items() if k in ResearchOptions.model_fields}),
                          principal.id)
    question = body.question.strip()
    if body.mode == "counterarguments" and len(question) < 12:
        question = f"Find the strongest counterarguments to: {parent['question']}"
    job = await _insert_and_enqueue(new_job_doc(principal.id, question, body.mode, opts))
    return {"job": public_job(job)}


@router.post("/{job_id}/feedback", status_code=201)
async def feedback(job_id: str, body: FeedbackIn, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    await get_owned_job(job_id, principal)
    if body.evidence_id and not await col(Collections.research_evidence).find_one({"job_id": job_id, "id": body.evidence_id}):
        raise NotFound("Evidence not found.")
    doc = {"_id": new_id("fb"), "job_id": job_id, "user_id": principal.id, **body.model_dump(), "created_at": utcnow()}
    await col(Collections.feedback).insert_one(doc)
    if body.kind == "citation_incorrect" and body.evidence_id:
        await col(Collections.research_evidence).update_one({"job_id": job_id, "id": body.evidence_id},
                                                            {"$set": {"user_flagged": True}})
    return {"id": doc["_id"], "message": "Thanks — the flag is saved. Regenerate the section to rewrite it without that evidence."
            if body.kind == "citation_incorrect" else "Thanks for the feedback."}


@router.get("/{job_id}/graph")
async def evidence_graph(job_id: str, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    """Claims ↔ sources ↔ counterclaims. Every edge carries its justification (evidence ID)."""
    await get_owned_job(job_id, principal)
    rep = await _report(job_id, principal, None)
    evidence = {e["id"]: e for e in await col(Collections.research_evidence).find({"job_id": job_id, "verified": True}).to_list(None)}
    sources = {s["number"]: s for s in await col(Collections.research_sources).find({"job_id": job_id, "status": "extracted"}).to_list(None)}
    nodes: dict[str, dict[str, Any]] = {}
    edges = []
    for i, f in enumerate(rep.get("key_findings") or []):
        fid = f"F{i + 1}"
        nodes[fid] = {"id": fid, "type": "finding", "label": " ".join(seg["text"] for seg in f["segments"])[:220],
                      "strength": (f.get("strength") or {}).get("label")}
        for seg in f["segments"]:
            for eid in seg["evidence_ids"]:
                e = evidence.get(eid)
                if not e:
                    continue
                sid = f"S{e['source_number']}"
                src = sources.get(e["source_number"])
                if src and sid not in nodes:
                    nodes[sid] = {"id": sid, "type": "source", "label": src.get("title") or src["url"],
                                  "source_type": src.get("source_type"), "number": e["source_number"], "domain": src.get("domain")}
                edges.append({"from": sid, "to": fid, "type": "contradicts" if e.get("stance") == "contradicts" else "supports",
                              "evidence_id": eid, "quote": e["quote"][:300]})
    for j, c in enumerate(rep.get("contradictions") or []):
        cid = f"C{j + 1}"
        nodes[cid] = {"id": cid, "type": "conflict", "label": c["topic"], "explanation": c.get("explanation")}
        for eid in c["evidence_ids"]:
            e = evidence.get(eid)
            if not e:
                continue
            sid = f"S{e['source_number']}"
            src = sources.get(e["source_number"])
            if src and sid not in nodes:
                nodes[sid] = {"id": sid, "type": "source", "label": src.get("title") or src["url"],
                              "source_type": src.get("source_type"), "number": e["source_number"], "domain": src.get("domain")}
            edges.append({"from": sid, "to": cid, "type": "position", "evidence_id": eid, "quote": e["quote"][:300]})
    return {"nodes": list(nodes.values()), "edges": edges,
            "note": "Edges exist only where a verified evidence passage links a source to a finding or conflict."}


# --- Exports -------------------------------------------------------------------------------------

@router.get("/{job_id}/export.md")
async def export_markdown(job_id: str, principal: Principal = Depends(current_principal), version: int | None = None) -> PlainTextResponse:
    await get_owned_job(job_id, principal)
    rep = await _report(job_id, principal, version)
    sources = await col(Collections.research_sources).find({"job_id": job_id}).sort("number", 1).to_list(None)
    md = render_markdown(rep, sources)
    return PlainTextResponse(md, media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="report-{job_id}-v{rep["version"]}.md"'})


@router.get("/{job_id}/charts.csv")
async def export_csv(job_id: str, principal: Principal = Depends(current_principal), version: int | None = None) -> PlainTextResponse:
    await get_owned_job(job_id, principal)
    rep = await _report(job_id, principal, version)
    return PlainTextResponse(charts_csv(rep), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="chart-data-{job_id}-v{rep["version"]}.csv"'})


@router.post("/{job_id}/exports", status_code=202)
async def create_export(job_id: str, body: ExportIn, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    job = await get_owned_job(job_id, principal)
    rep = await _report(job_id, principal, body.version)
    ex = new_job_doc(principal.id, job["question"], job["mode"], {"report_id": rep["_id"], "format": body.format,
                                                                  "parent_job_id": job_id}, kind="export")
    ex = await _insert_and_enqueue(ex)
    return {"export_id": ex["_id"], "status": ex["status"]}


@router.get("/exports/{export_id}")
async def get_export(export_id: str, principal: Principal = Depends(current_principal), download: bool = False) -> Response:
    job = await col(Collections.research_jobs).find_one({"_id": export_id, "user_id": principal.id, "kind": "export"})
    if not job:
        raise NotFound("Export not found.")
    if not download:
        return Response(json.dumps({"id": export_id, "status": job["status"], "error": job.get("last_error")}, default=str),
                        media_type="application/json")
    ex = await col(Collections.exports).find_one({"_id": export_id, "user_id": principal.id})
    if not ex:
        raise NotFound("The export is not ready or has expired.")
    return Response(bytes(ex["data"]), media_type=ex["mime"],
                    headers={"Content-Disposition": f'attachment; filename="{ex["filename"]}"'})


# --- Sharing --------------------------------------------------------------------------------------

@router.post("/{job_id}/share")
async def share(job_id: str, request: Request, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    if not get_settings().PUBLIC_REPORT_SHARING_ENABLED:
        raise AppError("Public report sharing is disabled.", code="feature_disabled", status_code=404)
    await get_owned_job(job_id, principal)
    rep = await _report(job_id, principal, None)
    token = new_token(24)
    await col(Collections.research_reports).update_one({"_id": rep["_id"]}, {"$set": {"share_token_hash": hash_token(token),
                                                                                      "shared_at": utcnow()}})
    await audit("report.shared", actor_id=principal.id, target_id=rep["_id"], ip=ratelimit.client_ip(request))
    return {"url": get_settings().FRONTEND_URL.rstrip("/") + f"/shared/{token}", "version": rep["version"]}


@router.delete("/{job_id}/share")
async def unshare(job_id: str, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    await get_owned_job(job_id, principal)
    res = await col(Collections.research_reports).update_many({"job_id": job_id, "user_id": principal.id},
                                                              {"$unset": {"share_token_hash": "", "shared_at": ""}})
    return {"unshared": res.modified_count}


shared_router = APIRouter(prefix="/api/v1/shared", tags=["shared"])


@shared_router.get("/{token}")
async def shared_report(token: str) -> dict[str, Any]:
    if not get_settings().PUBLIC_REPORT_SHARING_ENABLED:
        raise NotFound()
    rep = await col(Collections.research_reports).find_one({"share_token_hash": hash_token(token)})
    if not rep:
        raise NotFound("This shared link is invalid or was revoked.")
    sources = await col(Collections.research_sources).find({"job_id": rep["job_id"]}).sort("number", 1).to_list(None)
    out = report_out(rep, sources)
    out.pop("methodology", None)
    return {"report": out}
