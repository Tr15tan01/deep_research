"""MongoDB connection management, collection registry, indexes and schema validation.

Production uses PyMongo's official asyncio driver (``AsyncMongoClient``). Tests and the
explicitly non-durable development mode (``MONGODB_URI=mongomock://``) use an in-memory
mock with the same async surface.
"""

from __future__ import annotations

import asyncio
import inspect
import secrets
from typing import Any

from pymongo import ASCENDING, DESCENDING, IndexModel

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("db")

_client: Any = None
_db: Any = None

_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"  # Crockford-ish base32, unambiguous


def new_id(prefix: str) -> str:
    return f"{prefix}_" + "".join(secrets.choice(_ALPHABET) for _ in range(20))


class Collections:
    users = "users"
    sessions = "sessions"
    verification_tokens = "verification_tokens"
    password_reset_tokens = "password_reset_tokens"
    oauth_states = "oauth_states"
    research_jobs = "research_jobs"
    job_events = "job_events"
    research_sources = "research_sources"
    source_contents = "source_contents"
    research_evidence = "research_evidence"
    research_reports = "research_reports"
    agent_runs = "agent_runs"
    research_templates = "research_templates"
    usage_records = "usage_records"
    subscriptions = "subscriptions"
    billing_events = "billing_events"
    audit_logs = "audit_logs"
    notifications = "notifications"
    user_api_credentials = "user_api_credentials"
    app_settings = "app_settings"
    uploads = "uploads"
    upload_chunks = "upload_chunks"
    library_collections = "library_collections"
    library_items = "library_items"
    feedback = "feedback"
    exports = "exports"


