"""The research workflow as an explicit LangGraph state machine.

    validate → plan → [await_approval] → search → rank → extract → evidence → assess
                                           ↑                                   │
                                           └────── follow-up (bounded) ────────┘
    assess → synthesize → verify → charts → finalize

Every node is bounded (budgets, deadline, iteration cap) and the full state is
checkpointed to MongoDB after each node — and inside long nodes — so a crashed or
restarted worker resumes from the last checkpoint instead of starting over.
Deterministic code handles limits, deduplication, ranking, quote verification, citation
validation and chart data; the LLM is used for planning, reading, gap analysis and writing.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import utcnow
from app.db.mongo import Collections, col, new_id
from app.llm.base import ErrorKind, LLMError
from app.llm.service import AIService
from app.research import prompts
from app.research.charts import data_charts, process_charts
from app.research.citations import CitationResolver
from app.research.context import BudgetExceeded, JobContext
from app.research.evidence import (
    evidence_strength,
    heuristic_source_type,
    parse_date,
    verify_quote,
)
from app.research.modes import ModeSpec
from app.research.passages import number_in_text, select_passages
from app.research.schemas import (
    Candidate,
    ComparisonMatrixOut,
    EvidenceBatch,
    GapAnalysis,
    PendingQuery,
    Plan,
    QueryRecord,
    QuestionAssessment,
    Rejection,
    ReportDraft,
    ResearchPlan,
    ResearchState,
    SubQ,
    SupportCheck,
)
from app.search.base import SearchError, SearchQuery
from app.search.canonical import canonicalize_url, domain_matches, domain_of, registrable_domain
from app.search.service import SearchNotConfigured, SearchService
from app.security.injection import new_boundary, scan_for_injection

log = get_logger("pipeline")

FINAL_RESERVE_CALLS = 8
SYNTHESIS_TOKEN_RESERVE = 6000
MAX_PER_DOMAIN = 3
SOURCE_TEXT_CHARS = 20_000
MAX_LEDGER = 140


class PauseForApproval(Exception):
    pass


class StepRetryable(Exception):
    def __init__(self, reason: str, retry_after: float | None = None) -> None:
        self.reason = reason
        self.retry_after = retry_after
        super().__init__(reason)


class StepFailed(Exception):
    def __init__(self, code: str, message: str, *, resumable: bool = False) -> None:
        self.code = code
        self.message = message
        self.resumable = resumable
        super().__init__(message)


@dataclass
class Deps:
    ctx: JobContext
    ai: AIService
    search: SearchService
    mode: ModeSpec
    persist: Callable[[ResearchState], Awaitable[None]]


class GraphState(TypedDict):
    s: dict[str, Any]


# ============================================================================================
# Helpers
# ============================================================================================

async def load_evidence(job_id: str, *, verified_only: bool = True) -> list[dict[str, Any]]:
    q: dict[str, Any] = {"job_id": job_id}
    if verified_only:
        q["verified"] = True
    return await col(Collections.research_evidence).find(q).sort("number", 1).to_list(None)


async def load_sources(job_id: str) -> list[dict[str, Any]]:
    return await col(Collections.research_sources).find({"job_id": job_id}).sort("number", 1).to_list(None)


def _subq_dicts(state: ResearchState) -> list[dict[str, str]]:
    return [{"id": s.id, "question": s.question} for s in state.plan.subquestions]


def _time_fraction_left(deps: Deps) -> float:
    left = deps.ctx.seconds_left()
    total = deps.ctx.budgets.max_duration_seconds
    return 1.0 if left == float("inf") else max(0.0, left / max(total, 1))


async def _upload_candidates(state: ResearchState) -> list[Candidate]:
    ids = state.options.get("upload_ids") or []
    if not ids:
        return []
    ups = await col(Collections.uploads).find({"_id": {"$in": ids}, "user_id": state.user_id, "status": "ready"}).to_list(None)
    return [Candidate(url=f"upload://{u['_id']}", canonical_url=f"upload://{u['_id']}", title=u.get("filename", "Uploaded document"),
                      snippet=(u.get("preview") or "")[:300], provider="upload", upload_id=u["_id"], best_rank=0, hits=1,
                      subq_ids=[s.id for s in state.plan.subquestions], published_at=u.get("doc_published"),
                      author=u.get("doc_author"), metadata={"filename": u.get("filename")}) for u in ups]


async def _parent_candidates(state: ResearchState) -> list[Candidate]:
    pid = state.options.get("parent_job_id")
    if not pid:
        return []
    srcs = await col(Collections.research_sources).find({"job_id": pid, "user_id": state.user_id, "status": "extracted"}).to_list(None)
    return [Candidate(url=s["url"], canonical_url=s["canonical_url"], title=s.get("title") or "", snippet=s.get("snippet") or "",
                      provider="previous_report", published_at=s.get("published_at"), author=s.get("author"),
                      subq_ids=[q.id for q in state.plan.subquestions], best_rank=1,
                      metadata={"parent_source_id": s["_id"]}) for s in srcs[:40]]


def _merge_hit(state: ResearchState, cand: Candidate) -> bool:
    for c in state.candidates:
        if c.canonical_url == cand.canonical_url:
            c.hits += 1
            c.best_rank = min(c.best_rank, cand.best_rank)
            for sid in cand.subq_ids:
                if sid not in c.subq_ids:
                    c.subq_ids.append(sid)
            if not c.published_at and cand.published_at:
                c.published_at = cand.published_at
            if not c.content and cand.content:
                c.content, c.content_kind = cand.content, cand.content_kind
            return False
    state.candidates.append(cand)
    return True


# ============================================================================================
# Nodes
# ============================================================================================

async def node_validate(state: ResearchState, deps: Deps) -> ResearchState:
    ctx = deps.ctx
    await ctx.set_stage("understanding", status="planning", message="Understanding the question")
    q = state.question.strip()
    if len(q) < 8:
        raise StepFailed("question_too_short", "Please describe what you want to research in a little more detail.")
    if deps.mode.uses_uploads and not state.options.get("upload_ids"):
        raise StepFailed("uploads_required", "This mode analyses uploaded documents — attach at least one document.")
    assessment = await deps.ai.structured(
        "routine", prompts.assess_question(q, deps.mode.key, state.clarifications), QuestionAssessment,
        max_output_tokens=900, metadata={"demo": "assess", "question": q})
    if get_settings().CONTENT_SAFETY_ENABLED and assessment.safety == "refuse":
        raise StepFailed("content_policy", "This request can't be researched under the content policy. "
                         + (assessment.safety_reason or ""))
    state.assessment = assessment.model_dump()
    state.assumptions = assessment.assumptions_if_unclarified
    await ctx.emit("understanding", assessment.restated_question,
                   {"question_type": assessment.question_type, "ambiguities": assessment.ambiguities,
                    "clarifying_questions": assessment.clarifying_questions,
                    "assumptions": assessment.assumptions_if_unclarified})
    if not assessment.is_researchable:
        state.warnings.append("The model judged this question hard to research with public sources; results may be thin.")
    state.next = "plan"
    return state


async def node_plan(state: ResearchState, deps: Deps) -> ResearchState:
    ctx = deps.ctx
    await ctx.set_stage("planning", status="planning", message="Creating the research plan")
    b = ctx.budgets
    if not state.plan.subquestions:
        rp = await deps.ai.structured(
            "planning", prompts.plan(state.question, deps.mode.key, b.max_subquestions, state.assessment,
                                     state.clarifications, state.options),
            ResearchPlan, max_output_tokens=2200, metadata={"demo": "plan", "question": state.question,
                                                            "max_subq": b.max_subquestions, "mode": deps.mode.key})
        subqs = []
        seen_q: set[str] = set()
        for i, sq in enumerate(rp.subquestions[: b.max_subquestions]):
            queries = []
            for qq in sq.search_queries:
                k = " ".join(qq.lower().split())
                if k and k not in seen_q:
                    seen_q.add(k)
                    queries.append(qq.strip()[:200])
            subqs.append(SubQ(id=f"Q{i + 1}", question=sq.question.strip(), rationale=sq.rationale,
                              source_types=sq.source_types, queries=queries[:3] or [sq.question[:200]]))
        state.plan = Plan(objective=rp.objective, subquestions=subqs, entities=rp.entities[:8],
                          attributes=rp.comparison_attributes[:10], out_of_scope=rp.out_of_scope)
    await ctx.emit("plan", f"Plan with {len(state.plan.subquestions)} sub-questions", state.plan.model_dump())
    await col(Collections.research_jobs).update_one({"_id": ctx.job_id}, {"$set": {"plan": state.plan.model_dump()}})
    needs_review = bool(state.options.get("review_plan")) and not state.options.get("plan_approved")
    state.next = "search"
    if needs_review:
        await deps.persist(state)
        raise PauseForApproval()
    return state


async def node_search(state: ResearchState, deps: Deps) -> ResearchState:
    ctx = deps.ctx
    ctx.final_reserve_calls = FINAL_RESERVE_CALLS
    await ctx.set_stage("searching", status="searching",
                        message="Searching the web" if deps.mode.web else "Preparing your documents")
    opts = state.options
    # Seed once: uploads, parent-report sources and the plan's queries.
    if state.iteration == 0 and not state.queries and not state.pending_queries:
        for c in await _upload_candidates(state) + await _parent_candidates(state):
            _merge_hit(state, c)
        if deps.mode.web:
            for sq in state.plan.subquestions:
                for qq in sq.queries:
                    state.pending_queries.append(PendingQuery(subq_id=sq.id, query=qq, kind="web"))
                if deps.mode.scholarly:
                    state.pending_queries.append(PendingQuery(subq_id=sq.id, query=sq.queries[0], kind="scholarly"))
        await deps.persist(state)

    if state.pending_queries and not deps.search.available() and deps.mode.web:
        if not state.candidates:
            raise StepFailed("search_not_configured",
                             "No search provider is configured. An administrator must add a search API key "
                             "(Firecrawl, Tavily or Brave) — or enable DEMO_MODE for a labelled demo.", resumable=True)
        state.warnings.append("No search provider configured; used only uploaded/previous sources.")
        state.pending_queries = []

    transient_failures = 0
    successes = 0
    while state.pending_queries:
        await ctx.check_alive()
        if _time_fraction_left(deps) < 0.35:
            state.stop_reason = "time budget: stopped searching to leave time for writing"
            await ctx.emit("warning", "Stopping search early to stay within the time budget.", level="warning")
            state.pending_queries = []
            break
        pq = state.pending_queries[0]
        sq = SearchQuery(q=pq.query, max_results=ctx.budgets.results_per_query or 6,
                         include_domains=opts.get("include_domains") or [], exclude_domains=opts.get("exclude_domains") or [],
                         date_from=opts.get("date_from"), date_to=opts.get("date_to"), language=opts.get("language"),
                         scholarly=pq.kind == "scholarly")
        rec = QueryRecord(subq_id=pq.subq_id, query=pq.query, kind=pq.kind, iteration=pq.iteration)
        try:
            if pq.kind == "scholarly":
                hits, provider, cached = await deps.search.scholarly(sq), "openalex", False
            else:
                hits, provider, cached = await deps.search.search(sq)
        except BudgetExceeded:
            state.stop_reason = "search budget reached"
            await ctx.emit("warning", "Search budget reached; continuing with the sources found so far.", level="warning")
            state.pending_queries = []
            break
        except SearchNotConfigured:
            state.pending_queries.pop(0)
            continue
        except SearchError as e:
            rec.error = e.kind.value
            state.queries.append(rec)
            state.pending_queries.pop(0)
            await ctx.emit("query_failed", f"Search failed for “{pq.query}” ({e.kind.value.replace('_', ' ')})",
                           {"query": pq.query, "provider": e.provider, "error": e.kind.value}, level="warning")
            if e.retryable:
                transient_failures += 1
                if transient_failures >= 3 and successes == 0 and not state.candidates:
                    # Put it back and let the job retry later with its checkpoint intact.
                    state.pending_queries.insert(0, pq)
                    await deps.persist(state)
                    raise StepRetryable("search providers temporarily unavailable", e.retry_after) from e
            elif e.kind in (ErrorKind.AUTH, ErrorKind.QUOTA, ErrorKind.BILLING) and not deps.search.order[1:] \
                    and not state.candidates and pq.kind == "web":
                raise StepFailed("search_provider_error",
                                 f"The search provider rejected our requests ({e.kind.value.replace('_', ' ')}). "
                                 "An administrator needs to check the search API key or quota.", resumable=True) from e
            await deps.persist(state)
            continue
        successes += 1
        rec.provider, rec.results, rec.from_cache = provider, len(hits), cached
        new = 0
        for h in hits:
            cand = Candidate(url=h.url, canonical_url=canonicalize_url(h.url), title=h.title[:300], snippet=h.snippet[:500],
                             provider=h.provider, published_at=h.published_at, author=h.author, subq_ids=[pq.subq_id],
                             best_rank=h.rank, content=(h.content or None) and h.content[:8000],
                             content_kind=h.content_kind, metadata=h.metadata)
            new += int(_merge_hit(state, cand))
        state.queries.append(rec)
        state.pending_queries.pop(0)
        await ctx.emit("query", f"Searched “{pq.query}”", {"query": pq.query, "provider": provider, "results": len(hits),
                                                          "new_results": new, "cached": cached, "subquestion_id": pq.subq_id,
                                                          "kind": pq.kind})
        await deps.persist(state)
    state.next = "rank"
    return state


async def node_rank(state: ResearchState, deps: Deps) -> ResearchState:
    ctx = deps.ctx
    opts = state.options
    remaining = ctx.budgets.max_sources - len(state.source_ids)
    existing_domains: dict[str, int] = defaultdict(int)
    for s in await load_sources(ctx.job_id):
        existing_domains[registrable_domain(s.get("domain") or "")] += 1
    date_from = parse_date(opts.get("date_from"))
    date_to = parse_date(opts.get("date_to"))

    def reject(c: Candidate, reason: str) -> None:
        c.status = "rejected"
        state.rejected.append(Rejection(url=c.url, title=c.title, reason=reason))

    pool = []
    for c in state.candidates:
        if c.status != "new":
            continue
        if c.provider not in ("upload",) and opts.get("exclude_domains") and domain_matches(c.url, opts["exclude_domains"]):
            reject(c, "excluded domain")
            continue
        if c.provider not in ("upload", "previous_report") and opts.get("include_domains") and not domain_matches(c.url, opts["include_domains"]):
            reject(c, "outside requested domains")
            continue
        d = parse_date(c.published_at)
        if d and ((date_from and d < date_from) or (date_to and d > date_to)):
            reject(c, f"published {d.isoformat()}, outside the requested date range")
            continue
        hint = heuristic_source_type(c.url)
        score = 1.0 / (1 + c.best_rank) + 0.35 * (c.hits - 1) + 0.15 * len(c.subq_ids)
        score += 0.4 if hint == "primary" else (-0.25 if hint == "commentary" else 0)
        score += 0.5 if c.provider in ("upload", "previous_report") else 0
        if deps.mode.scholarly and c.provider == "openalex":
            score += 0.3
        if d:
            age_years = (utcnow().date() - d).days / 365
            score += 0.2 if age_years < 1 else (0.1 if age_years < 3 else 0)
        c.score = round(score, 4)
        pool.append(c)

    # Round-robin across sub-questions for coverage, respecting a per-domain cap for diversity.
    by_subq: dict[str, list[Candidate]] = defaultdict(list)
    for c in sorted(pool, key=lambda c: -c.score):
        by_subq[c.subq_ids[0] if c.subq_ids else "Q1"].append(c)
    selected: list[Candidate] = []
    domain_counts = dict(existing_domains)
    while remaining > 0 and any(by_subq.values()):
        progressed = False
        for key in sorted(by_subq):
            lst = by_subq[key]
            while lst:
                c = lst.pop(0)
                if c.status != "new":
                    continue
                dom = registrable_domain(domain_of(c.url)) if c.provider != "upload" else f"upload:{c.upload_id}"
                if domain_counts.get(dom, 0) >= MAX_PER_DOMAIN:
                    reject(c, "too many sources from the same domain (diversity cap)")
                    continue
                domain_counts[dom] = domain_counts.get(dom, 0) + 1
                c.status = "selected"
                selected.append(c)
                remaining -= 1
                progressed = True
                break
            if remaining <= 0:
                break
        if not progressed:
            break
    for c in pool:
        if c.status == "new" and remaining <= 0:
            reject(c, "source limit reached (lower-ranked)")

    sources = col(Collections.research_sources)
    for c in selected:
        existing = await sources.find_one({"job_id": ctx.job_id, "canonical_url": c.canonical_url}, {"_id": 1})
        if existing:
            continue
        num = state.next_source_number
        state.next_source_number += 1
        sid = new_id("src")
        await sources.insert_one({
            "_id": sid, "job_id": ctx.job_id, "user_id": ctx.user_id, "number": num, "url": c.url,
            "canonical_url": c.canonical_url, "domain": domain_of(c.url) if c.provider != "upload" else "uploaded document",
            "title": c.title, "snippet": c.snippet, "provider": c.provider, "published_at": c.published_at,
            "author": c.author, "subquestion_ids": c.subq_ids, "rank_score": c.score, "status": "candidate",
            "upload_id": c.upload_id, "metadata": c.metadata, "content_kind": c.content_kind,
            "candidate_content": c.content, "created_at": utcnow(), "is_demo": ctx.is_demo,
        })
        state.source_ids.append(sid)
        await ctx.emit("source_found", c.title or c.url, {"source_id": sid, "number": num, "url": c.url,
                                                         "domain": domain_of(c.url), "provider": c.provider,
                                                         "subquestion_ids": c.subq_ids})
    rejected_now = [r for r in state.rejected[-50:]]
    if rejected_now:
        reasons: dict[str, int] = defaultdict(int)
        for r in rejected_now:
            reasons[r.reason] += 1
        await ctx.emit("sources_rejected", f"Set aside {len(rejected_now)} candidate(s)",
                       {"reasons": dict(reasons), "examples": [r.model_dump() for r in rejected_now[:8]]})
    state.next = "extract"
    return state


async def _content_for(src: dict[str, Any], deps: Deps) -> dict[str, Any]:
    """Return {'text','title','author','published_at','provider','final_url','warnings','content_kind'}."""
    if src.get("upload_id"):
        chunks = await col(Collections.upload_chunks).find({"upload_id": src["upload_id"]}).sort("index", 1).to_list(None)
        text = "\n\n".join(c["text"] for c in chunks)
        return {"text": text, "provider": "upload", "content_kind": "full_text", "warnings": []}
    parent_id = (src.get("metadata") or {}).get("parent_source_id")
    if parent_id:
        pc = await col(Collections.source_contents).find_one({"source_id": parent_id})
        if pc:
            return {"text": pc["text"], "provider": "previous_report", "content_kind": pc.get("content_kind", "full_text"),
                    "warnings": []}
    try:
        page = await deps.search.extract(src["url"])
        return {"text": page.text, "title": page.title, "author": page.author, "published_at": page.published_at,
                "provider": page.provider, "final_url": page.final_url, "warnings": page.warnings,
                "content_kind": "full_text", "site_name": page.site_name}
    except SearchError:
        if src.get("candidate_content"):
            # e.g. OpenAlex abstracts — clearly labelled as abstract-only.
            return {"text": src["candidate_content"], "provider": src.get("provider"),
                    "content_kind": src.get("content_kind") or "abstract", "warnings": ["full text unavailable; abstract only"]}
        raise


async def node_extract(state: ResearchState, deps: Deps) -> ResearchState:
    ctx = deps.ctx
    await ctx.set_stage("reading", status="extracting", message="Reading sources")
    sources = col(Collections.research_sources)
    pending = await sources.find({"job_id": ctx.job_id, "status": "candidate"}).sort("number", 1).to_list(None)
    for src in pending:
        await ctx.check_alive()
        if _time_fraction_left(deps) < 0.3:
            state.stop_reason = "time budget: stopped reading to leave time for writing"
            await ctx.emit("warning", "Stopping source reading early to stay within the time budget.", level="warning")
            break
        try:
            content = await _content_for(src, deps)
        except BudgetExceeded:
            state.stop_reason = "tool-call budget reached while reading sources"
            await ctx.emit("warning", "Tool-call budget reached; continuing with sources already read.", level="warning")
            break
        except SearchError as e:
            await sources.update_one({"_id": src["_id"]}, {"$set": {"status": "inaccessible",
                                                                     "inaccessible_reason": e.detail or e.kind.value,
                                                                     "retrieved_at": utcnow()}})
            await ctx.emit("source_rejected", f"Could not access [{src['number']}] {src.get('title') or src['url']}",
                           {"source_id": src["_id"], "number": src["number"], "reason": e.detail or e.kind.value})
            continue
        text = content["text"]
        flags = scan_for_injection(text)
        await col(Collections.source_contents).update_one(
            {"source_id": src["_id"]},
            {"$set": {"source_id": src["_id"], "job_id": ctx.job_id, "user_id": ctx.user_id, "text": text[:200_000],
                      "content_kind": content.get("content_kind", "full_text"),
                      "content_hash": hashlib.sha256(text.encode()).hexdigest(), "updated_at": utcnow()},
             "$setOnInsert": {"_id": new_id("sct")}}, upsert=True)
        upd = {"status": "extracted", "retrieved_at": utcnow(), "extract_provider": content.get("provider"),
               "content_kind": content.get("content_kind", "full_text"), "word_count": len(text.split()),
               "injection_flags": flags, "extract_warnings": content.get("warnings", []),
               "final_url": content.get("final_url")}
        if content.get("title") and (not src.get("title") or src.get("provider") in ("upload",)):
            upd["title"] = content["title"][:300]
        if content.get("author") and not src.get("author"):
            upd["author"] = content["author"][:200]
        if content.get("published_at") and not src.get("published_at"):
            upd["published_at"] = str(content["published_at"])[:40]
        if content.get("site_name"):
            upd["publisher"] = content["site_name"][:200]
        await sources.update_one({"_id": src["_id"]}, {"$set": upd})
        state.extracted_ids.append(src["_id"])
        await ctx.add_usage(extracted_pages=1)
        await ctx.emit("source_extracted", f"Read [{src['number']}] {upd.get('title') or src.get('title') or src['url']}",
                       {"source_id": src["_id"], "number": src["number"], "words": upd["word_count"],
                        "content_kind": upd["content_kind"], "injection_suspected": bool(flags)})
        if flags:
            await ctx.emit("warning", f"Source [{src['number']}] contains instruction-like text; treated strictly as data.",
                           {"source_id": src["_id"], "examples": flags[:2]}, level="warning")
        await deps.persist(state)
    state.next = "evidence"
    return state


async def node_evidence(state: ResearchState, deps: Deps) -> ResearchState:
    ctx = deps.ctx
    await ctx.set_stage("comparing", status="verifying", message="Extracting and verifying evidence")
    sources_col = col(Collections.research_sources)
    todo = await sources_col.find({"job_id": ctx.job_id, "status": "extracted",
                                   "_id": {"$nin": state.processed_evidence_source_ids}}).sort("number", 1).to_list(None)
    sel = deps.ai.select("extraction")
    per_source_chars = min(SOURCE_TEXT_CHARS, max(4000, int(sel.caps.context_window * 3 * 0.25)))
    batch_chars = min(48_000, int(sel.caps.context_window * 3 * 0.5))
    queries = [s.question for s in state.plan.subquestions] + [q for s in state.plan.subquestions for q in s.queries]

    batches: list[list[tuple[dict[str, Any], str, str]]] = [[]]
    size = 0
    for src in todo:
        content = await col(Collections.source_contents).find_one({"source_id": src["_id"]})
        if not content:
            continue
        full = content["text"]
        excerpt = select_passages(full, queries + [state.question], per_source_chars)
        if batches[-1] and (size + len(excerpt) > batch_chars or len(batches[-1]) >= 3):
            batches.append([])
            size = 0
        batches[-1].append((src, excerpt, full))
        size += len(excerpt)
    batches = [b for b in batches if b]
    valid_subq = {s.id for s in state.plan.subquestions}
    ev_col = col(Collections.research_evidence)

    for batch in batches:
        await ctx.check_alive()
        if await ctx.remaining_output_tokens() < SYNTHESIS_TOKEN_RESERVE + 1500:
            state.stop_reason = "token budget: reserved remaining tokens for writing the report"
            await ctx.emit("warning", "Token budget is getting low; moving on to writing with the evidence gathered.",
                           level="warning")
            break
        if _time_fraction_left(deps) < 0.25:
            state.stop_reason = "time budget: stopped evidence extraction early"
            break
        boundary = new_boundary()
        payload = [{"label": f"S{src['number']}", "title": src.get("title"), "url": src["url"], "text": excerpt}
                   for src, excerpt, _ in batch]
        try:
            out = await deps.ai.structured(
                "extraction", prompts.extract_evidence(state.question, _subq_dicts(state), payload, boundary), EvidenceBatch,
                max_output_tokens=3500,
                metadata={"demo": "evidence", "sources": payload, "subquestions": _subq_dicts(state)})
        except LLMError as e:
            if e.kind == ErrorKind.BAD_OUTPUT:
                for src, _, _ in batch:
                    state.processed_evidence_source_ids.append(src["_id"])
                await ctx.emit("warning", "Could not parse the model's reading of a source batch; skipped it.",
                               {"sources": [s["number"] for s, _, _ in batch]}, level="warning")
                continue
            if e.kind == ErrorKind.BUDGET:
                state.stop_reason = "budget reached during evidence extraction"
                break
            raise
        except BudgetExceeded:
            state.stop_reason = "tool-call budget reached during evidence extraction"
            break
        by_label = {a.source_label.strip().upper(): a for a in out.sources}
        for src, _excerpt, full in batch:
            a = by_label.get(f"S{src['number']}")
            state.processed_evidence_source_ids.append(src["_id"])
            if a is None:
                continue
            hint = heuristic_source_type(src["url"])
            stype = a.source_type
            type_basis = "model"
            if hint == "commentary" and stype == "primary":
                stype, type_basis = "commentary", "domain heuristic overrode model"
            elif stype == "unknown" and hint:
                stype, type_basis = hint, "domain heuristic"
            upd: dict[str, Any] = {"source_type": stype, "source_type_basis": type_basis,
                                   "source_type_reason": a.source_type_reason, "relevance": a.relevance,
                                   "reliability_notes": a.reliability_notes}
            if a.publisher and not src.get("publisher"):
                upd["publisher"] = a.publisher
            if a.author and not src.get("author") and a.author in full:
                upd["author"] = a.author
            if a.published_date and not src.get("published_at") and (a.published_date in full or (parse_date(a.published_date) and str(parse_date(a.published_date).year) in full[:5000])):  # type: ignore[union-attr]
                upd["published_at"] = a.published_date
                upd["published_at_basis"] = "stated in source text (model-extracted)"
            if a.contains_instructions_to_ai:
                upd["injection_flags"] = list({*(src.get("injection_flags") or []), "model flagged instruction-like text"})
            await sources_col.update_one({"_id": src["_id"]}, {"$set": upd})
            published = upd.get("published_at") or src.get("published_at")
            verified_n = 0
            discarded = 0
            for cl in a.claims[:10]:
                m = verify_quote(cl.quote, full)
                sq_id = cl.subquestion_id.strip().upper() if cl.subquestion_id.strip().upper() in valid_subq else (
                    (src.get("subquestion_ids") or ["Q1"])[0])
                n = state.next_evidence_number
                state.next_evidence_number += 1
                await ev_col.insert_one({
                    "_id": new_id("evi"), "id": f"E{n}", "number": n, "job_id": ctx.job_id, "user_id": ctx.user_id,
                    "kind": "claim", "source_id": src["_id"], "source_number": src["number"], "subquestion_id": sq_id,
                    "claim": cl.claim, "quote": cl.quote, "stance": cl.stance, "claim_type": cl.claim_type,
                    "verified": m.verified, "match_method": m.method, "match_score": m.score,
                    "source_type": stype, "published": published, "domain": src.get("domain") or "",
                    "created_at": utcnow(),
                })
                verified_n += int(m.verified)
                discarded += int(not m.verified)
            for dp in a.datapoints[:12]:
                m = verify_quote(dp.quote, full)
                ok = m.verified and number_in_text(dp.value, dp.quote)
                n = state.next_evidence_number
                state.next_evidence_number += 1
                await ev_col.insert_one({
                    "_id": new_id("evi"), "id": f"E{n}", "number": n, "job_id": ctx.job_id, "user_id": ctx.user_id,
                    "kind": "datapoint", "source_id": src["_id"], "source_number": src["number"],
                    "subquestion_id": (src.get("subquestion_ids") or ["Q1"])[0],
                    "claim": f"{dp.metric} — {dp.entity}: {dp.value:g} {dp.unit}" + (f" ({dp.period})" if dp.period else ""),
                    "quote": dp.quote, "metric": dp.metric, "entity": dp.entity, "value": dp.value, "unit": dp.unit,
                    "period": dp.period, "stance": "context", "claim_type": "statistic", "verified": ok,
                    "match_method": m.method if ok else ("number_not_in_quote" if m.verified else m.method),
                    "match_score": m.score, "source_type": stype, "published": published,
                    "domain": src.get("domain") or "", "created_at": utcnow(),
                })
                verified_n += int(ok)
                discarded += int(not ok)
            await ctx.emit("evidence", f"[{src['number']}] {verified_n} verified item(s)"
                           + (f", {discarded} discarded (quote not found in source)" if discarded else ""),
                           {"source_id": src["_id"], "number": src["number"], "verified": verified_n, "discarded": discarded,
                            "source_type": stype, "relevance": a.relevance})
        await deps.persist(state)
    state.next = "assess"
    return state


async def node_assess(state: ResearchState, deps: Deps) -> ResearchState:
    ctx = deps.ctx
    await ctx.set_stage("gaps", status="verifying", message="Identifying gaps and contradictions")
    evidence = [e for e in await load_evidence(ctx.job_id) if e["kind"] == "claim"]
    b = ctx.budgets
    usage = await ctx.usage()
    search_left = b.max_search_calls - int(usage.get("search_calls", 0))
    can_follow = (deps.mode.web and state.iteration + 1 < b.max_iterations and search_left > 0
                  and _time_fraction_left(deps) > 0.45 and not state.stop_reason
                  and await ctx.remaining_output_tokens() > SYNTHESIS_TOKEN_RESERVE + 4000)
    executed = {" ".join(q.query.lower().split()) for q in state.queries}

    if not evidence:
        await ctx.emit("gap", "No verified evidence yet.", {"subquestions": [s.id for s in state.plan.subquestions]})
        if can_follow:
            state.iteration += 1
            for s in state.plan.subquestions:
                q = s.question[:200]
                if " ".join(q.lower().split()) not in executed:
                    state.pending_queries.append(PendingQuery(subq_id=s.id, query=q, iteration=state.iteration))
            state.next = "search" if state.pending_queries else "synthesize"
        else:
            state.next = "synthesize"
        return state

    ledger = [{"id": e["id"], "subquestion_id": e["subquestion_id"], "claim": e["claim"], "source_type": e["source_type"],
               "published": e.get("published"), "domain": e["domain"], "stance": e.get("stance")} for e in evidence[:200]]
    try:
        gaps = await deps.ai.structured(
            "verification", prompts.gap_analysis(state.question, [s.model_dump() for s in state.plan.subquestions], ledger,
                                                 max(0, b.max_iterations - state.iteration - 1)),
            GapAnalysis, max_output_tokens=1800,
            metadata={"demo": "gaps", "subquestions": _subq_dicts(state), "evidence": ledger, "can_follow": can_follow})
    except (LLMError, BudgetExceeded) as e:
        if isinstance(e, LLMError) and e.kind not in (ErrorKind.BAD_OUTPUT, ErrorKind.BUDGET):
            raise
        state.warnings.append("Gap analysis was skipped (budget or unparseable output).")
        state.next = "synthesize"
        return state

    ids = {e["id"] for e in evidence}
    state.contradictions = [
        {"topic": c.topic, "evidence_ids": [i for i in c.evidence_ids if i in ids], "explanation": c.explanation}
        for c in gaps.contradictions if len([i for i in c.evidence_ids if i in ids]) >= 2
    ]
    state.unknowns = [u.model_dump() for u in gaps.unknowns]
    status_by = {s.subquestion_id.upper(): s for s in gaps.statuses}
    for sq in state.plan.subquestions:
        st = status_by.get(sq.id)
        n_dom = len({registrable_domain(e["domain"]) for e in evidence if e["subquestion_id"] == sq.id})
        sq.status = "covered" if (st.sufficient if st else n_dom >= 2) else "insufficient"
        sq.missing = st.missing if st else ""
    for c in state.contradictions:
        await ctx.emit("contradiction", c["topic"], c)
    for sq in state.plan.subquestions:
        if sq.status == "insufficient":
            await ctx.emit("gap", f"{sq.id}: {sq.missing or 'evidence insufficient'}", {"subquestion_id": sq.id})

    followups = []
    per_subq: dict[str, int] = defaultdict(int)
    valid = {s.id for s in state.plan.subquestions}
    for f in gaps.followup_queries:
        k = " ".join(f.query.lower().split())
        sid = f.subquestion_id.upper()
        if sid not in valid or k in executed or per_subq[sid] >= 2 or not k:
            continue
        per_subq[sid] += 1
        executed.add(k)
        followups.append(PendingQuery(subq_id=sid, query=f.query[:200], iteration=state.iteration + 1))
    followups = followups[: max(0, min(search_left, 8))]
    if followups and can_follow:
        state.iteration += 1
        state.pending_queries = followups
        await ctx.emit("followup", f"Follow-up round {state.iteration}: {len(followups)} targeted searches",
                       {"queries": [f.model_dump() for f in followups]})
        state.next = "search"
    else:
        state.next = "synthesize"
    return state


def _ledger(evidence: list[dict[str, Any]], max_items: int) -> list[dict[str, Any]]:
    """Choose evidence for the writer: diverse across sources and sub-questions."""
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in evidence:
        by_source[e["source_id"]].append(e)
    out: list[dict[str, Any]] = []
    while len(out) < max_items and any(by_source.values()):
        for sid in list(by_source):
            if by_source[sid]:
                e = by_source[sid].pop(0)
                out.append({**e, "quote": e["quote"][:300]})
                if len(out) >= max_items:
                    break
    return sorted(out, key=lambda e: e["number"])


async def node_synthesize(state: ResearchState, deps: Deps) -> ResearchState:
    ctx = deps.ctx
    ctx.final_reserve_calls = 0
    await ctx.set_stage("writing", status="synthesizing", message="Writing the report")
    evidence = await load_evidence(ctx.job_id)
    sel = deps.ai.select("synthesis")
    max_items = min(MAX_LEDGER, max(20, int(sel.caps.context_window * 3 * 0.5 / 600)))
    ledger = _ledger(evidence, max_items)
    by_id = {e["id"]: e for e in evidence}
    report_id = state.report_id or new_id("rep")
    resolver = CitationResolver(by_id)
    if not ledger:
        draft_doc = _insufficient_evidence_report(state)
    else:
        boundary = new_boundary()
        remaining = await ctx.remaining_output_tokens()
        draft = await deps.ai.structured(
            "synthesis", prompts.synthesize(state.question, deps.mode.key, state.plan.model_dump(), ledger,
                                            state.contradictions, state.unknowns, boundary),
            ReportDraft, max_output_tokens=max(1500, min(9000, remaining)), temperature=0.3,
            metadata={"demo": "synthesis", "question": state.question, "evidence": ledger,
                      "subquestions": _subq_dicts(state), "contradictions": state.contradictions,
                      "unknowns": state.unknowns})
        draft_doc = {
            "title": draft.title,
            "executive_summary": [resolver.paragraph(p) for p in draft.executive_summary],
            "key_findings": [{**resolver.paragraph(f.text), "strength": None} for f in draft.key_findings],
            "sections": [{"id": new_id("sec"), "title": s.title, "paragraphs": [resolver.paragraph(p) for p in s.paragraphs]}
                         for s in draft.sections],
            "conflicts": [{"topic": c.topic, **resolver.paragraph(c.summary)} for c in draft.conflicts],
            "limitations": draft.limitations,
            "unknowns": [u.model_dump() for u in draft.unknowns] or state.unknowns,
            "conclusions": [resolver.paragraph(p) for p in draft.conclusions],
            "recommendations": [resolver.paragraph(p, require_citations=False) for p in draft.recommendations],
            "insufficient_evidence": False,
        }
    # Comparison matrix (only with ≥2 entities, attributes and evidence).
    tables = []
    if deps.mode.comparison_matrix and len(state.plan.entities) >= 2 and state.plan.attributes and ledger:
        try:
            mx = await deps.ai.structured(
                "charts", prompts.comparison_matrix(state.question, state.plan.entities, state.plan.attributes, ledger,
                                                    new_boundary()),
                ComparisonMatrixOut, max_output_tokens=3000,
                metadata={"demo": "matrix", "entities": state.plan.entities, "attributes": state.plan.attributes,
                          "evidence": ledger})
            tables.append(_matrix_table(mx, state.plan.entities, state.plan.attributes, by_id))
        except (LLMError, BudgetExceeded) as e:
            if isinstance(e, LLMError) and e.kind not in (ErrorKind.BAD_OUTPUT, ErrorKind.BUDGET):
                raise
            state.warnings.append("The comparison matrix could not be generated within budget.")
    draft_doc["tables"] = tables
    draft_doc["citation_validation"] = resolver.summary()
    await col(Collections.research_reports).update_one(
        {"_id": report_id},
        {"$set": {"draft": draft_doc, "job_id": ctx.job_id, "user_id": ctx.user_id, "status": "draft", "updated_at": utcnow()},
         "$setOnInsert": {"created_at": utcnow(), "version": 0}},
        upsert=True)
    state.report_id = report_id
    v = resolver.summary()
    await ctx.emit("report_draft", "Draft written", {"sentences": v["sentences"], "cited": v["cited_sentences"],
                                                     "invalid_citations_removed": v["invalid"]})
    state.next = "verify"
    return state


def _insufficient_evidence_report(state: ResearchState) -> dict[str, Any]:
    msg = ("We could not find verifiable evidence to answer this question within the research budget. "
           "No claims are made beyond what the sources showed.")
    return {
        "title": "Insufficient evidence: " + state.question[:150],
        "executive_summary": [{"id": new_id("p"), "segments": [{"text": msg, "evidence_ids": [], "sources": [],
                                                                "support": "n/a", "support_note": "", "dropped_markers": []}]}],
        "key_findings": [], "sections": [], "conflicts": [],
        "limitations": ["No verified evidence was found.", *(state.warnings or [])],
        "unknowns": [{"question": s.question, "why": "No verified evidence was retrieved."} for s in state.plan.subquestions],
        "conclusions": [], "recommendations": [], "insufficient_evidence": True,
    }


def _matrix_table(mx: ComparisonMatrixOut, entities: list[str], attributes: list[str],
                  by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cells: dict[tuple[str, str], dict[str, Any]] = {}
    ent_l = {e.lower(): e for e in entities}
    att_l = {a.lower(): a for a in attributes}
    for c in mx.cells:
        e = ent_l.get(c.entity.lower())
        a = att_l.get(c.attribute.lower())
        if not e or not a:
            continue
        ev = [i for i in c.evidence_ids if i in by_id]
        value = c.value if ev else "Not found in sources"
        cells[(e, a)] = {"value": value, "evidence_ids": ev, "sources": sorted({by_id[i]["source_number"] for i in ev}),
                         "dropped": [i for i in c.evidence_ids if i not in by_id]}
    rows = []
    for a in attributes:
        rows.append({"attribute": a, "cells": [cells.get((e, a), {"value": "Not found in sources", "evidence_ids": [],
                                                                  "sources": []}) for e in entities]})
    return {"id": new_id("tbl"), "type": "matrix", "title": "Comparison matrix", "columns": entities, "rows": rows,
            "notes": ["Cells without verified evidence are shown as “Not found in sources”."]}


def _iter_paragraphs(doc: dict[str, Any]) -> list[dict[str, Any]]:
    pars: list[dict[str, Any]] = []
    pars.extend(doc.get("key_findings") or [])
    pars.extend(doc.get("executive_summary") or [])
    for s in doc.get("sections") or []:
        pars.extend(s.get("paragraphs") or [])
    pars.extend(doc.get("conflicts") or [])
    pars.extend(doc.get("conclusions") or [])
    return pars


async def verify_support(doc: dict[str, Any], by_id: dict[str, dict[str, Any]], ai: AIService, ctx: JobContext | None,
                         limit: int = 48) -> dict[str, int]:
    items = []
    for par in _iter_paragraphs(doc):
        for seg in par.get("segments", []):
            if seg.get("evidence_ids") and seg.get("support") == "unverified":
                items.append(seg)
    counts = {"checked": 0, "supported": 0, "partially_supported": 0, "not_supported": 0, "not_checked": 0}
    todo = items[:limit]
    counts["not_checked"] = max(0, len(items) - limit)
    for i in range(0, len(todo), 12):
        chunk = todo[i : i + 12]
        payload = [{"sentence": s["text"], "quotes": [by_id[e]["quote"][:400] for e in s["evidence_ids"] if e in by_id]}
                   for s in chunk]
        try:
            res = await ai.structured("verification", prompts.check_support(payload, new_boundary()), SupportCheck,
                                      max_output_tokens=1500, temperature=0,
                                      metadata={"demo": "support", "items": payload})
        except (LLMError, BudgetExceeded) as e:
            if isinstance(e, LLMError) and e.kind not in (ErrorKind.BAD_OUTPUT, ErrorKind.BUDGET):
                raise
            counts["not_checked"] += len(todo) - i
            break
        verdicts = {v.index: v for v in res.verdicts}
        for j, seg in enumerate(chunk):
            v = verdicts.get(j)
            if v is None:
                counts["not_checked"] += 1
                continue
            seg["support"] = v.verdict
            seg["support_note"] = v.note
            counts["checked"] += 1
            counts[v.verdict] += 1
    if ctx is not None:
        await ctx.emit("verification", f"Checked {counts['checked']} cited statement(s): {counts['supported']} supported, "
                       f"{counts['partially_supported']} partially, {counts['not_supported']} not supported",
                       counts)
    return counts


async def node_verify(state: ResearchState, deps: Deps) -> ResearchState:
    ctx = deps.ctx
    await ctx.set_stage("verifying", status="verifying", message="Verifying claims against cited evidence")
    rep = await col(Collections.research_reports).find_one({"_id": state.report_id})
    doc = rep["draft"]
    evidence = await load_evidence(ctx.job_id)
    by_id = {e["id"]: e for e in evidence}
    counts = await verify_support(doc, by_id, deps.ai, ctx)
    contested = {i for c in state.contradictions for i in c["evidence_ids"]}
    for f in doc.get("key_findings") or []:
        cited = [by_id[i] for seg in f["segments"] for i in seg["evidence_ids"] if i in by_id]
        f["strength"] = evidence_strength(cited, contradicted=any(i in contested for seg in f["segments"] for i in seg["evidence_ids"]))
    doc["support_check"] = counts
    await col(Collections.research_reports).update_one({"_id": state.report_id}, {"$set": {"draft": doc, "updated_at": utcnow()}})
    state.next = "charts"
    return state


async def node_charts(state: ResearchState, deps: Deps) -> ResearchState:
    ctx = deps.ctx
    charts: list[dict[str, Any]] = []
    if get_settings().CHARTS_ENABLED:
        await ctx.set_stage("visualizing", status="synthesizing", message="Building charts from verified data")
        evidence = await load_evidence(ctx.job_id)
        datapoints = [{"metric": e["metric"], "entity": e["entity"], "value": e["value"], "unit": e["unit"],
                       "period": e.get("period"), "evidence_id": e["id"], "source_number": e["source_number"]}
                      for e in evidence if e.get("kind") == "datapoint"]
        sources = await load_sources(ctx.job_id)
        charts = data_charts(datapoints) + process_charts(
            sources, [e for e in evidence if e["kind"] == "claim"], [s.model_dump() for s in state.plan.subquestions])
        await ctx.emit("charts", f"{len(charts)} chart(s) from verified data",
                       {"data_charts": sum(1 for c in charts if c.get("kind") == "data"),
                        "process_charts": sum(1 for c in charts if c.get("kind") == "process")})
    await col(Collections.research_reports).update_one({"_id": state.report_id}, {"$set": {"draft.charts": charts}})
    state.next = "finalize"
    return state


async def node_finalize(state: ResearchState, deps: Deps) -> ResearchState:
    from app.research.reports import publish_report

    await publish_report(state, deps.ctx, deps.ai, partial_reason=state.partial_reason)
    state.next = "done"
    return state


# ============================================================================================
# Graph
# ============================================================================================

NODES: dict[str, Callable[[ResearchState, Deps], Awaitable[ResearchState]]] = {
    "validate": node_validate,
    "plan": node_plan,
    "search": node_search,
    "rank": node_rank,
    "extract": node_extract,
    "evidence": node_evidence,
    "assess": node_assess,
    "synthesize": node_synthesize,
    "verify": node_verify,
    "charts": node_charts,
    "finalize": node_finalize,
}


def build_graph(deps: Deps) -> Any:
    g: StateGraph = StateGraph(GraphState)

    def wrap(name: str, fn: Callable[[ResearchState, Deps], Awaitable[ResearchState]]) -> Any:
        async def _run(gs: GraphState) -> GraphState:
            st = ResearchState.model_validate(gs["s"])
            await deps.ctx.check_alive()
            st = await fn(st, deps)
            await deps.persist(st)  # durable checkpoint after every node
            return {"s": st.model_dump(mode="json")}

        _run.__name__ = f"node_{name}"
        return _run

    for name, fn in NODES.items():
        g.add_node(name, wrap(name, fn))

    def route(gs: GraphState) -> str:
        nxt = gs["s"].get("next", "done")
        return END if nxt == "done" else nxt

    targets: dict[str, str] = {n: n for n in NODES} | {END: END}
    g.add_conditional_edges(START, route, targets)
    for name in NODES:
        g.add_conditional_edges(name, route, targets)
    return g.compile()


async def run_graph(state: ResearchState, deps: Deps) -> ResearchState:
    graph = build_graph(deps)
    # recursion_limit bounds the total number of node executions (loops are also bounded by budgets).
    out = await graph.ainvoke({"s": state.model_dump(mode="json")}, config={"recursion_limit": 80})
    return ResearchState.model_validate(out["s"])
