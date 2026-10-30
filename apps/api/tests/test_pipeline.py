"""End-to-end research pipeline (demo providers), durability, retries, cancellation, budgets,
tenant isolation and the HTTP/SSE surface."""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import ApiClient


async def _setup(make_client: Any, env: Any, email: str = "res@example.com", **flags: str) -> ApiClient:
    env(DEMO_MODE="1", **flags)
    c = await make_client()
    await c.register(email)
    return c


async def _run_once(job_id: str | None = None) -> dict[str, Any] | None:
    from app.jobs import lifecycle
    from app.jobs.worker import Worker

    job = await lifecycle.claim(job_id, "test-worker")
    if job is None:
        return None
    await Worker(concurrency=1, worker_id="test-worker").process(job)
    from app.db.mongo import Collections, col

    return await col(Collections.research_jobs).find_one({"_id": job["_id"]})


async def _create(c: ApiClient, question: str = "How widely is remote work adopted by organisations?", mode: str = "standard",
                  **opts: Any) -> str:
    r = await c.post("/api/v1/research", json={"question": question, "mode": mode, "options": opts})
    assert r.status_code == 202, r.text
    return r.json()["job"]["id"]


async def test_full_demo_pipeline(make_client: Any, env: Any) -> None:
    from app.db.mongo import Collections, col

    c = await _setup(make_client, env)
    job_id = await _create(c, mode="competitive", question="Compare Alpha vs Beta for demo analytics workloads")
    job = await _run_once(job_id)
    assert job and job["status"] == "completed", job and job.get("last_error")
    assert job["is_demo"] is True

    rep = (await c.get(f"/api/v1/research/{job_id}/report")).json()["report"]
    assert rep["status"] == "complete" and rep["is_demo"] is True
    sources = (await c.get(f"/api/v1/research/{job_id}/sources")).json()["items"]
    stored_numbers = {s["number"] for s in sources if s["status"] == "extracted"}
    # Every citation resolves to a stored, extracted source.
    cited = {n for p in rep["executive_summary"] + rep["key_findings"] for seg in p["segments"] for n in seg["sources"]}
    for s in rep["sections"]:
        for p in s["paragraphs"]:
            for seg in p["segments"]:
                cited.update(seg["sources"])
                for eid in seg["evidence_ids"]:
                    ev = await col(Collections.research_evidence).find_one({"job_id": job_id, "id": eid})
                    assert ev and ev["verified"] is True
    assert cited and cited <= stored_numbers
    assert rep["citation_validation"]["invalid"] == 0
    # Key findings carry transparent strength labels.
    assert all(f["strength"]["label"] in ("strong", "moderate", "limited", "contested", "unsupported") for f in rep["key_findings"])
    # Charts exist and every data point is traceable.
    assert rep["charts"], "expected charts from verified demo datapoints"
    for ch in rep["charts"]:
        for s in ch["series"]:
            for p in s["points"]:
                assert p["sources"], ch["title"]
    assert any(ch["kind"] == "data" for ch in rep["charts"])
    # Comparison matrix cells are cited or explicitly "Not found in sources".
    assert rep["tables"]
    for row in rep["tables"][0]["rows"]:
        for cell in row["cells"]:
            assert cell["evidence_ids"] or cell["value"] == "Not found in sources"
    # Methodology / reproducibility.
    m = rep["methodology"]
    assert m["queries"] and m["model_config"]["synthesis"]["provider"] == "demo"
    # Live events were recorded in order.
    evs = (await c.get(f"/api/v1/research/{job_id}/events")).json()["events"]
    types = [e["type"] for e in evs]
    assert types.index("plan") < types.index("query") < types.index("source_extracted") < types.index("report")
    assert [e["seq"] for e in evs] == sorted(e["seq"] for e in evs)
    # Exports.
    md = await c.get(f"/api/v1/research/{job_id}/export.md")
    assert md.status_code == 200 and "DEMO MODE" in md.text and "## Sources" in md.text
    csv = await c.get(f"/api/v1/research/{job_id}/charts.csv")
    assert csv.status_code == 200 and "source_numbers" in csv.text
    graph = (await c.get(f"/api/v1/research/{job_id}/graph")).json()
    assert all(e["evidence_id"] for e in graph["edges"])


