"""The standalone worker package (apps/worker) and its container health check."""

from __future__ import annotations

import os
import time
from pathlib import Path

from app.jobs.worker import health_check, touch_health_file
from app.search.demo import _slug, topic_from


def test_health_file_freshness(tmp_path: Path) -> None:
    f = tmp_path / "alive"
    assert not health_check(str(f), 60)  # missing file = unhealthy
    touch_health_file(str(f))
    assert health_check(str(f), 60)
    old = time.time() - 600
    os.utime(f, (old, old))
    assert not health_check(str(f), 60)


def test_worker_cli_healthcheck(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.core.config import reset_settings_cache
    from deep_research_worker.__main__ import main

    f = tmp_path / "alive"
    monkeypatch.setenv("WORKER_HEALTH_FILE", str(f))
    reset_settings_cache()
    try:
        assert main(["--healthcheck"]) == 1
        touch_health_file(str(f))
        assert main(["--healthcheck"]) == 0
    finally:
        reset_settings_cache()


def test_demo_text_never_cut_mid_word() -> None:
    q = "Compare PostgreSQL and MongoDB for a multi-tenant SaaS analytics workload in regulated industries today"
    t = topic_from(q)
    assert q.replace("Compare ", "").startswith(t) and len(t) <= 80
    assert q.replace("Compare ", "")[len(t):][:1] in ("", " ")
    s = _slug(q + " definition")
    assert len(s) <= 70 and not s.endswith("-") and (q.lower().replace(" ", "-") + "-definition").startswith(s)
