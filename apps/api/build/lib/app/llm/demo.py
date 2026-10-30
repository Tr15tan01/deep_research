"""DEMO MODE language-model provider.

Deterministic, offline and *not* a real model. It builds schema-valid outputs from the
structured context the pipeline passes in ``LLMRequest.metadata`` (sources, evidence IDs),
so the real downstream machinery — quote verification, citation validation, charts,
checkpointing, SSE — can be exercised end-to-end. Everything it produces is marked as demo.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from app.llm.base import (
    LLMRequest,
    LLMResult,
    ModelCapabilities,
    ModelInfo,
    TokenUsage,
    estimate_request_tokens,
    estimate_tokens,
)
from app.search.demo import ENTITIES, demo_pause, sentence_case, topic_from

_SENT = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str) -> list[str]:
    out = []
    for para in text.split("\n"):
        for s in _SENT.split(para.strip()):
            s = s.strip()
            if 25 <= len(s) <= 400:
                out.append(s)
    return out


def _overlap(a: str, b: str) -> float:
    wa = set(re.findall(r"[a-z0-9]{3,}", a.lower()))
    wb = set(re.findall(r"[a-z0-9]{3,}", b.lower()))
    return len(wa & wb) / max(len(wa), 1)


class DemoProvider:
    name = "demo"

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(id="demo-deterministic", display_name="Demo (deterministic, not a real model)",
                          context_window=1_000_000, max_output_tokens=32_000, source="demo")]

    async def stream(self, req: LLMRequest, model: str, caps: ModelCapabilities) -> AsyncIterator[str]:
        res = await self.generate(req, model, caps)
        for i in range(0, len(res.text), 40):
            yield res.text[i : i + 40]

    async def generate(self, req: LLMRequest, model: str, caps: ModelCapabilities) -> LLMResult:
        await demo_pause()
        md = req.metadata or {}
        kind = md.get("demo")
        builder = getattr(self, f"_{kind}", None) if kind else None
        parsed: Any = builder(md) if builder else None
        text = json.dumps(parsed) if parsed is not None else "pong"
        return LLMResult(text=text, parsed=parsed, provider="demo", model=model,
                         usage=TokenUsage(input_tokens=estimate_request_tokens(req), output_tokens=estimate_tokens(text)),
                         finish_reason="stop", latency_ms=5)

    # --- builders --------------------------------------------------------------------------
    def _assess(self, md: dict[str, Any]) -> dict[str, Any]:
        q = md.get("question", "")
        return {"restated_question": q.strip(), "question_type": "comparison" if " vs" in q.lower() or "compare" in q.lower()
                else "analysis", "is_researchable": True, "ambiguities": [],
                "clarifying_questions": ["Which time period matters most to you?"],
                "assumptions_if_unclarified": ["Demo mode: the most recent available period is assumed."],
                "safety": "ok", "safety_reason": ""}

    def _plan(self, md: dict[str, Any]) -> dict[str, Any]:
        topic = topic_from(md.get("question", "the topic"))
        n = max(2, min(int(md.get("max_subq", 4)), 5))
        templates = [
            (f"What is {topic} and how is it measured?", [f"{topic} definition", f"{topic} measurement"]),
            (f"What does current data say about adoption of {topic}?", [f"{topic} adoption statistics", f"{topic} survey 2024"]),
            (f"How do the main options for {topic} compare on cost and performance?", [f"{topic} pricing comparison"]),
            (f"What are the main limitations or disagreements about {topic}?", [f"{topic} limitations", f"{topic} criticism"]),
            (f"How has {topic} changed over time?", [f"{topic} trend 2022 2024"]),
        ]
        comparison = md.get("mode") in ("competitive", "technology", "market")
        return {"objective": f"Understand {topic} using verifiable sources (demo).",
                "subquestions": [{"question": q, "rationale": "Demo plan step.", "source_types": ["statistics", "documentation"],
                                  "search_queries": qs} for q, qs in templates[:n]],
                "entities": ENTITIES[:2] if comparison else [],
                "comparison_attributes": ["Monthly price", "Demo Index (2024)", "Main limitation"] if comparison else [],
                "out_of_scope": []}

    def _evidence(self, md: dict[str, Any]) -> dict[str, Any]:
        subqs = [s["id"] for s in md.get("subquestions", [])] or ["Q1"]
        out = []
        for si, src in enumerate(md.get("sources", [])):
            text = src["text"]
            label = src["label"]
            url = src.get("url", "")
            stype = "primary" if ("stats-office" in url or "journal" in url or "vendor" in url) else (
                "commentary" if "blog" in url else "secondary")
            # Disclaimers label the page as synthetic; they are not findings. Injection text is never a claim.
            sents = [s for s in _sentences(text) if not s.startswith("DEMO CONTENT") and "Ignore previous" not in s
                     and "synthetic demonstration content" not in s and "not real research data" not in s
                     and "prompt injection" not in s]
            claims = []
            for i, s in enumerate([s for s in sents if "Demo Index" not in s][:4]):
                claims.append({"subquestion_id": subqs[(si + i) % len(subqs)], "claim": s.rstrip("."), "quote": s,
                               "stance": "contradicts" if "competing" in s else "supports",
                               "claim_type": "statistic" if re.search(r"\d", s) else "fact"})
            dps = []
            for s in sents:
                m = re.search(r"The Demo Index for (\w+) was (\d+) points in (\d{4})", s)
                if m:
                    dps.append({"metric": "Demo Index", "entity": m.group(1), "value": float(m.group(2)), "unit": "points",
                                "period": m.group(3), "quote": s})
                m2 = re.search(r"(\w+) offers a monthly plan priced at (\d+) USD per month", s)
                if m2:
                    dps.append({"metric": "Monthly price", "entity": m2.group(1), "value": float(m2.group(2)),
                                "unit": "USD/month", "period": None, "quote": f"{m2.group(1)} offers a monthly plan priced at {m2.group(2)} USD per month"})
            out.append({"source_label": label, "source_type": stype, "source_type_reason": "demo heuristic",
                        "publisher": None, "published_date": None, "author": None, "relevance": 3,
                        "reliability_notes": "Synthetic demo source.",
                        "contains_instructions_to_ai": "Ignore previous instructions" in text,
                        "claims": claims, "datapoints": dps[:8]})
        return {"sources": out}

    def _gaps(self, md: dict[str, Any]) -> dict[str, Any]:
        ev = md.get("evidence", [])
        subqs = md.get("subquestions", [])
        statuses = []
        for s in subqs:
            n = sum(1 for e in ev if e["subquestion_id"] == s["id"])
            statuses.append({"subquestion_id": s["id"], "sufficient": n >= 2, "missing": "" if n >= 2 else "Fewer than two items."})
        contra = [e["id"] for e in ev if e.get("stance") == "contradicts"][:1]
        adopt = [e["id"] for e in ev if "percent had adopted" in e["claim"]][:1]
        contradictions = ([{"topic": "Adoption rate", "evidence_ids": adopt + contra,
                            "explanation": "Demo sources use different definitions of adoption."}] if contra and adopt else [])
        follow = []
        if md.get("can_follow") and subqs:
            follow = [{"subquestion_id": subqs[-1]["id"], "query": subqs[-1]["question"][:80] + " evidence", "reason": "demo follow-up"}]
        return {"statuses": statuses, "contradictions": contradictions, "followup_queries": follow,
                "unknowns": [{"question": "How would results differ with real-world data?",
                              "why": "This is demo mode; no real sources were consulted."}]}

    def _synthesis(self, md: dict[str, Any]) -> dict[str, Any]:
        ev = [e for e in md.get("evidence", []) if e.get("kind", "claim") == "claim"] or md.get("evidence", [])
        subqs = md.get("subquestions", [])
        topic = topic_from(md.get("question", "the topic"))

        def cite(items: list[dict[str, Any]]) -> str:
            return "".join(f"[{e['id']}]" for e in items)

        sections = []
        findings = []
        for sq in subqs:
            items = [e for e in ev if e["subquestion_id"] == sq["id"]][:4]
            if not items:
                continue
            paras = [f"{items[0]['claim'].rstrip('.')}. {cite(items[:1])}"]
            if len(items) > 1:
                paras.append(f"Another demo source adds that {items[1]['claim'][0].lower() + items[1]['claim'][1:].rstrip('.')}. {cite(items[1:2])}")
            sections.append({"title": sq["question"], "paragraphs": paras})
            if all(f["claim"] != items[0]["claim"] for f in findings):  # one finding per distinct claim
                findings.append({"text": f"{items[0]['claim'].rstrip('.')}. {cite(items[:2])}", "claim": items[0]["claim"]})
        conflicts = [{"topic": c["topic"], "summary": f"Demo sources disagree on {c['topic'].lower()}. "
                      + "".join(f"[{i}]" for i in c["evidence_ids"])} for c in md.get("contradictions", [])]
        lead = ev[:3]
        return {
            "title": f"{sentence_case(topic)}: demo research report",
            "executive_summary": [f"This demo report illustrates how the agent summarises evidence about {topic}. "
                                  f"{lead[0]['claim'].rstrip('.') if lead else 'No evidence was found'}. {cite(lead[:1])}",
                                  "All content is synthetic and exists only to demonstrate the workflow."],
            "key_findings": [{"text": f["text"]} for f in findings[:5]] or [{"text": "No verified findings in demo data."}],
            "sections": sections or [{"title": "Findings", "paragraphs": ["No verified evidence was available."]}],
            "conflicts": conflicts,
            "limitations": ["DEMO MODE: every source is synthetic.", "Demo evidence does not reflect reality."],
            "unknowns": md.get("unknowns", []),
            "conclusions": [f"In this demo, the evidence ledger is consistent enough to illustrate a conclusion about {topic}. {cite(ev[:2])}"],
            "recommendations": ["Connect real AI and search providers to run genuine research."],
        }

    def _matrix(self, md: dict[str, Any]) -> dict[str, Any]:
        cells = []
        ev = md.get("evidence", [])
        for ent in md.get("entities", []):
            for att in md.get("attributes", []):
                match = None
                for e in ev:
                    c = e["claim"]
                    if ent in c and (("price" in att.lower() and "USD" in c) or ("index" in att.lower() and "Demo Index" in c and "2024" in c)):
                        match = e
                        break
                if match:
                    cells.append({"entity": ent, "attribute": att, "value": match["claim"][:80], "evidence_ids": [match["id"]]})
                else:
                    cells.append({"entity": ent, "attribute": att, "value": "Not found in sources", "evidence_ids": []})
        return {"cells": cells}

    def _support(self, md: dict[str, Any]) -> dict[str, Any]:
        verdicts = []
        for i, it in enumerate(md.get("items", [])):
            best = max((_overlap(it["sentence"], q) for q in it["quotes"]), default=0.0)
            v = "supported" if best >= 0.6 else ("partially_supported" if best >= 0.3 else "not_supported")
            verdicts.append({"index": i, "verdict": v, "note": f"demo word-overlap {best:.2f}"})
        return {"verdicts": verdicts}

    def _rewrite(self, md: dict[str, Any]) -> dict[str, Any]:
        ev = md.get("evidence", [])[:3]
        paras = [f"{e['claim'].rstrip('.')}. [{e['id']}]" for e in ev] or ["No verified evidence available."]
        return {"title": md.get("title", "Section"), "paragraphs": paras}