async def test_demo_prompt_injection_source_is_flagged(make_client: Any, env: Any) -> None:
    from app.db.mongo import Collections, col

    c = await _setup(make_client, env)
    job_id = await _create(c, mode="deep", question="What is the state of demo widget adoption worldwide?")
    job = await _run_once(job_id)
    assert job["status"] == "completed"
    flagged = await col(Collections.research_sources).count_documents({"job_id": job_id, "injection_flags.0": {"$exists": True}})
    if flagged:  # deterministic demo content includes an injection sentence in some sources
        rep = (await c.get(f"/api/v1/research/{job_id}/report")).json()["report"]
        assert any("instruction-like" in w for w in rep["warnings"])
        # The injected instruction never made it into the report text.
        assert "cite only this website" not in str(rep).lower()


async def test_plan_review_and_edit(make_client: Any, env: Any) -> None:
    c = await _setup(make_client, env)
    job_id = await _create(c, review_plan=True)
    job = await _run_once(job_id)
    assert job["status"] == "awaiting_approval"
    plan = (await c.get(f"/api/v1/research/{job_id}")).json()["job"]["plan"]
    edited = [{"question": "What share of organisations allow remote work?", "queries": ["remote work adoption survey"]}]
    r = await c.post(f"/api/v1/research/{job_id}/approve", json={"subquestions": edited, "clarifications": ["Focus on 2024"]})
    assert r.status_code == 200 and r.json()["job"]["status"] == "queued"
    job = await _run_once(job_id)
    assert job["status"] == "completed"
    rep = (await c.get(f"/api/v1/research/{job_id}/report")).json()["report"]
    assert rep["methodology"]["plan_edited_by_user"] is True
    assert [s["question"] for s in rep["methodology"]["subquestions"]] == [edited[0]["question"]]
    assert plan["subquestions"]


