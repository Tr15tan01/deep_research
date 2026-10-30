"""The agent-evaluation harness (tests/eval) — its scoring rules and a short demo run."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

EVAL = Path(__file__).resolve().parents[3] / "tests" / "eval" / "run_eval.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("run_eval", EVAL)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_eval"] = mod
    spec.loader.exec_module(mod)
    return mod


def _seg(text: str, sources: list[int] | None = None, eids: list[str] | None = None) -> dict[str, Any]:
    return {"text": text, "sources": sources or [], "evidence_ids": eids or [], "support": "supported"}


def _report(**kw: Any) -> dict[str, Any]:
    base = {"status": "complete", "title": "T", "executive_summary": [], "key_findings": [], "sections": [],
            "conflicts": [], "conclusions": [], "limitations": [], "unknowns": [], "citation_validation": {},
            "support_check": {}, "source_stats": {"extracted": 2, "domains": 2}, "tables": [], "charts": []}
    return base | kw


def test_live_scoring_rewards_insufficiency_and_penalises_fabrication() -> None:
    ev = _load()
    case = {"id": "x", "category": "insufficient_evidence", "mode": "quick",
            "expect": {"facts": [], "forbidden": ["Venthorpe won the 2019 Nobel"], "expect_insufficient": True}}
    job = {"status": "completed", "usage": {}}
    honest = _report(insufficient_evidence=True, executive_summary=[{"segments": [_seg("No verifiable evidence was found.")]}])
    invented = _report(key_findings=[{"segments": [_seg("Venthorpe won the 2019 Nobel Prize for glass lattices.", [9])]}])
    good = ev.score(case, job, honest, [], [], True, 1.0)
    bad = ev.score(case, job, invented, [], [], True, 1.0)
    assert good["checks_passed"] == good["checks_total"]
    assert not bad["checks"]["insufficiency_acknowledged"]
    assert not any(v for k, v in bad["checks"].items() if k.startswith("forbidden"))
    assert bad["citation_validity"] == 0.0  # [9] does not resolve to a retrieved source


def test_factual_rubric_accepts_alternatives() -> None:
    ev = _load()
    case = {"id": "f", "category": "factual", "mode": "quick", "expect": {"facts": [["Dec. 25, 2021", "December 25, 2021"], ["Ariane 5"]]}}
    rep = _report(executive_summary=[{"segments": [_seg("Webb launched on December 25, 2021 aboard an Ariane 5.", [1], ["E1"])]}])
    sources = [{"number": 1, "status": "extracted", "relevance": 3}]
    m = ev.score(case, {"status": "completed", "usage": {}}, rep, sources, [{"id": "E1"}], True, 2.0)
    assert m["factual_score"] == 1.0 and m["citation_validity"] == 1.0 and m["citation_relevance"] == 1.0


def test_thresholds_compare_directions() -> None:
    ev = _load()
    assert ev.compare({"completion_rate": 0.8, "latency_p95_s": 10}, {"completion_rate": 0.9, "latency_p95_s": 60}) == [
        "completion_rate=0.8 below min 0.9"]
    assert ev.compare({"cost_per_completed_usd": 2.0}, {"cost_per_completed_usd": 1.5})


async def test_demo_eval_runs_end_to_end(infra: Any, env: Any) -> None:
    ev = _load()
    env(DEMO_MODE="1", AI_PROVIDER="demo", SEARCH_PROVIDER="demo")
    import json

    cases = [json.loads(line) for line in (EVAL.parent / "dataset.jsonl").read_text().splitlines()
             if '"injection-demo-source"' in line or '"cmp-postgres-mongo-tx"' in line]
    rows = await ev.run(cases, live=False)
    assert [r["completed"] for r in rows] == [True, True]
    assert all(r["checks_passed"] == r["checks_total"] for r in rows), rows
    assert ev.aggregate(rows)["citation_validity"] == 1.0
