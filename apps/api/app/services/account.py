"""Account data export and deletion (GDPR-style), plus per-job cascade deletion."""

from __future__ import annotations

import contextlib
import os
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.mongo import Collections, col

log = get_logger("account")


async def delete_job_data(job_id: str, user_id: str) -> None:
    sources = await col(Collections.research_sources).find({"job_id": job_id, "user_id": user_id}, {"_id": 1}).to_list(None)
    ids = [s["_id"] for s in sources]
    if ids:
        await col(Collections.source_contents).delete_many({"source_id": {"$in": ids}})
    for name in (Collections.research_sources, Collections.research_evidence, Collections.research_reports,
                 Collections.job_events, Collections.feedback):
        await col(name).delete_many({"job_id": job_id})
    await col(Collections.agent_runs).delete_many({"job_id": job_id})
    await col(Collections.library_items).delete_many({"user_id": user_id, "ref_id": job_id})
    # Child jobs (exports/regenerations) of this research.
    children = await col(Collections.research_jobs).find({"user_id": user_id, "options.parent_job_id": job_id,
                                                          "kind": {"$in": ["export", "regenerate_section"]}}, {"_id": 1}).to_list(None)
    for c in children:
        await col(Collections.exports).delete_many({"_id": c["_id"]})
        await col(Collections.job_events).delete_many({"job_id": c["_id"]})
    await col(Collections.research_jobs).delete_many({"_id": {"$in": [c["_id"] for c in children]}})
    await col(Collections.research_jobs).delete_one({"_id": job_id, "user_id": user_id})


async def delete_upload_files(upload: dict[str, Any]) -> None:
    path = upload.get("storage_path")
    if path:
        root = os.path.realpath(get_settings().UPLOAD_DIR)
        real = os.path.realpath(path)
        if real.startswith(root + os.sep):
            with contextlib.suppress(FileNotFoundError):
                os.remove(real)


async def export_user_data(user_id: str) -> dict[str, Any]:
    def clean(doc: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in doc.items() if k not in ("password_hash", "refresh_hash", "prev_refresh_hash", "token_hash",
                                                           "ciphertext", "checkpoint", "lease", "share_token_hash", "data")}

    user = await col(Collections.users).find_one({"_id": user_id})
    out: dict[str, Any] = {"user": clean(user or {})}
    for name in (Collections.research_jobs, Collections.research_reports, Collections.research_sources,
                 Collections.research_evidence, Collections.research_templates, Collections.usage_records,
                 Collections.notifications, Collections.library_collections, Collections.library_items,
                 Collections.feedback, Collections.uploads, Collections.subscriptions):
        docs = await col(name).find({"user_id": user_id}).limit(5000).to_list(None)
        out[name] = [clean(d) for d in docs]
    sessions = await col(Collections.sessions).find({"user_id": user_id}).to_list(None)
    out["sessions"] = [clean(s) for s in sessions]
    out["audit_logs"] = [clean(a) for a in await col(Collections.audit_logs).find({"actor_id": user_id}).limit(2000).to_list(None)]
    return out


async def delete_account(user_id: str) -> None:
    jobs = await col(Collections.research_jobs).find({"user_id": user_id}, {"_id": 1}).to_list(None)
    await col(Collections.research_jobs).update_many({"user_id": user_id}, {"$set": {"cancel_requested": True}})
    for j in jobs:
        await delete_job_data(j["_id"], user_id)
    for up in await col(Collections.uploads).find({"user_id": user_id}).to_list(None):
        await delete_upload_files(up)
    await col(Collections.upload_chunks).delete_many({"user_id": user_id})
    for name in (Collections.uploads, Collections.research_templates, Collections.usage_records, Collections.notifications,
                 Collections.library_collections, Collections.library_items, Collections.user_api_credentials,
                 Collections.sessions, Collections.verification_tokens, Collections.password_reset_tokens,
                 Collections.exports, Collections.feedback, Collections.subscriptions):
        await col(name).delete_many({"user_id": user_id})
    # Audit logs keep the (now meaningless) user ID for security accountability, without personal data.
    await col(Collections.users).delete_one({"_id": user_id})