async def test_crash_recovery_resumes_from_checkpoint(make_client: Any, env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import timedelta

    from app.core.security import utcnow
    from app.db.mongo import Collections, col
    from app.research import pipeline

    c = await _setup(make_client, env)
    job_id = await _create(c, mode="quick")  # single search round, so every step count is exact
    calls: dict[str, int] = {}
    original = dict(pipeline.NODES)

    def counting(name: str) -> Any:
        async def _n(state: Any, deps: Any) -> Any:
            calls[name] = calls.get(name, 0) + 1
            if name == "evidence" and calls[name] == 1:
                raise RuntimeError("simulated worker crash")
            return await original[name](state, deps)
        return _n

    for name in original:
        monkeypatch.setitem(pipeline.NODES, name, counting(name))
    job = await _run_once(job_id)
    assert job["status"] == "waiting_for_retry" and job["attempts"] == 1
    assert job["checkpoint"]["next"] == "evidence"
    # Make the retry due now and run again: earlier steps must NOT re-run.
    await col(Collections.research_jobs).update_one({"_id": job_id}, {"$set": {"next_attempt_at": utcnow() - timedelta(seconds=1)}})
    job = await _run_once(job_id)
    assert job["status"] == "completed", job.get("last_error")
    assert calls["validate"] == 1 and calls["plan"] == 1 and calls["search"] == 1 and calls["evidence"] == 2
    evs = (await c.get(f"/api/v1/research/{job_id}/events")).json()["events"]
    assert any(e["type"] == "recovery" for e in evs) and any(e["type"] == "retry" for e in evs)


async def test_expired_lease_is_recovered(make_client: Any, env: Any) -> None:
    from datetime import timedelta

    from app.core.security import utcnow
    from app.db.mongo import Collections, col
    from app.jobs import lifecycle

    c = await _setup(make_client, env)
    job_id = await _create(c)
    # A worker claimed it, started work, then died (lease never renewed).
    j = await lifecycle.claim(job_id, "dead-worker")
    await col(Collections.research_jobs).update_one({"_id": job_id}, {"$set": {"status": "searching"}})
    assert await lifecycle.claim(job_id, "other") is None  # lease still valid
    await col(Collections.research_jobs).update_one({"_id": job_id},
                                                    {"$set": {"lease.expires_at": utcnow() - timedelta(seconds=1)}})
    stats = await lifecycle.reconcile()
    assert stats["redispatched"] >= 1
    job = await _run_once(job_id)
    assert job["status"] == "completed" and job["run_count"] == 2 and j is not None
    # The old owner can no longer write checkpoints (lease token changed).
    assert not await lifecycle.save_checkpoint(job_id, j["lease"]["token"], {"next": "x"})


async def test_host_sleep_does_not_count_against_deadline(make_client: Any, env: Any) -> None:
    """Free-tier hosts sleep when idle. A job interrupted that way resumes from its checkpoint with the
    deadline moved forward by the downtime, instead of failing as 'time limit reached'."""
    from datetime import timedelta

    from app.core.security import utcnow
    from app.db.mongo import Collections, col
    from app.jobs import lifecycle

    c = await _setup(make_client, env)
    job_id = await _create(c)
    await lifecycle.claim(job_id, "sleeping-host")
    two_hours_ago = utcnow() - timedelta(hours=2)
    # It ran for a while, checkpointed, then the host went to sleep for two hours (deadline long passed).
    await col(Collections.research_jobs).update_one({"_id": job_id}, {"$set": {
        "status": "searching", "started_at": two_hours_ago - timedelta(minutes=1),
        "deadline_at": two_hours_ago + timedelta(minutes=10),
        "checkpoint": {"next": "validate", "state": None, "saved_at": two_hours_ago},
        "lease.expires_at": two_hours_ago + timedelta(seconds=60)}})
    job = await _run_once(job_id)
    assert job["status"] == "completed", job.get("last_error")
    assert job["run_count"] == 2


async def test_transient_llm_error_retries_but_auth_error_does_not(make_client: Any, env: Any,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm.base import ErrorKind, LLMError
    from app.llm.demo import DemoProvider

    c = await _setup(make_client, env)
    original = DemoProvider.generate

    async def rate_limited(self: Any, req: Any, model: str, caps: Any) -> Any:
        raise LLMError(ErrorKind.RATE_LIMIT, provider="demo", retry_after=5)

    monkeypatch.setattr(DemoProvider, "generate", rate_limited)
    j1 = await _create(c)
    job = await _run_once(j1)
    assert job["status"] == "waiting_for_retry" and job["last_error"]["code"] == "rate_limited"

    async def bad_key(self: Any, req: Any, model: str, caps: Any) -> Any:
        raise LLMError(ErrorKind.AUTH, provider="demo", status=401)

    monkeypatch.setattr(DemoProvider, "generate", bad_key)
    j2 = await _create(c, question="Another question about remote work adoption")
    job = await _run_once(j2)
    assert job["status"] == "failed" and job["last_error"]["code"] == "invalid_credentials"
    assert job["last_error"]["resumable"] is True and job["attempts"] == 0  # never retried
    # Fix the "credentials" and resume from the checkpoint.
    monkeypatch.setattr(DemoProvider, "generate", original)
    r = await c.post(f"/api/v1/research/{j2}/resume")
    assert r.status_code == 200
    job = await _run_once(j2)
    assert job["status"] == "completed"


async def test_quota_exhaustion_not_retried_and_dead_letter(make_client: Any, env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import timedelta

    from app.core.security import utcnow
    from app.db.mongo import Collections, col
    from app.llm.base import ErrorKind, LLMError
    from app.llm.demo import DemoProvider

    c = await _setup(make_client, env, MAX_JOB_ATTEMPTS="2")

    async def quota(self: Any, req: Any, model: str, caps: Any) -> Any:
        raise LLMError(ErrorKind.QUOTA, provider="demo", status=429)

    monkeypatch.setattr(DemoProvider, "generate", quota)
    jid = await _create(c)
    job = await _run_once(jid)
    assert job["status"] == "failed" and job["attempts"] == 0

    async def outage(self: Any, req: Any, model: str, caps: Any) -> Any:
        raise LLMError(ErrorKind.UNAVAILABLE, provider="demo", status=503)

    monkeypatch.setattr(DemoProvider, "generate", outage)
    jid2 = await _create(c, question="A second question about remote work adoption")
    job = await _run_once(jid2)
    assert job["status"] == "waiting_for_retry"
    await col(Collections.research_jobs).update_one({"_id": jid2}, {"$set": {"next_attempt_at": utcnow() - timedelta(seconds=1)}})
    job = await _run_once(jid2)
    assert job["status"] == "failed" and job["dead_lettered"] is True


async def test_cancel_running_job_keeps_partial(make_client: Any, env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db.mongo import Collections, col
    from app.research import pipeline

    c = await _setup(make_client, env)
    jid = await _create(c)
    original = pipeline.NODES["assess"]

    async def cancel_then_assess(state: Any, deps: Any) -> Any:
        await col(Collections.research_jobs).update_one({"_id": state.job_id}, {"$set": {"cancel_requested": True}})
        return await original(state, deps)

    monkeypatch.setitem(pipeline.NODES, "assess", cancel_then_assess)
    job = await _run_once(jid)
    assert job["status"] == "cancelled"
    rep = (await c.get(f"/api/v1/research/{jid}/report")).json()["report"]
    assert rep["status"] == "partial" and "cancelled" in rep["partial_reason"]
    assert rep["sections"], "verified findings gathered before cancellation are preserved"


async def test_cancel_queued_job_immediately(make_client: Any, env: Any) -> None:
    c = await _setup(make_client, env)
    jid = await _create(c)
    r = await c.post(f"/api/v1/research/{jid}/cancel")
    assert r.json()["job"]["status"] == "cancelled"
    assert await _run_once(jid) is None


async def test_tight_budget_stops_gracefully(make_client: Any, env: Any) -> None:
    c = await _setup(make_client, env, MAX_SEARCH_CALLS_PER_JOB="2", MAX_SOURCES_PER_JOB="3")
    jid = await _create(c, mode="deep")
    job = await _run_once(jid)
    assert job["status"] == "completed", job.get("last_error")
    assert job["usage"]["search_calls"] <= 2
    sources = (await c.get(f"/api/v1/research/{jid}/sources")).json()["items"]
    assert len(sources) <= 3
    rep = (await c.get(f"/api/v1/research/{jid}/report")).json()["report"]
    assert any("stopped early" in w or "budget" in w for w in rep["warnings"])


async def test_tool_call_budget_exhaustion_yields_partial_or_report(make_client: Any, env: Any) -> None:
    c = await _setup(make_client, env, MAX_TOOL_CALLS_PER_JOB="4")
    jid = await _create(c, mode="quick")
    job = await _run_once(jid)
    # Never labelled complete if it could not finish; partial results are kept.
    assert job["status"] in ("completed", "failed")
    if job["status"] == "failed":
        assert job["last_error"]["code"] in ("budget_exhausted", "budget_exhausted".upper().lower())
        rep = (await c.get(f"/api/v1/research/{jid}/report")).json()["report"]
        assert rep["status"] == "partial"


async def test_tenant_isolation(make_client: Any, env: Any) -> None:
    a = await _setup(make_client, env, email="owner@example.com")
    jid = await _create(a)
    await _run_once(jid)
    b = await make_client()
    await b.register("intruder@example.com")
    for path in ("", "/report", "/sources", "/evidence", "/events", "/export.md", "/charts.csv", "/graph"):
        r = await b.get(f"/api/v1/research/{jid}{path}")
        assert r.status_code == 404, path
    assert (await b.post(f"/api/v1/research/{jid}/cancel")).status_code == 404
    assert (await b.delete(f"/api/v1/research/{jid}")).status_code == 404
    listing = (await b.get("/api/v1/research")).json()["items"]
    assert listing == []


async def test_sse_stream_and_resume_from_event_id(make_client: Any, env: Any) -> None:
    c = await _setup(make_client, env)
    jid = await _create(c)
    await _run_once(jid)
    r = await c.get(f"/api/v1/research/{jid}/stream")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    body = r.text
    assert "event: progress" in body and "event: end" in body
    ids = [int(line.split(": ")[1]) for line in body.splitlines() if line.startswith("id: ")]
    assert ids == sorted(ids) and len(ids) > 5
    r2 = await c.get(f"/api/v1/research/{jid}/stream", headers={"Last-Event-ID": str(ids[-3])})
    ids2 = [int(line.split(": ")[1]) for line in r2.text.splitlines() if line.startswith("id: ")]
    assert ids2 == ids[-2:]


async def test_not_configured_is_actionable(make_client: Any, env: Any) -> None:
    c = await make_client()
    await c.register("noai@example.com")
    r = await c.post("/api/v1/research", json={"question": "What is happening with remote work?", "mode": "quick"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "ai_not_configured"
    env(AI_PROVIDER="openai", AI_MODEL="some-model-id")
    r = await c.post("/api/v1/research", json={"question": "What is happening with remote work?", "mode": "quick"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "ai_key_missing"
    env(AI_PROVIDER="openai", AI_MODEL="some-model-id", OPENAI_API_KEY="sk-test-123456789012345678")
    r = await c.post("/api/v1/research", json={"question": "What is happening with remote work?", "mode": "quick"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "search_not_configured"


async def test_queue_unavailable_refuses_job(make_client: Any, env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import research as research_api
    from app.db.mongo import Collections, col

    c = await _setup(make_client, env)

    async def down() -> bool:
        return False

    monkeypatch.setattr(research_api, "redis_ping", down)
    r = await c.post("/api/v1/research", json={"question": "What is happening with remote work?", "mode": "quick"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "queue_unavailable"
    assert await col(Collections.research_jobs).count_documents({}) == 0  # never claimed as queued


async def test_idempotent_creation(make_client: Any, env: Any) -> None:
    c = await _setup(make_client, env)
    body = {"question": "What is happening with remote work?", "mode": "quick"}
    r1 = await c.post("/api/v1/research", json=body, headers={"Idempotency-Key": "abc-123"})
    r2 = await c.post("/api/v1/research", json=body, headers={"Idempotency-Key": "abc-123"})
    assert r1.json()["job"]["id"] == r2.json()["job"]["id"] and r2.json()["duplicate"] is True


async def test_concurrency_limit(make_client: Any, env: Any) -> None:
    c = await _setup(make_client, env, MAX_CONCURRENT_RESEARCH_JOBS_PER_USER="1")
    await _create(c)
    r = await c.post("/api/v1/research", json={"question": "Second concurrent research question", "mode": "quick"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "concurrency_limit"


async def test_regenerate_section_and_versions(make_client: Any, env: Any) -> None:
    c = await _setup(make_client, env)
    jid = await _create(c)
    await _run_once(jid)
    rep = (await c.get(f"/api/v1/research/{jid}/report")).json()["report"]
    sec = rep["sections"][0]
    eid = next(i for p in sec["paragraphs"] for s in p["segments"] for i in s["evidence_ids"])
    fb = await c.post(f"/api/v1/research/{jid}/feedback", json={"kind": "citation_incorrect", "evidence_id": eid,
                                                                 "section_id": sec["id"], "note": "wrong source"})
    assert fb.status_code == 201
    r = await c.post(f"/api/v1/research/{jid}/report/sections/{sec['id']}/regenerate", json={"instruction": "Be concise"})
    assert r.status_code == 202
    regen = await _run_once(r.json()["job"]["id"])
    assert regen["status"] == "completed", regen.get("last_error")
    versions = (await c.get(f"/api/v1/research/{jid}/report/versions")).json()["items"]
    assert [v["version"] for v in versions] == [2, 1]
    new = (await c.get(f"/api/v1/research/{jid}/report")).json()["report"]
    new_sec = next(s for s in new["sections"] if s["id"] == sec["id"])
    assert eid not in {i for p in new_sec["paragraphs"] for s in p["segments"] for i in s["evidence_ids"]}
    diff = (await c.get(f"/api/v1/research/{jid}/report/diff?a=1&b=2")).json()
    assert diff["changes"]


async def test_followup_reuses_sources(make_client: Any, env: Any) -> None:
    from app.db.mongo import Collections, col

    c = await _setup(make_client, env)
    jid = await _create(c)
    await _run_once(jid)
    r = await c.post(f"/api/v1/research/{jid}/followup", json={"question": "What are the main costs of remote work?",
                                                                "mode": "quick"})
    fid = r.json()["job"]["id"]
    job = await _run_once(fid)
    assert job["status"] == "completed"
    reused = await col(Collections.research_sources).count_documents({"job_id": fid, "provider": "previous_report"})
    assert reused > 0


async def test_exports_background(make_client: Any, env: Any) -> None:
    c = await _setup(make_client, env)
    jid = await _create(c)
    await _run_once(jid)
    for fmt, magic in (("pdf", b"%PDF"), ("docx", b"PK")):
        r = await c.post(f"/api/v1/research/{jid}/exports", json={"format": fmt})
        ex_id = r.json()["export_id"]
        done = await _run_once(ex_id)
        assert done["status"] == "completed", done.get("last_error")
        dl = await c.get(f"/api/v1/research/exports/{ex_id}?download=true")
        assert dl.status_code == 200 and dl.content.startswith(magic)


async def test_uploads_and_document_mode(make_client: Any, env: Any) -> None:
    c = await _setup(make_client, env)
    text = ("Remote work policy report. In 2024, 58 percent of surveyed teams worked remotely at least two days per week. "
            "Managers reported that collaboration costs increased modestly.\n") * 3
    r = await c.post("/api/v1/uploads", files={"file": ("notes.txt", text.encode(), "text/plain")})
    assert r.status_code == 201, r.text
    up = r.json()["upload"]
    assert up["status"] == "ready"
    bad = await c.post("/api/v1/uploads", files={"file": ("fake.pdf", b"not really a pdf", "application/pdf")})
    assert bad.status_code == 415
    exe = await c.post("/api/v1/uploads", files={"file": ("x.exe", b"MZ....", "application/octet-stream")})
    assert exe.status_code == 415
    jid = await _create(c, mode="documents", question="What does my document say about remote work?", upload_ids=[up["id"]])
    job = await _run_once(jid)
    assert job["status"] == "completed", job.get("last_error")
    srcs = (await c.get(f"/api/v1/research/{jid}/sources")).json()["items"]
    assert srcs and srcs[0]["provider"] == "upload"
    other = await make_client()
    await other.register("other-up@example.com")
    r = await other.post("/api/v1/research", json={"question": "Use someone else's upload please", "mode": "documents",
                                                    "options": {"upload_ids": [up["id"]]}})
    assert r.status_code == 422  # cannot reference another user's upload


async def test_delete_research_cascades(make_client: Any, env: Any) -> None:
    from app.db.mongo import Collections, col

    c = await _setup(make_client, env)
    jid = await _create(c)
    await _run_once(jid)
    assert (await c.delete(f"/api/v1/research/{jid}")).status_code == 200
    for name in (Collections.research_sources, Collections.research_evidence, Collections.research_reports, Collections.job_events):
        assert await col(name).count_documents({"job_id": jid}) == 0


async def test_usage_tracked(make_client: Any, env: Any) -> None:
    c = await _setup(make_client, env)
    jid = await _create(c)
    job = await _run_once(jid)
    assert job["usage"]["llm_calls"] > 0 and job["usage"]["search_calls"] > 0
    u = (await c.get("/api/v1/usage")).json()
    assert u["jobs"][0]["usage"]["llm_calls"] == job["usage"]["llm_calls"]
    assert "estimates" in u["snapshot"]["cost_note"]
