"""Agent evaluation harness.

Runs every case in ``dataset.jsonl`` through the *real* research pipeline (API → durable job →
worker → report), then scores the stored report with transparent, deterministic metrics.

    cd apps/api
    .venv/bin/python ../../tests/eval/run_eval.py                   # demo providers (deterministic, offline)
    ENV_FILE=../../.env .venv/bin/python ../../tests/eval/run_eval.py --live   # configured providers
    ... --only fact-jwst-launch,adv-fictional-nobel --out results/my-run.json

Demo runs check the *machinery* (citations resolve, quotes verified, injection flagged,
charts/matrix only from verified data, completion, cost accounting) and are what CI runs.
They cannot measure factual correctness — the demo corpus is synthetic. ``--live`` runs add
factual-rubric, premise-rejection and insufficient-evidence scoring against real sources.
Results are written to ``results/`` and compared with ``thresholds.json``; a regression exits 1.

Storage is always in-memory (the eval never touches a real database); only the AI and search
providers differ between modes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


def _configure_env(live: bool) -> None:
    os.environ.update({
        "APP_ENV": "test", "MONGODB_URI": "mongomock://", "REDIS_URL": "", "RATE_LIMIT_ENABLED": "0",
        "EMBEDDED_WORKER": "0", "LOG_LEVEL": os.environ.get("LOG_LEVEL", "ERROR"), "FRONTEND_URL": "http://localhost:3000",
        "AUTH_SECRET": os.environ.get("AUTH_SECRET") or "eval-" + "x" * 40,
        "UPLOAD_DIR": tempfile.mkdtemp(prefix="dr-eval-"), "MONTHLY_COST_LIMIT_USD_PER_USER": "1000",
        "DAILY_RESEARCH_JOBS_PER_USER": "1000", "MAX_CONCURRENT_RESEARCH_JOBS_PER_USER": "50",
    })
    if live:
        os.environ.setdefault("ENV_FILE", str(ROOT / ".env"))
        os.environ["DEMO_MODE"] = "0"
    else:
        os.environ.update({"ENV_FILE": "/nonexistent.env", "DEMO_MODE": "1", "AI_PROVIDER": "demo",
                           "SEARCH_PROVIDER": "demo", "DEMO_STEP_DELAY_MS": "0", "SCHOLARLY_SEARCH_ENABLED": "0"})


# ------------------------------------------------------------------------------------------
# Report text helpers
# ------------------------------------------------------------------------------------------

def _paragraphs(rep: dict[str, Any]) -> list[dict[str, Any]]:
    pars = list(rep.get("executive_summary") or []) + list(rep.get("key_findings") or [])
    for s in rep.get("sections") or []:
        pars += s.get("paragraphs") or []
    pars += list(rep.get("conflicts") or []) + list(rep.get("conclusions") or [])
    return pars


def _segments(rep: dict[str, Any]) -> list[dict[str, Any]]:
    return [seg for p in _paragraphs(rep) for seg in p.get("segments", [])]


def report_text(rep: dict[str, Any]) -> str:
    parts = [rep.get("title") or ""] + [seg.get("text", "") for seg in _segments(rep)]
    parts += [str(x) for x in rep.get("limitations") or []]
    parts += [f"{u.get('question', '')} {u.get('why', '')}" for u in rep.get("unknowns") or []]
    return "\n".join(parts)


def _contains(text: str, needle: str) -> bool:
    return needle.lower() in text.lower()


# ------------------------------------------------------------------------------------------
# Scoring
# ------------------------------------------------------------------------------------------

def score(case: dict[str, Any], job: dict[str, Any], rep: dict[str, Any] | None, sources: list[dict[str, Any]],
          evidence: list[dict[str, Any]], live: bool, seconds: float) -> dict[str, Any]:
    exp = dict(case.get("expect") or {})
    if not live:
        exp = {**{k: v for k, v in exp.items() if k in ("min_sources",)}, **(case.get("demo") or {})}
    m: dict[str, Any] = {"id": case["id"], "category": case["category"], "mode": case["mode"],
                         "status": job.get("status"), "latency_s": round(seconds, 2),
                         "cost_usd_est": round(float((job.get("usage") or {}).get("cost_usd_est", 0.0)), 5),
                         "llm_calls": (job.get("usage") or {}).get("llm_calls", 0),
                         "search_calls": (job.get("usage") or {}).get("search_calls", 0), "checks": {}}
    checks: dict[str, bool] = m["checks"]
    m["completed"] = job.get("status") == "completed" and bool(rep) and rep.get("status") == "complete"
    if not rep:
        m["error"] = (job.get("last_error") or {}).get("code")
        return m

    extracted = {s["number"]: s for s in sources if s.get("status") == "extracted"}
    ev_ids = {e["id"] for e in evidence}
    segs = _segments(rep)
    cited_numbers = [n for seg in segs for n in seg.get("sources", [])]
    cited_eids = [e for seg in segs for e in seg.get("evidence_ids", [])]

    # Citation validity: every displayed citation resolves to a retrieved, extracted source and
    # every evidence ID to a stored, quote-verified evidence record.
    # None when nothing is cited (e.g. an honest "insufficient evidence" report) — not a failure.
    n_cites = len(cited_numbers) + len(cited_eids)
    m["citation_validity"] = round(
        (sum(1 for n in cited_numbers if n in extracted) + sum(1 for e in cited_eids if e in ev_ids)) / n_cites, 4
    ) if n_cites else None
    cv = rep.get("citation_validation") or {}
    m["invalid_markers_removed"] = cv.get("invalid", 0)
    sentences = max(1, int(cv.get("sentences") or len(segs)))
    m["cited_sentence_ratio"] = round(int(cv.get("cited_sentences") or 0) / sentences, 4)

    # Claim support (LLM verifier verdicts on cited sentences; partial = 0.5).
    sc = rep.get("support_check") or {}
    checked = int(sc.get("checked") or 0)
    m["claim_support"] = (round((sc.get("supported", 0) + 0.5 * sc.get("partially_supported", 0)) / checked, 4)
                          if checked else None)
    m["unsupported_claims"] = sc.get("not_supported", 0)

    # Relevance proxy: share of cited sources the reading model scored >= 2 on its 0-3 relevance scale.
    rel = [extracted[n].get("relevance") for n in set(cited_numbers) if n in extracted]
    m["citation_relevance"] = (round(sum(1 for r in rel if isinstance(r, int) and r >= 2) / len(rel), 4) if rel else None)

    m["report_warnings"] = rep.get("warnings") or []
    m["contradictions"] = len(rep.get("contradictions") or [])
    ss = rep.get("source_stats") or {}
    m["sources_extracted"] = ss.get("extracted", 0)
    m["source_diversity"] = round(ss.get("domains", 0) / max(1, ss.get("extracted", 0)), 4)
    text = report_text(rep)

    if "min_sources" in exp:
        checks["min_sources"] = ss.get("extracted", 0) >= exp["min_sources"]
    if "min_domains" in exp:
        checks["min_domains"] = ss.get("domains", 0) >= exp["min_domains"]
    facts = exp.get("facts") or []
    if live and facts:
        hits = [any(_contains(text, alt) for alt in alts) for alts in facts]
        m["factual_score"] = round(sum(hits) / len(hits), 4)
    for f in exp.get("forbidden") or []:
        checks[f"forbidden:{f[:30]}"] = not _contains(text, f)
    if exp.get("expect_premise_rejected"):
        checks["premise_rejected"] = any(_contains(text, p) for p in exp["expect_premise_rejected"]) or bool(
            rep.get("insufficient_evidence"))
    if exp.get("expect_insufficient"):
        # Correct answer is "the evidence is insufficient": the report must say so, not invent.
        checks["insufficiency_acknowledged"] = bool(rep.get("insufficient_evidence")) or (
            len(rep.get("unknowns") or []) > 0 and len(rep.get("key_findings") or []) <= 2)
    if exp.get("expect_conflict"):
        checks["conflict_surfaced"] = bool(rep.get("conflicts") or rep.get("contradictions"))
    if exp.get("expect_conflict_or_limitations") or exp.get("expect_conflict_or_range"):
        checks["conflict_or_limits"] = bool(rep.get("conflicts") or rep.get("contradictions") or rep.get("limitations"))
    if exp.get("expect_limitations"):
        checks["limitations_present"] = bool(rep.get("limitations"))
    if exp.get("requires_scholarly"):
        checks["scholarly_sources"] = any(s.get("provider") == "openalex" for s in extracted.values())
    if exp.get("expect_matrix"):
        checks["comparison_matrix"] = any(t.get("type") == "matrix" for t in rep.get("tables") or [])
    if exp.get("expect_charts"):
        charts = rep.get("charts") or []
        checks["charts_present"] = bool(charts)
        # Every data chart point must trace to a stored, verified evidence record.
        pts = [p for c in charts if c.get("kind") == "data" for s in c.get("series", []) for p in s.get("points", [])]
        checks["chart_points_traceable"] = all(p.get("evidence_id") in ev_ids for p in pts if p.get("evidence_id"))
    if exp.get("expect_injection_flagged"):
        checks["injection_flagged"] = ss.get("injection_flagged", 0) >= 1
    if exp.get("expect_freshness_label"):
        checks["freshness_label"] = bool((rep.get("freshness") or {}).get("label"))
    checks["no_invalid_citations_shown"] = m["citation_validity"] in (None, 1.0)
    m["checks_passed"] = sum(checks.values())
    m["checks_total"] = len(checks)
    return m


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def mean(key: str) -> float | None:
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(statistics.fmean(vals), 4) if vals else None

    done = [r for r in rows if r.get("completed")]
    lat = sorted(r["latency_s"] for r in rows)
    total_checks = sum(r.get("checks_total", 0) for r in rows)
    return {
        "cases": len(rows),
        "completion_rate": round(len(done) / max(1, len(rows)), 4),
        "citation_validity": mean("citation_validity"),
        "citation_relevance": mean("citation_relevance"),
        "claim_support": mean("claim_support"),
        "cited_sentence_ratio": mean("cited_sentence_ratio"),
        "source_diversity": mean("source_diversity"),
        "factual_score": mean("factual_score"),
        "check_pass_rate": round(sum(r.get("checks_passed", 0) for r in rows) / total_checks, 4) if total_checks else None,
        "cost_per_completed_usd": round(sum(r["cost_usd_est"] for r in rows) / max(1, len(done)), 5),
        "latency_p50_s": lat[len(lat) // 2] if lat else None,
        "latency_p95_s": lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else None,
    }


def compare(summary: dict[str, Any], thresholds: dict[str, Any]) -> list[str]:
    problems = []
    for k, t in thresholds.items():
        v = summary.get(k)
        if v is None:
            continue
        if k.startswith(("latency", "cost")):
            if v > t:
                problems.append(f"{k}={v} exceeds max {t}")
        elif v < t:
            problems.append(f"{k}={v} below min {t}")
    return problems


# ------------------------------------------------------------------------------------------
# Execution
# ------------------------------------------------------------------------------------------

async def run(cases: list[dict[str, Any]], live: bool, max_rounds: int = 400) -> list[dict[str, Any]]:
    import fakeredis
    import httpx
    from mongomock_motor import AsyncMongoMockClient

    from app.db import mongo, redis
    from app.db.mongo import Collections, col
    from app.jobs import lifecycle
    from app.jobs.worker import Worker
    from app.main import create_app

    mongo.use_database(AsyncMongoMockClient(tz_aware=False)["eval"])
    redis.use_redis(fakeredis.FakeAsyncRedis(decode_responses=True))
    await mongo.ensure_indexes()
    app = create_app()
    rows = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost:3000") as c:
        csrf = (await c.get("/api/v1/auth/csrf")).json()["csrf_token"]
        hdr = {"x-csrf-token": csrf, "origin": "http://localhost:3000"}
        r = await c.post("/api/v1/auth/register", json={"email": "eval@example.com", "password": "Str0ng!Passw0rd-Harness"},
                         headers=hdr)
        r.raise_for_status()
        hdr["x-csrf-token"] = c.cookies.get("dr_csrf") or csrf
        worker = Worker(concurrency=1, worker_id="eval")
        for case in cases:
            t0 = time.monotonic()
            r = await c.post("/api/v1/research", json={"question": case["question"], "mode": case["mode"], "options": {}},
                             headers=hdr)
            if r.status_code != 202:
                rows.append({"id": case["id"], "category": case["category"], "mode": case["mode"], "completed": False,
                             "status": "rejected", "error": r.json().get("error", {}).get("code"), "latency_s": 0.0,
                             "cost_usd_est": 0.0, "checks": {}})
                continue
            job_id = r.json()["job"]["id"]
            for _ in range(max_rounds):
                job = await col(Collections.research_jobs).find_one({"_id": job_id})
                if job["status"] in lifecycle.TERMINAL:
                    break
                if job["status"] == "waiting_for_retry":  # fast-forward backoff; attempts stay bounded
                    await col(Collections.research_jobs).update_one({"_id": job_id}, {"$set": {"next_attempt_at": None}})
                claimed = await lifecycle.claim(job_id, "eval")
                if claimed:
                    await worker.process(claimed)
            job = await col(Collections.research_jobs).find_one({"_id": job_id})
            seconds = time.monotonic() - t0
            rep = (await c.get(f"/api/v1/research/{job_id}/report")).json().get("report") if job.get("report_id") else None
            sources = (await c.get(f"/api/v1/research/{job_id}/sources")).json().get("items", [])
            evidence = await col(Collections.research_evidence).find({"job_id": job_id, "verified": True}).to_list(None)
            row = score(case, job, rep, sources, evidence, live, seconds)
            rows.append(row)
            mark = "✓" if row.get("completed") and row.get("checks_passed") == row.get("checks_total") else "✗"
            print(f"  {mark} {case['id']:<32} {row['status']:<10} cites={row.get('citation_validity')} "
                  f"support={row.get('claim_support')} checks={row.get('checks_passed', 0)}/{row.get('checks_total', 0)} "
                  f"{row['latency_s']}s", flush=True)
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="use configured AI/search providers instead of demo")
    ap.add_argument("--only", default="", help="comma-separated case IDs")
    ap.add_argument("--out", default="", help="results file (default results/<timestamp>-<mode>.json)")
    ap.add_argument("--no-thresholds", action="store_true", help="report only; never fail")
    args = ap.parse_args(argv)
    _configure_env(args.live)

    cases = [json.loads(line) for line in (HERE / "dataset.jsonl").read_text().splitlines() if line.strip()]
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    if not args.live:
        cases = [c for c in cases if (c.get("demo") or {}).get("run")]
    label = "live" if args.live else "demo"
    print(f"Running {len(cases)} case(s) with {label} providers")
    rows = asyncio.run(run(cases, args.live))
    summary = aggregate(rows)
    thresholds = json.loads((HERE / "thresholds.json").read_text())[label]
    problems = [] if args.no_thresholds or args.only else compare(summary, thresholds)
    out = Path(args.out) if args.out else HERE / "results" / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"mode": label, "created_at": datetime.now(UTC).isoformat(), "summary": summary,
                               "thresholds": thresholds, "regressions": problems, "cases": rows}, indent=2, default=str))
    print("\nSummary:")
    for k, v in summary.items():
        print(f"  {k:<24} {v}")
    print(f"\nWrote {out}")
    if problems:
        print("REGRESSIONS:\n  " + "\n  ".join(problems))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
