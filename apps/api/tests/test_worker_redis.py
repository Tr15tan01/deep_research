"""Worker loop against a real redis-server binary (queue delivery, pub/sub, graceful shutdown).
Skipped when redis-server is not installed."""

from __future__ import annotations

import asyncio
import shutil
import socket
import subprocess
from collections.abc import AsyncIterator
from typing import Any

import pytest

pytestmark = [pytest.mark.redis, pytest.mark.skipif(shutil.which("redis-server") is None, reason="redis-server not installed")]


@pytest.fixture
async def real_redis(infra: Any) -> AsyncIterator[Any]:
    import redis.asyncio as aioredis

    from app.db import redis as redis_mod

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(["redis-server", "--port", str(port), "--save", "", "--appendonly", "no"],  # noqa: S603,S607
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = aioredis.from_url(f"redis://127.0.0.1:{port}/0", decode_responses=True)
    for _ in range(50):
        try:
            await client.ping()
            break
        except Exception:  # noqa: BLE001
            await asyncio.sleep(0.1)
    redis_mod.use_redis(client)
    yield client
    await client.aclose()
    proc.terminate()
    proc.wait(timeout=5)


async def test_worker_consumes_from_real_queue(make_client: Any, env: Any, real_redis: Any) -> None:
    from app.db.mongo import Collections, col
    from app.jobs.worker import Worker

    env(DEMO_MODE="1", WORKER_POLL_SECONDS="1")
    c = await make_client()
    await c.register("rq@example.com")
    r = await c.post("/api/v1/research", json={"question": "How common is remote work in 2024?", "mode": "quick"})
    jid = r.json()["job"]["id"]
    assert await real_redis.llen("dr:queue:jobs") == 1
    worker = Worker(concurrency=1, worker_id="w-real")
    task = asyncio.create_task(worker.run(install_signals=False))
    for _ in range(200):
        job = await col(Collections.research_jobs).find_one({"_id": jid})
        if job["status"] in ("completed", "failed"):
            break
        await asyncio.sleep(0.1)
    worker.stopping.set()
    await asyncio.wait_for(task, timeout=30)
    assert job["status"] == "completed", job.get("last_error")
    assert job["lease"] is None
    assert await real_redis.exists("dr:workers:w-real") in (0, 1)


async def test_lost_delivery_is_reconciled(make_client: Any, env: Any, real_redis: Any) -> None:
    from app.db.mongo import Collections, col
    from app.jobs.worker import Worker

    env(DEMO_MODE="1", WORKER_POLL_SECONDS="1")
    c = await make_client()
    await c.register("rq2@example.com")
    jid = (await c.post("/api/v1/research", json={"question": "How common is remote work in 2023?", "mode": "quick"})).json()["job"]["id"]
    await real_redis.delete("dr:queue:jobs")  # simulate a lost Redis delivery
    worker = Worker(concurrency=1, worker_id="w-rec")
    task = asyncio.create_task(worker.run(install_signals=False))
    for _ in range(300):
        job = await col(Collections.research_jobs).find_one({"_id": jid})
        if job["status"] == "completed":
            break
        await asyncio.sleep(0.1)
    worker.stopping.set()
    await asyncio.wait_for(task, timeout=30)
    assert job["status"] == "completed"
