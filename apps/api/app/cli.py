"""Operational CLI.

    python -m app.cli init-db                 # create indexes and schema validators
    python -m app.cli create-admin EMAIL      # promote an existing account to ADMIN
    python -m app.cli reconcile               # re-dispatch runnable jobs to the queue
    python -m app.cli purge-uploads           # delete uploads past their retention date
"""

from __future__ import annotations

import asyncio
import sys

from app.core.config import get_settings
from app.core.logging import configure_logging


async def _main(argv: list[str]) -> int:
    from app.db.mongo import Collections, col, connect, ensure_indexes
    from app.db.redis import connect_redis

    s = get_settings()
    configure_logging(s.LOG_LEVEL, s.log_json)
    if not argv:
        print(__doc__)
        return 2
    await connect()
    cmd = argv[0]
    if cmd == "init-db":
        await ensure_indexes()
        print("indexes and validators ensured")
    elif cmd == "create-admin" and len(argv) == 2:
        res = await col(Collections.users).update_one({"email": argv[1].strip().lower()}, {"$set": {"role": "ADMIN"}})
        print("promoted" if res.matched_count else "no such user — register first")
        return 0 if res.matched_count else 1
    elif cmd == "reconcile":
        await connect_redis()
        from app.jobs.lifecycle import reconcile

        print(await reconcile())
    elif cmd == "purge-uploads":
        from app.api.uploads import purge_expired_uploads

        print(f"purged {await purge_expired_uploads()} uploads")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
