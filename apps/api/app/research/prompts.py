"""Prompt builders for each LLM-backed research step.

Conventions:
  * Untrusted text (web pages, uploads) is always wrapped with randomised delimiters and the
    UNTRUSTED_DATA_POLICY is included in the system prompt.
  * Models cite only evidence IDs (E#) that we provide; we map them to sources ourselves.
  * Every step has a narrow, schema-constrained output.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.security import utcnow
from app.llm.base import Message
from app.security.injection import UNTRUSTED_DATA_POLICY, wrap_untrusted

BASE_SYSTEM = (
    "You are a meticulous research analyst. You value accuracy over fluency, distinguish evidence from inference, "
    "state uncertainty plainly, and never invent sources, quotes, numbers, dates or URLs. Today's date is {today}."
)


def _system(extra: str = "", untrusted: bool = False) -> Message:
    parts = [BASE_SYSTEM.format(today=utcnow().date().isoformat())]
    if untrusted:
        parts.append(UNTRUSTED_DATA_POLICY)
    if extra:
        parts.append(extra)
    return Message(role="system", content="\n\n".join(parts))


def assess_question(question: str, mode: str, clarifications: list[str]) -> list[Message]:
    clar = ("\nUser clarifications:\n- " + "\n- ".join(clarifications)) if clarifications else ""
    return [
        _system("Your task: assess a research request before planning. Identify genuine ambiguities that would change "
                "the research direction (not trivia). Refuse only requests whose purpose is clearly to cause serious "
                "harm (e.g. weapons capable of mass casualties, targeting private individuals)."),
        Message(role="user", content=f"Research mode: {mode}\nResearch request:\n\"\"\"{question}\"\"\"{clar}"),
    ]


def plan(question: str, mode: str, max_subq: int, assessment: dict[str, Any] | None, clarifications: list[str],
         options: dict[str, Any]) -> list[Message]:
    hints = []
    if mode in ("competitive", "technology", "market"):
        hints.append("This is a comparison: list the entities being compared and 4-8 comparison attributes that can be "
                     "verified from public sources (e.g. pricing, key features, limitations, adoption).")
    if mode == "academic":
        hints.append("Favour scholarly literature; phrase queries the way papers are titled and abstracted.")
    if mode == "verify_claim":
        hints.append("Include sub-questions that look for evidence FOR and AGAINST the claim, and its original source.")
    if mode == "counterarguments":
        hints.append("Focus on the strongest credible counterarguments, critiques and contrary evidence.")
    if options.get("date_from") or options.get("date_to"):
        hints.append(f"Time window of interest: {options.get('date_from') or 'any'} to {options.get('date_to') or 'present'}.")
    if options.get("source_preferences"):
        hints.append("Preferred source types: " + ", ".join(options["source_preferences"]))
    ctx = ""
    if assessment:
        ctx = f"\nAssessment: {json.dumps({k: assessment.get(k) for k in ('restated_question', 'question_type', 'assumptions_if_unclarified')})}"
    if clarifications:
        ctx += "\nUser clarifications:\n- " + "\n- ".join(clarifications)
    return [
        _system("Your task: produce a research plan. Break the question into at most "
                f"{max_subq} non-overlapping sub-questions that together answer it. For each, give 1-3 specific "
                "search queries (no quotes or operators unless essential). Prefer queries that surface primary sources "
                "(official data, filings, documentation, studies). " + " ".join(hints)),
        Message(role="user", content=f"Research question:\n\"\"\"{question}\"\"\"{ctx}"),
    ]


def extract_evidence(question: str, subquestions: list[dict[str, str]], sources: list[dict[str, Any]],
                     boundary: str) -> list[Message]:
    subq = "\n".join(f"{s['id']}: {s['question']}" for s in subquestions)
    blocks = []
    for s in sources:
        label = f"source={s['label']} title={json.dumps(s.get('title') or '')[:200]} url={s.get('url', '')}"
        blocks.append(wrap_untrusted(label, s["text"], boundary))
    return [
        _system(
            "Your task: read the source(s) and extract evidence relevant to the sub-questions.\n"
            "Rules:\n"
            "1. Every claim must have a `quote` copied EXACTLY (verbatim, same words) from that source's text. "
            "Quotes that are not verbatim will be discarded automatically.\n"
            "2. Keep quotes short (one or two sentences) and claims specific (who, what, when, how much).\n"
            "3. Mark stance 'contradicts' when the source disputes a common or opposing claim; 'context' for background.\n"
            "4. Record numbers as datapoints only when the value, unit and entity are explicit in the quote.\n"
            "5. source_type: 'primary' = original data/official statement/study/filing/documentation from the "
            "originator; 'secondary' = reporting or analysis of others' work; 'commentary' = opinion, marketing, "
            "forums or unattributed claims.\n"
            "6. If the text is irrelevant, return relevance 0 and no claims. Do not use outside knowledge.\n"
            "7. When given several sources, return one assessment per source in the same order.",
            untrusted=True),
        Message(role="user", content=f"Research question: {question}\nSub-questions:\n{subq}\n\n" + "\n\n".join(blocks)),
    ]


def gap_analysis(question: str, subquestions: list[dict[str, Any]], evidence: list[dict[str, Any]],
                 remaining_iterations: int) -> list[Message]:
    ev = "\n".join(f"{e['id']} [{e['subquestion_id']}] ({e['source_type']}, {e.get('published') or 'undated'}, "
                   f"{e['domain']}): {e['claim']}" + (" [CONTRADICTS]" if e.get("stance") == "contradicts" else "")
                   for e in evidence)
    subq = "\n".join(f"{s['id']}: {s['question']}" for s in subquestions)
    return [
        _system("Your task: judge whether the gathered evidence is sufficient, find contradictions, and propose "
                "targeted follow-up searches. A sub-question is sufficient only if supported by at least two "
                "independent sources, or one authoritative primary source. Flag stale evidence when recency matters. "
                f"Propose follow-up queries only if they are likely to fill a real gap (follow-up rounds left: "
                f"{remaining_iterations}). List what remains genuinely unknown."),
        Message(role="user", content=f"Question: {question}\nSub-questions:\n{subq}\n\nEvidence (claims are summaries):\n{ev}"),
    ]


def synthesize(question: str, mode: str, plan: dict[str, Any], evidence: list[dict[str, Any]],
               contradictions: list[dict[str, Any]], unknowns: list[dict[str, Any]], boundary: str) -> list[Message]:
    ev_lines = []
    for e in evidence:
        ev_lines.append(json.dumps({"id": e["id"], "subq": e["subquestion_id"], "claim": e["claim"], "quote": e["quote"],
                                    "source": e["source_number"], "type": e["source_type"], "date": e.get("published"),
                                    "domain": e["domain"], "stance": e.get("stance")}, ensure_ascii=False))
    evidence_block = wrap_untrusted("evidence-ledger", "\n".join(ev_lines), boundary)
    return [
        _system(
            "Your task: write a rigorous research report from the evidence ledger ONLY.\n"
            "Citation rules (strict):\n"
            "- Support every factual sentence with one or more evidence markers like [E3] or [E3][E7], placed at the end "
            "of the sentence. Use only IDs that appear in the ledger.\n"
            "- Never state facts that are not in the ledger. If something important is unsupported, say it is unknown.\n"
            "- When sources disagree, present each side with its markers and explain the disagreement.\n"
            "- Distinguish primary data from commentary in your wording ('according to the company…', 'one analyst argues…').\n"
            "- Note when evidence is old or undated if recency matters.\n"
            "Style: clear, specific, neutral; short paragraphs; no marketing language; no headings inside paragraphs. "
            "Key findings should each be one or two sentences. Recommendations must follow from the evidence and be "
            "phrased as considerations, not certainties.",
            untrusted=True),
        Message(role="user", content=(
            f"Research question: {question}\nMode: {mode}\n"
            f"Plan: {json.dumps({'objective': plan.get('objective'), 'subquestions': [s['question'] for s in plan.get('subquestions', [])]})}\n"
            f"Known contradictions: {json.dumps(contradictions)[:3000]}\n"
            f"Known unknowns: {json.dumps(unknowns)[:2000]}\n\nEvidence ledger:\n{evidence_block}")),
    ]


def rewrite_section(question: str, section: dict[str, Any], evidence: list[dict[str, Any]], instruction: str,
                    boundary: str) -> list[Message]:
    ev = "\n".join(json.dumps({"id": e["id"], "claim": e["claim"], "quote": e["quote"], "type": e["source_type"],
                               "date": e.get("published")}, ensure_ascii=False) for e in evidence)
    return [
        _system("Your task: rewrite one section of a research report using only the evidence ledger. Every factual "
                "sentence must end with [E#] markers from the ledger. Do not introduce new facts.", untrusted=True),
        Message(role="user", content=(f"Research question: {question}\nSection title: {section['title']}\n"
                                      f"Current text:\n{json.dumps(section.get('paragraphs_raw') or section.get('paragraphs'), ensure_ascii=False)[:6000]}\n"
                                      f"User instruction: {instruction or 'Improve accuracy and clarity.'}\n\n"
                                      f"Evidence ledger:\n{wrap_untrusted('evidence-ledger', ev, boundary)}")),
    ]


def check_support(items: list[dict[str, Any]], boundary: str) -> list[Message]:
    lines = []
    for i, it in enumerate(items):
        lines.append(f"#{i}\nSTATEMENT: {it['sentence']}\nCITED EVIDENCE:\n" +
                     "\n".join(f"- {q}" for q in it["quotes"]))
    return [
        _system("Your task: for each numbered statement, decide whether the cited evidence passages support it. "
                "'supported' = the passages state it; 'partially_supported' = some parts are supported but details "
                "(numbers, scope, dates, attribution) go beyond the passages; 'not_supported' = the passages do not "
                "say this. Judge only against the passages, not your own knowledge.", untrusted=True),
        Message(role="user", content=wrap_untrusted("statements", "\n\n".join(lines), boundary)),
    ]


def comparison_matrix(question: str, entities: list[str], attributes: list[str], evidence: list[dict[str, Any]],
                      boundary: str) -> list[Message]:
    ev = "\n".join(json.dumps({"id": e["id"], "claim": e["claim"], "quote": e["quote"]}, ensure_ascii=False) for e in evidence)
    return [
        _system("Your task: fill a comparison matrix using only the evidence ledger. For each entity × attribute, give a "
                "short value (under 15 words) and the evidence IDs that state it. If the ledger does not state it, set "
                "value to 'Not found in sources' and evidence_ids to [].", untrusted=True),
        Message(role="user", content=(f"Question: {question}\nEntities: {json.dumps(entities)}\nAttributes: {json.dumps(attributes)}\n\n"
                                      f"Evidence ledger:\n{wrap_untrusted('evidence-ledger', ev, boundary)}")),
    ]
