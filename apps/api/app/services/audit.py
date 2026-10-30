"""Append-only audit trail for security-sensitive actions."""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger, redact
from app.core.security import utcnow
from app.db.mongo import Collections, col, new_id

log = get_logger("audit")


async def audit(action: str, *, actor_id: str | None, target_id: str | None = None, ip: str | None = None,
                outcome: str = "success", metadata: dict[str, Any] | None = None) -> None:
    if not get_settings().AUDIT_LOG_ENABLED:
        return
    doc = {
        "_id": new_id("aud"),
        "action": action,
        "actor_id": actor_id,
        "target_id": target_id,
        "ip": ip,
        "outcome": outcome,
        "metadata": redact(metadata or {}),
        "created_at": utcnow(),
    }
    try:
        await col(Collections.audit_logs).insert_one(doc)
    except Exception as e:  # noqa: BLE001 — auditing must never break the primary action
        log.error("audit_write_failed", action=action, error=type(e).__name__)