INDEXES: dict[str, list[IndexModel]] = {
    Collections.users: [
        IndexModel([("email", ASCENDING)], unique=True, name="email_unique"),
        IndexModel([("google_sub", ASCENDING)], unique=True, name="google_sub_unique",
                   partialFilterExpression={"google_sub": {"$type": "string"}}),
        IndexModel([("created_at", DESCENDING)], name="created_desc"),
    ],
    Collections.sessions: [
        IndexModel([("refresh_hash", ASCENDING)], unique=True, name="refresh_hash_unique"),
        IndexModel([("prev_refresh_hash", ASCENDING)], name="prev_refresh_hash"),
        IndexModel([("user_id", ASCENDING), ("revoked_at", ASCENDING)], name="user_active"),
        IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl"),
    ],
    Collections.verification_tokens: [
        IndexModel([("token_hash", ASCENDING)], unique=True, name="token_unique"),
        IndexModel([("user_id", ASCENDING)], name="user"),
        IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl"),
    ],
    Collections.password_reset_tokens: [
        IndexModel([("token_hash", ASCENDING)], unique=True, name="token_unique"),
        IndexModel([("user_id", ASCENDING)], name="user"),
        IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl"),
    ],
    Collections.oauth_states: [
        IndexModel([("jti", ASCENDING)], unique=True, name="jti_unique"),
        IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl"),
    ],
    Collections.research_jobs: [
        IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_created"),
        IndexModel([("status", ASCENDING), ("next_attempt_at", ASCENDING)], name="status_next"),
        IndexModel([("lease.expires_at", ASCENDING)], name="lease_exp"),
        IndexModel([("user_id", ASCENDING), ("idempotency_key", ASCENDING)], unique=True, name="idem_unique",
                   partialFilterExpression={"idempotency_key": {"$type": "string"}}),
    ],
    Collections.job_events: [
        IndexModel([("job_id", ASCENDING), ("seq", ASCENDING)], unique=True, name="job_seq"),
    ],
    Collections.research_sources: [
        IndexModel([("job_id", ASCENDING), ("number", ASCENDING)], unique=True, name="job_number"),
        IndexModel([("job_id", ASCENDING), ("canonical_url", ASCENDING)], name="job_canonical"),
        IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_created"),
    ],
    Collections.source_contents: [IndexModel([("source_id", ASCENDING)], unique=True, name="source_unique")],
    Collections.research_evidence: [
        IndexModel([("job_id", ASCENDING), ("source_id", ASCENDING)], name="job_source"),
        IndexModel([("job_id", ASCENDING), ("subquestion_id", ASCENDING)], name="job_subq"),
    ],
    Collections.research_reports: [
        IndexModel([("job_id", ASCENDING), ("version", DESCENDING)], unique=True, name="job_version"),
        IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_created"),
        IndexModel([("share_token_hash", ASCENDING)], unique=True, name="share_unique",
                   partialFilterExpression={"share_token_hash": {"$type": "string"}}),
    ],
    Collections.agent_runs: [IndexModel([("job_id", ASCENDING), ("attempt", ASCENDING)], name="job_attempt")],
    Collections.research_templates: [IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_created")],
    Collections.usage_records: [
        IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_created"),
        IndexModel([("job_id", ASCENDING)], name="job"),
        IndexModel([("created_at", DESCENDING)], name="created"),
    ],
    Collections.subscriptions: [
        IndexModel([("user_id", ASCENDING)], unique=True, name="user_unique"),
        IndexModel([("provider_subscription_id", ASCENDING)], name="provider_sub"),
    ],
    Collections.billing_events: [IndexModel([("event_id", ASCENDING)], unique=True, name="event_unique")],
    Collections.audit_logs: [
        IndexModel([("created_at", DESCENDING)], name="created"),
        IndexModel([("actor_id", ASCENDING), ("created_at", DESCENDING)], name="actor"),
    ],
    Collections.notifications: [IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_created")],
    Collections.user_api_credentials: [
        IndexModel([("user_id", ASCENDING), ("provider", ASCENDING)], unique=True, name="user_provider"),
    ],
    Collections.uploads: [
        IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_created"),
        IndexModel([("expires_at", ASCENDING)], name="expires"),
    ],
    Collections.upload_chunks: [IndexModel([("upload_id", ASCENDING), ("index", ASCENDING)], name="upload_idx")],
    Collections.library_collections: [IndexModel([("user_id", ASCENDING), ("name", ASCENDING)], name="user_name")],
    Collections.library_items: [
        IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_created"),
        IndexModel([("user_id", ASCENDING), ("kind", ASCENDING), ("ref_id", ASCENDING)], unique=True, name="user_ref"),
    ],
    Collections.feedback: [IndexModel([("job_id", ASCENDING), ("created_at", DESCENDING)], name="job_created")],
    Collections.exports: [
        IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_created"),
        IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl"),
    ],
}

# JSON-schema validators for the core collections (applied on real MongoDB only).
VALIDATORS: dict[str, dict[str, Any]] = {
    Collections.users: {
        "bsonType": "object",
        "required": ["_id", "email", "role", "created_at"],
        "properties": {
            "email": {"bsonType": "string", "maxLength": 320},
            "role": {"enum": ["USER", "ADMIN", "CONTENT_MANAGER"]},
            "password_hash": {"bsonType": ["string", "null"]},
            "email_verified": {"bsonType": "bool"},
        },
    },
    Collections.research_jobs: {
        "bsonType": "object",
        "required": ["_id", "user_id", "status", "question", "mode", "created_at"],
        "properties": {
            "status": {"enum": ["queued", "planning", "awaiting_approval", "searching", "extracting", "verifying",
                                "synthesizing", "completed", "failed", "cancelled", "waiting_for_retry"]},
            "question": {"bsonType": "string", "maxLength": 4000},
            "user_id": {"bsonType": "string"},
        },
    },
    Collections.research_sources: {
        "bsonType": "object",
        "required": ["_id", "job_id", "user_id", "number", "url", "status"],
        "properties": {"status": {"enum": ["candidate", "extracted", "inaccessible", "rejected"]}},
    },
}


def get_db() -> Any:
    if _db is None:
        raise RuntimeError("database not initialised")
    return _db


def col(name: str) -> Any:
    return get_db()[name]


async def connect(uri: str | None = None, database: str | None = None) -> Any:
    global _client, _db
    settings = get_settings()
    uri = uri if uri is not None else settings.MONGODB_URI
    database = database or settings.MONGODB_DATABASE
    if not uri:
        raise RuntimeError("MONGODB_URI is not configured")
    if uri.startswith("mongomock://"):
        from mongomock_motor import AsyncMongoMockClient  # dev/test only dependency

        if settings.is_production:
            raise RuntimeError("mongomock is not allowed in production")
        _client = AsyncMongoMockClient(tz_aware=False)
        log.warning("using_in_memory_database", note="NOT DURABLE — development/test only")
    else:
        from pymongo import AsyncMongoClient

        _client = AsyncMongoClient(
            uri,
            appname=settings.APP_NAME,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            retryWrites=True,
            retryReads=True,
            tz_aware=False,
            uuidRepresentation="standard",
        )
    _db = _client[database]
    return _db


def use_database(db: Any) -> None:
    """Inject a database (tests)."""
    global _db
    _db = db


async def close() -> None:
    global _client, _db
    if _client is not None:
        res = _client.close()
        if inspect.isawaitable(res):
            await res
    _client = None
    _db = None


async def ping() -> bool:
    try:
        res = get_db().command("ping")
        if inspect.isawaitable(res):
            res = await res
        return bool(res.get("ok", 0))
    except Exception:  # noqa: BLE001
        return False


async def aggregate(collection: Any, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run an aggregation regardless of driver flavour (pymongo async vs motor-style)."""
    cursor = collection.aggregate(pipeline)
    if inspect.isawaitable(cursor):
        cursor = await cursor
    return await cursor.to_list(None)


async def ensure_indexes() -> None:
    db = get_db()
    settings = get_settings()
    for name, models in INDEXES.items():
        if settings.uses_memory_db:
            # mongomock ignores partialFilterExpression, so partial *unique* indexes would reject
            # documents real MongoDB accepts. Emulate them as plain indexes in memory mode only.
            models = [IndexModel(list(m.document["key"].items()), name=m.document["name"],
                                 **{k: v for k, v in m.document.items() if k in ("expireAfterSeconds",)},
                                 unique=bool(m.document.get("unique")) and "partialFilterExpression" not in m.document)
                      for m in models]
        try:
            await db[name].create_indexes(models)
        except Exception as e:  # noqa: BLE001
            log.error("index_creation_failed", collection=name, error=str(e))
            raise
    if not settings.uses_memory_db:
        existing = set(await db.list_collection_names())
        for name, schema in VALIDATORS.items():
            try:
                if name not in existing:
                    await db.create_collection(name)
                await db.command({"collMod": name, "validator": {"$jsonSchema": schema},
                                  "validationLevel": "moderate", "validationAction": "error"})
            except Exception as e:  # noqa: BLE001
                # Some Atlas tiers restrict collMod; validation is defence-in-depth (Pydantic is primary).
                log.warning("schema_validator_not_applied", collection=name, error=str(e))


async def with_retry(fn: Any, *args: Any, attempts: int = 3, base_delay: float = 0.2, **kwargs: Any) -> Any:
    """Bounded retry for transient connection errors (never retries logical errors)."""
    from pymongo.errors import AutoReconnect, ConnectionFailure, NetworkTimeout

    last: Exception | None = None
    for i in range(attempts):
        try:
            return await fn(*args, **kwargs)
        except (AutoReconnect, ConnectionFailure, NetworkTimeout) as e:
            last = e
            await asyncio.sleep(base_delay * (2**i))
    assert last is not None
    raise last
