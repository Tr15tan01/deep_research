"""Deep Research background worker process.

The research engine lives in the shared ``app`` package (apps/api) so the API and worker
use identical job, pipeline and provider code. This process only runs the job consumer:

    python -m deep_research_worker                    # run with WORKER_CONCURRENCY slots
    python -m deep_research_worker --concurrency 4    # override slot count
    python -m deep_research_worker --healthcheck      # exit 0 if the worker loop is alive

Shutdown: SIGTERM/SIGINT stop new claims, give in-flight jobs time to reach a checkpoint,
then release their leases so another worker resumes them (rolling deploys are safe).
"""

from __future__ import annotations

import argparse
import asyncio
import sys


def _parse(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="deep_research_worker", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--concurrency", type=int, default=None, help="parallel job slots (default WORKER_CONCURRENCY)")
    p.add_argument("--worker-id", default=None, help="stable worker identity (default host-pid)")
    p.add_argument("--healthcheck", action="store_true", help="check liveness file freshness and exit")
    return p.parse_args(argv)


async def _run(args: argparse.Namespace) -> None:
    from app.core.config import get_settings
    from app.core.logging import configure_logging, get_logger
    from app.db.mongo import connect, ensure_indexes
    from app.db.redis import connect_redis
    from app.jobs.worker import Worker, touch_health_file

    s = get_settings()
    configure_logging(s.LOG_LEVEL, s.log_json)
    log = get_logger("worker")
    from app.core.tracking import init_tracking

    init_tracking("worker")
    for w in s.config_warnings:
        log.warning("config_warning", message=w)
    if s.uses_memory_db:
        log.warning("memory_db_worker",
                    note="MONGODB_URI=mongomock:// is per-process; a separate worker cannot see API jobs. "
                         "Use EMBEDDED_WORKER=1 for in-memory development or point both at MongoDB.")
    if s.uses_memory_redis:
        raise SystemExit("REDIS_URL=memory:// is per-process; a separate worker cannot see the API's queue. "
                         "Use EMBEDDED_WORKER=1 on the API instead, or point both at a real Redis.")
    await connect()
    await ensure_indexes()
    await connect_redis()
    touch_health_file(s.WORKER_HEALTH_FILE)
    await Worker(concurrency=args.concurrency, worker_id=args.worker_id).run()


def main(argv: list[str] | None = None) -> int:
    args = _parse(sys.argv[1:] if argv is None else argv)
    if args.healthcheck:
        from app.core.config import get_settings
        from app.jobs.worker import health_check

        s = get_settings()
        # The reconciler touches the file every max(5, 3*poll) seconds; allow generous slack.
        ok = health_check(s.WORKER_HEALTH_FILE, max(60.0, s.WORKER_POLL_SECONDS * 12))
        print("alive" if ok else "stale")
        return 0 if ok else 1
    asyncio.run(_run(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
