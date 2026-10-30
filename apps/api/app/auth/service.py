"""Authentication domain logic: users, sessions with rotating refresh tokens, email
verification and password reset."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.config import get_settings
from app.core.errors import AppError, Conflict, Forbidden, NotAuthenticated
from app.core.security import (
    as_utc,
    create_access_token,
    hash_password,
    hash_token,
    new_token,
    password_needs_rehash,
    utcnow,
    verify_password,
)
from app.db.mongo import Collections, col, new_id

ROLES = ("USER", "ADMIN", "CONTENT_MANAGER")
REFRESH_REUSE_GRACE_SECONDS = 30
VERIFY_TTL = timedelta(hours=24)
RESET_TTL = timedelta(minutes=30)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_password_strength(password: str, email: str = "") -> None:
    problems = []
    if len(password) < 10:
        problems.append("at least 10 characters")
    if len(password) > 256:
        problems.append("at most 256 characters")
    classes = sum(bool(re.search(p, password)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    if classes < 3:
        problems.append("at least three of: lowercase, uppercase, digit, symbol")
    if email and email.split("@")[0].lower() in password.lower() and len(email.split("@")[0]) >= 4:
        problems.append("not contain your email name")
    if problems:
        raise AppError("Password must have " + "; ".join(problems) + ".", code="weak_password", status_code=422)


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["_id"],
        "email": user["email"],
        "name": user.get("name") or "",
        "role": user.get("role", "USER"),
        "email_verified": bool(user.get("email_verified")),
        "has_password": bool(user.get("password_hash")),
        "google_linked": bool(user.get("google_sub")),
        "created_at": user.get("created_at"),
        "plan": user.get("plan", "free"),
        "preferences": user.get("preferences", {}),
    }


# --- Users ---------------------------------------------------------------------------------

async def get_user(user_id: str) -> dict[str, Any] | None:
    return await col(Collections.users).find_one({"_id": user_id})


async def get_user_by_email(email: str) -> dict[str, Any] | None:
    return await col(Collections.users).find_one({"email": normalize_email(email)})


def _bootstrap_trusted(verified: bool) -> bool:
    """Bootstrap admins must have a verified email. The only exception is the explicitly
    non-durable in-memory development mode, which has no mail delivery."""
    s = get_settings()
    return verified or (not s.is_production and s.uses_memory_db)


def _initial_role(email: str, verified: bool) -> str:
    return "ADMIN" if _bootstrap_trusted(verified) and normalize_email(email) in get_settings().admin_bootstrap_emails else "USER"


async def create_user(email: str, password: str | None, name: str, *, email_verified: bool = False,
                      google_sub: str | None = None) -> dict[str, Any]:
    email = normalize_email(email)
    if not _EMAIL_RE.match(email) or len(email) > 320:
        raise AppError("Enter a valid email address.", code="invalid_email", status_code=422)
    now = utcnow()
    doc = {
        "_id": new_id("usr"),
        "email": email,
        "name": name.strip()[:120],
        "password_hash": hash_password(password) if password else None,
        "email_verified": email_verified,
        "role": _initial_role(email, email_verified),
        "status": "active",
        "plan": "free",
        "preferences": {},
        "created_at": now,
        "updated_at": now,
        "last_login_at": None,
        "password_changed_at": now if password else None,
    }
    if google_sub:
        doc["google_sub"] = google_sub
    try:
        await col(Collections.users).insert_one(doc)
    except DuplicateKeyError as e:
        raise Conflict("An account with this email already exists.", code="email_taken") from e
    return doc


async def maybe_promote_bootstrap_admin(user: dict[str, Any]) -> dict[str, Any]:
    if _bootstrap_trusted(bool(user.get("email_verified"))) and user.get("role") == "USER" and user["email"] in get_settings().admin_bootstrap_emails:
        await col(Collections.users).update_one({"_id": user["_id"]}, {"$set": {"role": "ADMIN", "updated_at": utcnow()}})
        user = {**user, "role": "ADMIN"}
    return user


async def authenticate(email: str, password: str) -> dict[str, Any]:
    user = await get_user_by_email(email)
    ok = verify_password(password, user.get("password_hash") if user else None)
    if not user or not ok:
        raise NotAuthenticated("Invalid email or password.", code="invalid_credentials")
    if user.get("status") != "active":
        raise Forbidden("This account is disabled. Contact support if you think this is a mistake.", code="account_disabled")
    if password_needs_rehash(user["password_hash"]):
        await col(Collections.users).update_one({"_id": user["_id"]}, {"$set": {"password_hash": hash_password(password)}})
    return user


# --- Sessions ------------------------------------------------------------------------------

@dataclass
class IssuedSession:
    session_id: str
    access_token: str
    refresh_token: str | None
    user: dict[str, Any]


async def create_session(user: dict[str, Any], *, ip: str | None, user_agent: str | None, method: str) -> IssuedSession:
    settings = get_settings()
    now = utcnow()
    refresh = new_token(32)
    sid = new_id("ses")
    await col(Collections.sessions).insert_one({
        "_id": sid,
        "user_id": user["_id"],
        "refresh_hash": hash_token(refresh),
        "prev_refresh_hash": None,
        "rotated_at": None,
        "created_at": now,
        "last_used_at": now,
        "expires_at": now + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS),
        "revoked_at": None,
        "ip": ip,
        "user_agent": (user_agent or "")[:300],
        "method": method,
    })
    await col(Collections.users).update_one({"_id": user["_id"]}, {"$set": {"last_login_at": now}})
    access = create_access_token(user_id=user["_id"], session_id=sid, role=user.get("role", "USER"))
    return IssuedSession(sid, access, refresh, user)


async def rotate_refresh(refresh_token: str, *, ip: str | None) -> IssuedSession:
    """Rotate a refresh token. Reuse of an already-rotated token revokes the session
    (token theft signal), except within a short grace window to tolerate concurrent tabs."""
    now = utcnow()
    h = hash_token(refresh_token)
    sessions = col(Collections.sessions)
    new_refresh = new_token(32)
    session = await sessions.find_one_and_update(
        {"refresh_hash": h, "revoked_at": None},
        {"$set": {"refresh_hash": hash_token(new_refresh), "prev_refresh_hash": h, "rotated_at": now,
                  "last_used_at": now, "ip": ip}},
        return_document=ReturnDocument.AFTER,
    )
    if session is None:
        reused = await sessions.find_one({"prev_refresh_hash": h})
        if reused is None:
            raise NotAuthenticated("Your session has expired. Please sign in again.", code="session_expired")
        rotated_at = as_utc(reused.get("rotated_at"))
        if reused.get("revoked_at") is None and rotated_at and (now - rotated_at).total_seconds() <= REFRESH_REUSE_GRACE_SECONDS:
            user = await get_user(reused["user_id"])
            if not user or user.get("status") != "active":
                raise NotAuthenticated(code="session_expired")
            access = create_access_token(user_id=user["_id"], session_id=reused["_id"], role=user.get("role", "USER"))
            return IssuedSession(reused["_id"], access, None, user)
        await sessions.update_one({"_id": reused["_id"]}, {"$set": {"revoked_at": now, "revoked_reason": "refresh_reuse"}})
        from app.services.audit import audit

        await audit("session.refresh_reuse_detected", actor_id=reused["user_id"], target_id=reused["_id"], ip=ip,
                    outcome="blocked")
        raise NotAuthenticated("Your session was signed out for security reasons. Please sign in again.",
                               code="session_revoked")
    if as_utc(session["expires_at"]) <= now:
        await sessions.update_one({"_id": session["_id"]}, {"$set": {"revoked_at": now, "revoked_reason": "expired"}})
        raise NotAuthenticated("Your session has expired. Please sign in again.", code="session_expired")
    user = await get_user(session["user_id"])
    if not user or user.get("status") != "active":
        await sessions.update_one({"_id": session["_id"]}, {"$set": {"revoked_at": now, "revoked_reason": "user_inactive"}})
        raise NotAuthenticated(code="session_expired")
    access = create_access_token(user_id=user["_id"], session_id=session["_id"], role=user.get("role", "USER"))
    return IssuedSession(session["_id"], access, new_refresh, user)


async def revoke_session(session_id: str, user_id: str, reason: str = "logout") -> bool:
    res = await col(Collections.sessions).update_one(
        {"_id": session_id, "user_id": user_id, "revoked_at": None},
        {"$set": {"revoked_at": utcnow(), "revoked_reason": reason}},
    )
    return res.modified_count > 0


async def revoke_all_sessions(user_id: str, *, except_session: str | None = None, reason: str = "revoke_all") -> int:
    q: dict[str, Any] = {"user_id": user_id, "revoked_at": None}
    if except_session:
        q["_id"] = {"$ne": except_session}
    res = await col(Collections.sessions).update_many(q, {"$set": {"revoked_at": utcnow(), "revoked_reason": reason}})
    return res.modified_count


async def session_is_active(session_id: str, user_id: str) -> bool:
    s = await col(Collections.sessions).find_one({"_id": session_id, "user_id": user_id},
                                                  {"revoked_at": 1, "expires_at": 1})
    return bool(s and s.get("revoked_at") is None and as_utc(s["expires_at"]) > utcnow())


async def list_sessions(user_id: str) -> list[dict[str, Any]]:
    cur = col(Collections.sessions).find({"user_id": user_id, "revoked_at": None}).sort("last_used_at", -1).limit(50)
    out = []
    for s in await cur.to_list(None):
        out.append({"id": s["_id"], "created_at": s["created_at"], "last_used_at": s.get("last_used_at"),
                    "ip": s.get("ip"), "user_agent": s.get("user_agent"), "method": s.get("method")})
    return out


# --- One-time tokens (verification, reset) -------------------------------------------------

async def _issue_one_time(collection: str, user_id: str, ttl: timedelta, purpose_extra: dict[str, Any] | None = None) -> str:
    token = new_token(32)
    # Invalidate previous outstanding tokens for this user.
    await col(collection).delete_many({"user_id": user_id})
    await col(collection).insert_one({
        "_id": new_id("tok"),
        "user_id": user_id,
        "token_hash": hash_token(token),
        "created_at": utcnow(),
        "expires_at": utcnow() + ttl,
        "used_at": None,
        **(purpose_extra or {}),
    })
    return token


async def _consume_one_time(collection: str, token: str) -> dict[str, Any]:
    now = utcnow()
    doc = await col(collection).find_one_and_update(
        {"token_hash": hash_token(token), "used_at": None},
        {"$set": {"used_at": now}},
        return_document=ReturnDocument.BEFORE,
    )
    # TTL deletion is asynchronous, so expiry is always checked explicitly.
    if doc is None or as_utc(doc["expires_at"]) <= now:
        raise AppError("This link is invalid or has expired. Request a new one.", code="invalid_token", status_code=400)
    return doc


async def issue_verification_token(user: dict[str, Any]) -> str:
    return await _issue_one_time(Collections.verification_tokens, user["_id"], VERIFY_TTL, {"email": user["email"]})


async def verify_email_token(token: str) -> dict[str, Any]:
    doc = await _consume_one_time(Collections.verification_tokens, token)
    user = await get_user(doc["user_id"])
    if not user or user["email"] != doc.get("email"):
        raise AppError("This link is invalid or has expired.", code="invalid_token", status_code=400)
    await col(Collections.users).update_one({"_id": user["_id"]}, {"$set": {"email_verified": True, "updated_at": utcnow()}})
    user["email_verified"] = True
    return await maybe_promote_bootstrap_admin(user)


async def issue_reset_token(user: dict[str, Any]) -> str:
    return await _issue_one_time(Collections.password_reset_tokens, user["_id"], RESET_TTL)


async def reset_password(token: str, new_password: str) -> dict[str, Any]:
    doc = await _consume_one_time(Collections.password_reset_tokens, token)
    user = await get_user(doc["user_id"])
    if not user:
        raise AppError("This link is invalid or has expired.", code="invalid_token", status_code=400)
    validate_password_strength(new_password, user["email"])
    await col(Collections.users).update_one(
        {"_id": user["_id"]},
        {"$set": {"password_hash": hash_password(new_password), "password_changed_at": utcnow(), "updated_at": utcnow(),
                  # Proving control of the mailbox also verifies the address.
                  "email_verified": True}},
    )
    await revoke_all_sessions(user["_id"], reason="password_reset")
    return user


async def change_password(user: dict[str, Any], current: str | None, new: str, session_id: str) -> None:
    if user.get("password_hash"):
        if not current or not verify_password(current, user["password_hash"]):
            raise AppError("Current password is incorrect.", code="invalid_credentials", status_code=400)
    validate_password_strength(new, user["email"])
    await col(Collections.users).update_one(
        {"_id": user["_id"]},
        {"$set": {"password_hash": hash_password(new), "password_changed_at": utcnow(), "updated_at": utcnow()}},
    )
    await revoke_all_sessions(user["_id"], except_session=session_id, reason="password_changed")
