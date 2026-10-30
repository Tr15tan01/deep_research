"""Report publication, versioning, partial reports, section regeneration and rendering."""

from __future__ import annotations

from collections import Counter
from typing import Any

from pymongo import DESCENDING

from app.core.logging import get_logger
from app.core.security import as_utc, utcnow
from app.db.mongo import Collections, col, new_id
from app.llm.service import AIService
from app.research import prompts
from app.research.citations import CitationResolver, paragraph_plain
from app.research.context import JobContext
from app.research.evidence import STRENGTH_CRITERIA, freshness
from app.research.schemas import ResearchState, SectionRewrite
from app.search.canonical import registrable_domain
from app.security.injection import new_boundary

log = get_logger("reports")


async def latest_version(job_id: str) -> int:
    doc = await col(Collections.research_reports).find_one({"job_id": job_id, "version": {"$gte": 1}},
                                                           sort=[("version", DESCENDING)], projection={"version": 1})
    return int(doc["version"]) if doc else 0


async def source_stats(job_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sources = await col(Collections.research_sources).find({"job_id": job_id}).sort("number", 1).to_list(None)
    extracted = [s for s in sources if s["status"] == "extracted"]
    stats = {
        "total": len(sources),
        "extracted": len(extracted),
        "inaccessible": sum(1 for s in sources if s["status"] == "inaccessible"),
        "by_type": dict(Counter(s.get("source_type") or "unknown" for s in extracted)),
        "domains": len({registrable_domain(s.get("domain") or "") for s in extracted}),
        "abstract_only": sum(1 for s in extracted if s.get("content_kind") == "abstract"),
        "injection_flagged": sum(1 for s in extracted if s.get("injection_flags")),
    }
    return stats, sources


async def _methodology(state: ResearchState, ctx: JobContext, ai: AIService | None) -> dict[str, Any]:
    job = await col(Collections.research_jobs).find_one({"_id": ctx.job_id}) or {}
    started = as_utc(job.get("started_at"))
    return {
        "objective": state.plan.objective,
        "subquestions": [{"id": s.id, "question": s.question, "status": s.status, "missing": s.missing}
                         for s in state.plan.subquestions],
        "plan_edited_by_user": state.plan.edited_by_user,
        "queries": [q.model_dump() for q in state.queries],
        "search_providers": sorted({q.provider for q in state.queries if q.provider}),
        "model_config": ai.describe() if ai else job.get("model_config"),
        "fallbacks": job.get("fallbacks", []),
        "budgets": ctx.budgets.as_dict(),
        "usage": job.get("usage", {}),
        "assumptions": state.assumptions,
        "clarifications": state.clarifications,
        "iterations": state.iteration + 1,
        "stop_reason": state.stop_reason,
        "rejected_candidates": len(state.rejected),
        "started_at": started,
        "executed_at": utcnow(),
        "duration_seconds": int((utcnow() - started).total_seconds()) if started else None,
        "mode": state.mode,
        "options": {k: v for k, v in state.options.items() if k not in ("upload_ids",)},
    }


async def publish_report(state: ResearchState, ctx: JobContext, ai: AIService | None, *, partial_reason: str | None = None,
                         change_note: str = "Initial report") -> dict[str, Any]:
    reports = col(Collections.research_reports)
    draft_doc: dict[str, Any] = {}
    if state.report_id:
        d = await reports.find_one({"_id": state.report_id})
        draft_doc = (d or {}).get("draft") or {}
    stats, sources = await source_stats(ctx.job_id)
    version = await latest_version(ctx.job_id) + 1
    warnings = list(state.warnings)
    if state.stop_reason:
        warnings.append(f"Research stopped early: {state.stop_reason}.")
    if stats["abstract_only"]:
        warnings.append(f"{stats['abstract_only']} source(s) were available as abstracts only (no full text).")
    if stats["injection_flagged"]:
        warnings.append(f"{stats['injection_flagged']} source(s) contained instruction-like text and were treated strictly as data.")
    cv = draft_doc.get("citation_validation") or {}
    if cv.get("invalid"):
        warnings.append(f"{cv['invalid']} citation marker(s) that did not match stored evidence were removed.")
    report = {
        "_id": new_id("rep"),
        "job_id": ctx.job_id,
        "user_id": ctx.user_id,
        "version": version,
        "status": "partial" if partial_reason else "complete",
        "partial_reason": partial_reason,
        "is_demo": ctx.is_demo,
        "question": state.question,
        "mode": state.mode,
        "title": draft_doc.get("title") or state.question[:200],
        **{k: draft_doc.get(k, [] if k not in ("support_check", "citation_validation") else {}) for k in (
            "executive_summary", "key_findings", "sections", "conflicts", "limitations", "unknowns", "conclusions",
            "recommendations", "tables", "charts", "citation_validation", "support_check")},
        "insufficient_evidence": bool(draft_doc.get("insufficient_evidence")),
        "contradictions": state.contradictions,
        "methodology": await _methodology(state, ctx, ai),
        "source_stats": stats,
        "freshness": freshness([s for s in sources if s["status"] == "extracted"]),
        "strength_criteria": STRENGTH_CRITERIA,
        "warnings": warnings,
        "change_note": change_note,
        "created_at": utcnow(),
    }
    await reports.insert_one(report)
    if state.report_id:
        await reports.delete_one({"_id": state.report_id, "version": 0})
    await col(Collections.research_jobs).update_one(
        {"_id": ctx.job_id},
        {"$set": {"report_id": report["_id"], "report_version": version, "partial": bool(partial_reason),
                  "title": report["title"], "updated_at": utcnow()}})
    await ctx.emit("report", "Partial report saved" if partial_reason else "Report ready",
                   {"report_id": report["_id"], "version": version, "status": report["status"]})
    return report


async def build_partial_report(state: ResearchState, ctx: JobContext, reason: str) -> dict[str, Any] | None:
    """Deterministic report from verified evidence gathered so far (no LLM call)."""
    evidence = await col(Collections.research_evidence).find({"job_id": ctx.job_id, "verified": True}).sort("number", 1).to_list(None)
    if not evidence and not state.plan.subquestions:
        return None
    by_id = {e["id"]: e for e in evidence}
    resolver = CitationResolver(by_id)
    sections = []
    for sq in state.plan.subquestions:
        items = [e for e in evidence if e["subquestion_id"] == sq.id and e["kind"] == "claim"][:12]
        if not items:
            continue
        pars = [resolver.paragraph(f"{e['claim'].rstrip('.')}. [{e['id']}]") for e in items]
        sections.append({"id": new_id("sec"), "title": sq.question, "paragraphs": pars})
    summary_text = (f"This research did not complete ({reason}). Below are the verified findings gathered before it "
                    "stopped, grouped by sub-question. They have not been synthesised or cross-checked into conclusions.")
    draft = {
        "title": "Partial findings: " + state.question[:150],
        "executive_summary": [{"id": new_id("p"), "segments": [{"text": summary_text, "evidence_ids": [], "sources": [],
                                                                "support": "n/a", "support_note": "", "dropped_markers": []}]}],
        "key_findings": [], "sections": sections, "conflicts": [],
        "limitations": ["Partial result: synthesis, contradiction analysis and claim verification may not have run."],
        "unknowns": [{"question": s.question, "why": "Research stopped before this was covered."}
                     for s in state.plan.subquestions if not any(e["subquestion_id"] == s.id for e in evidence)],
        "conclusions": [], "recommendations": [], "tables": [], "charts": [],
        "citation_validation": resolver.summary(), "support_check": {}, "insufficient_evidence": not evidence,
    }
    rid = state.report_id or new_id("rep")
    await col(Collections.research_reports).update_one(
        {"_id": rid}, {"$set": {"draft": draft, "job_id": ctx.job_id, "user_id": ctx.user_id, "status": "draft"},
                       "$setOnInsert": {"created_at": utcnow(), "version": 0}}, upsert=True)
    state.report_id = rid
    return await publish_report(state, ctx, None, partial_reason=reason, change_note="Partial results")


async def regenerate_section(job: dict[str, Any], report: dict[str, Any], section_id: str, instruction: str,
                             ctx: JobContext, ai: AIService) -> dict[str, Any]:
    from app.research.pipeline import load_evidence, verify_support

    section = next((s for s in report.get("sections", []) if s["id"] == section_id), None)
    if section is None:
        raise ValueError("section not found")
    evidence = await load_evidence(job["_id"])
    by_id = {e["id"]: e for e in evidence}
    used = {i for p in section["paragraphs"] for seg in p["segments"] for i in seg["evidence_ids"]}
    flagged = await col(Collections.feedback).find({"job_id": job["_id"], "kind": "citation_incorrect",
                                                    "section_id": section_id}).to_list(None)
    flagged_ids = {f.get("evidence_id") for f in flagged}
    # Prefer evidence for the section's sub-questions plus what it already cited; exclude user-flagged evidence.
    subq_ids = {by_id[i]["subquestion_id"] for i in used if i in by_id}
    pool = [e for e in evidence if (e["id"] in used or e["subquestion_id"] in subq_ids) and e["id"] not in flagged_ids][:80]
    if not pool:
        pool = [e for e in evidence if e["id"] not in flagged_ids][:80]
    section_plain = {"title": section["title"], "paragraphs_raw": [paragraph_plain(p, numbered=False) for p in section["paragraphs"]]}
    out = await ai.structured("synthesis", prompts.rewrite_section(job["question"], section_plain, pool, instruction,
                                                                    new_boundary()),
                              SectionRewrite, max_output_tokens=3000,
                              metadata={"demo": "rewrite", "evidence": pool, "title": section["title"]})
    resolver = CitationResolver({e["id"]: e for e in pool})
    new_section = {"id": section_id, "title": out.title, "paragraphs": [resolver.paragraph(p) for p in out.paragraphs],
                   "regenerated_at": utcnow(), "instruction": instruction[:500]}
    await verify_support({"sections": [new_section]}, by_id, ai, ctx)
    version = await latest_version(job["_id"]) + 1
    new_report = {**report, "_id": new_id("rep"), "version": version, "created_at": utcnow(),
                  "sections": [new_section if s["id"] == section_id else s for s in report["sections"]],
                  "change_note": f"Regenerated section “{out.title}”" + (f": {instruction[:120]}" if instruction else ""),
                  "parent_version": report["version"]}
    cv = dict(new_report.get("citation_validation") or {})
    cv["last_regeneration"] = resolver.summary()
    new_report["citation_validation"] = cv
    await col(Collections.research_reports).insert_one(new_report)
    await col(Collections.research_jobs).update_one({"_id": job["_id"]},
                                                    {"$set": {"report_id": new_report["_id"], "report_version": version}})
    return new_report


# --- Rendering --------------------------------------------------------------------------------

def _pars(pars: list[dict[str, Any]]) -> str:
    return "\n\n".join(paragraph_plain(p) for p in pars)


def bibliography(sources: list[dict[str, Any]], cited_numbers: set[int] | None = None) -> list[dict[str, Any]]:
    out = []
    for s in sources:
        if s["status"] != "extracted" and (cited_numbers is None or s["number"] not in cited_numbers):
            continue
        out.append({"number": s["number"], "title": s.get("title") or s["url"], "url": s["url"], "domain": s.get("domain"),
                    "publisher": s.get("publisher"), "author": s.get("author"), "published_at": s.get("published_at"),
                    "retrieved_at": s.get("retrieved_at"), "source_type": s.get("source_type"),
                    "content_kind": s.get("content_kind"), "cited": cited_numbers is None or s["number"] in cited_numbers})
    return out


def cited_numbers(report: dict[str, Any]) -> set[int]:
    nums: set[int] = set()
    for key in ("executive_summary", "key_findings", "conflicts", "conclusions", "recommendations"):
        for p in report.get(key) or []:
            for seg in p.get("segments", []):
                nums.update(seg.get("sources", []))
    for s in report.get("sections") or []:
        for p in s.get("paragraphs", []):
            for seg in p.get("segments", []):
                nums.update(seg.get("sources", []))
    return nums


def render_markdown(report: dict[str, Any], sources: list[dict[str, Any]]) -> str:
    L: list[str] = []
    if report.get("is_demo"):
        L.append("> **DEMO MODE — synthetic data. This is not real research.**\n")
    if report.get("status") == "partial":
        L.append(f"> **Partial report** — research did not complete ({report.get('partial_reason')}).\n")
    L.append(f"# {report['title']}\n")
    L.append(f"*Question:* {report['question']}  ")
    m = report.get("methodology") or {}
    L.append(f"*Mode:* {report.get('mode')} · *Version:* {report.get('version')} · *Generated:* {str(m.get('executed_at') or report.get('created_at'))[:19]} UTC\n")
    L.append("## Executive summary\n")
    L.append(_pars(report.get("executive_summary") or []) + "\n")
    if report.get("key_findings"):
        L.append("## Key findings\n")
        for f in report["key_findings"]:
            strength = (f.get("strength") or {}).get("label")
            L.append(f"- {paragraph_plain(f)}" + (f" *(evidence: {strength})*" if strength else ""))
        L.append("")
    for s in report.get("sections") or []:
        L.append(f"## {s['title']}\n")
        L.append(_pars(s.get("paragraphs") or []) + "\n")
    if report.get("tables"):
        for t in report["tables"]:
            L.append(f"## {t['title']}\n")
            L.append("| Attribute | " + " | ".join(t["columns"]) + " |")
            L.append("|---|" + "---|" * len(t["columns"]))
            for row in t["rows"]:
                vals = [c["value"] + ("".join(f"[{n}]" for n in c.get("sources", []))) for c in row["cells"]]
                L.append(f"| {row['attribute']} | " + " | ".join(v.replace("|", "/") for v in vals) + " |")
            L.append("")
    if report.get("conflicts"):
        L.append("## Conflicting evidence\n")
        for c in report["conflicts"]:
            L.append(f"**{c.get('topic', '')}** — {paragraph_plain(c)}\n")
    if report.get("limitations"):
        L.append("## Limitations\n")
        L.extend(f"- {x}" for x in report["limitations"])
        L.append("")
    if report.get("unknowns"):
        L.append("## What is still unknown\n")
        L.extend(f"- **{u['question']}** — {u['why']}" for u in report["unknowns"])
        L.append("")
    if report.get("conclusions"):
        L.append("## Conclusions\n")
        L.append(_pars(report["conclusions"]) + "\n")
    if report.get("recommendations"):
        L.append("## Recommendations\n")
        L.extend(f"- {paragraph_plain(p)}" for p in report["recommendations"])
        L.append("")
    L.append("## Methodology\n")
    L.append(f"Objective: {m.get('objective', '')}\n")
    for sq in m.get("subquestions", []):
        L.append(f"- {sq['id']}: {sq['question']} — *{sq['status']}*")
    L.append(f"\nSearches run: {len(m.get('queries', []))}; providers: {', '.join(m.get('search_providers') or []) or 'n/a'}.")
    mc = m.get("model_config") or {}
    if mc:
        L.append("Models: " + "; ".join(f"{k}: {v['provider']}/{v['model']}" for k, v in mc.items() if v))
    cv = report.get("citation_validation") or {}
    sc = report.get("support_check") or {}
    L.append(f"\nCitation validation: {cv.get('valid', 0)} valid markers, {cv.get('invalid', 0)} invalid removed, "
             f"{cv.get('uncited_sentences', 0)} uncited sentences. Support check: {sc.get('supported', 0)} supported, "
             f"{sc.get('partially_supported', 0)} partially, {sc.get('not_supported', 0)} not supported, "
             f"{sc.get('not_checked', 0)} not checked.\n")
    L.append("## Sources\n")
    for b in bibliography(sources, cited_numbers(report)):
        meta = ", ".join(x for x in [b.get("publisher") or b.get("domain"), b.get("author"),
                                     str(b.get("published_at") or "n.d.")[:10]] if x)
        L.append(f"[{b['number']}] {b['title']} — {meta}. {b['url']} (retrieved {str(b.get('retrieved_at') or '')[:10]})")
    return "\n".join(L) + "\n"
