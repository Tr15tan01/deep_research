"""Authentication HTTP API."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field

from app.auth import google, service
from app.auth.deps import (
    CSRF_COOKIE,
    REFRESH_COOKIE,
    Principal,
    clear_auth_cookies,
    current_principal,
    ensure_csrf_cookie,
    optional_principal,
    set_auth_cookies,
)
from app.core import ratelimit
from app.core.config import get_settings
from app.core.errors import AppError, FeatureDisabled, NotAuthenticated
from app.core.logging import get_logger
from app.core.ratelimit import client_ip
from app.core.security import sign_state, verify_state
from app.services.audit import audit
from app.services.mailer import existing_account_email, reset_email, send_email, verification_email

log = get_logger("auth")
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
OAUTH_COOKIE = "dr_oauth"


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    name: str = Field(default="", max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class TokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class EmailIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordIn(BaseModel):
    current_password: str | None = Field(default=None, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


def _frontend(path: str) -> str:
    return get_settings().FRONTEND_URL.rstrip("/") + path


def _safe_next(path: str | None) -> str:
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path or not re.match(r"^/[\w\-/?=&%.]*$", path):
        return "/dashboard"
    return path


async def _send_verification(user: dict[str, Any]) -> None:
    token = await service.issue_verification_token(user)
    subject, text = verification_email(user.get("name", ""), _frontend(f"/verify-email?token={token}"), get_settings().APP_NAME)
    await send_email(user["email"], subject, text)


@router.get("/csrf")
async def csrf(request: Request, response: Response) -> dict[str, str]:
    token = ensure_csrf_cookie(response, request.cookies.get(CSRF_COOKIE))
    return {"csrf_token": token}


@router.post("/register", status_code=201)
async def register(body: RegisterIn, request: Request, response: Response) -> dict[str, Any]:
    s = get_settings()
    ip = client_ip(request)
    await ratelimit.enforce(ratelimit.AUTH_REGISTER, f"ip:{ip}")
    if not s.PUBLIC_SIGNUP_ENABLED:
        raise AppError("New sign-ups are currently closed.", code="signup_disabled", status_code=403)
    email = service.normalize_email(body.email)
    service.validate_password_strength(body.password, email)
    existing = await service.get_user_by_email(email)

    if s.email_verification_required:
        # Identical response whether or not the account exists (no enumeration).
        if existing:
            subject, text = existing_account_email(_frontend("/login"), s.APP_NAME)
            await send_email(email, subject, text)
        else:
            user = await service.create_user(email, body.password, body.name)
            await _send_verification(user)
            await audit("user.registered", actor_id=user["_id"], ip=ip)
        return {"status": "verification_required",
                "message": "Check your inbox for a verification link to finish creating your account."}

    if existing:
        # Without an email channel enumeration cannot be fully hidden; keep the message generic.
        raise AppError("We couldn't create an account with these details. If you already have an account, sign in "
                       "or reset your password.", code="registration_failed", status_code=409)
    user = await service.create_user(email, body.password, body.name)
    await audit("user.registered", actor_id=user["_id"], ip=ip)
    issued = await service.create_session(user, ip=ip, user_agent=request.headers.get("user-agent"), method="password")
    set_auth_cookies(response, issued.access_token, issued.refresh_token)
    return {"status": "signed_in", "user": service.public_user(user)}


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response) -> dict[str, Any]:
    ip = client_ip(request)
    email = service.normalize_email(body.email)
    await ratelimit.enforce(ratelimit.AUTH_LOGIN, f"ip:{ip}", f"email:{email}")
    try:
        user = await service.authenticate(email, body.password)
    except AppError as e:
        await audit("user.login", actor_id=None, ip=ip, outcome="failure", metadata={"reason": e.code})
        raise
    user = await service.maybe_promote_bootstrap_admin(user)
    issued = await service.create_session(user, ip=ip, user_agent=request.headers.get("user-agent"), method="password")
    set_auth_cookies(response, issued.access_token, issued.refresh_token)
    await audit("user.login", actor_id=user["_id"], ip=ip)
    return {"status": "signed_in", "user": service.public_user(user)}


@router.post("/refresh")
async def refresh(request: Request, response: Response) -> dict[str, Any]:
    ip = client_ip(request)
    await ratelimit.enforce(ratelimit.AUTH_REFRESH, f"ip:{ip}")
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise NotAuthenticated("Your session has expired. Please sign in again.", code="session_expired")
    try:
        issued = await service.rotate_refresh(token, ip=ip)
    except NotAuthenticated:
        clear_auth_cookies(response)
        raise
    set_auth_cookies(response, issued.access_token, issued.refresh_token)
    return {"status": "refreshed", "user": service.public_user(issued.user)}


@router.post("/logout")
async def logout(request: Request, response: Response, principal: Principal | None = Depends(optional_principal)) -> dict[str, str]:
    if principal:
        await service.revoke_session(principal.session_id, principal.id)
        await audit("user.logout", actor_id=principal.id, ip=client_ip(request))
    clear_auth_cookies(response)
    return {"status": "signed_out"}


@router.get("/session")
async def session_state(request: Request, principal: Principal | None = Depends(optional_principal)) -> dict[str, Any]:
    """Non-throwing session probe for page loads: 200 with ``user: null`` when signed out, plus
    whether a refresh cookie is present (so the client knows a refresh attempt is worthwhile)."""
    return {"user": service.public_user(principal.user) if principal else None,
            "refreshable": principal is None and bool(request.cookies.get(REFRESH_COOKIE))}


@router.get("/me")
async def me(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    return {"user": service.public_user(principal.user)}


@router.post("/verify-email")
async def verify_email(body: TokenIn, request: Request) -> dict[str, Any]:
    if not get_settings().email_verification_required:
        # Still allow verifying (harmless), so links sent while enabled keep working.
        pass
    user = await service.verify_email_token(body.token)
    await audit("user.email_verified", actor_id=user["_id"], ip=client_ip(request))
    return {"status": "verified"}


@router.post("/resend-verification", status_code=202)
async def resend_verification(request: Request, principal: Principal = Depends(current_principal)) -> dict[str, str]:
    await ratelimit.enforce(ratelimit.AUTH_EMAIL, f"user:{principal.id}", f"ip:{client_ip(request)}")
    if not principal.user.get("email_verified"):
        await _send_verification(principal.user)
    return {"status": "sent"}


@router.post("/forgot-password", status_code=202)
async def forgot_password(body: EmailIn, request: Request) -> dict[str, str]:
    s = get_settings()
    if not s.PASSWORD_RESET_ENABLED:
        raise FeatureDisabled("Password reset is not enabled.")
    ip = client_ip(request)
    email = service.normalize_email(body.email)
    await ratelimit.enforce(ratelimit.AUTH_EMAIL, f"ip:{ip}", f"email:{email}")
    user = await service.get_user_by_email(email)
    if user and user.get("status") == "active":
        token = await service.issue_reset_token(user)
        subject, text = reset_email(user.get("name", ""), _frontend(f"/reset-password?token={token}"), s.APP_NAME)
        await send_email(user["email"], subject, text)
        await audit("user.password_reset_requested", actor_id=user["_id"], ip=ip)
    return {"status": "sent", "message": "If an account exists for that email, a reset link is on its way."}


@router.post("/reset-password")
async def reset_password(body: ResetIn, request: Request, response: Response) -> dict[str, str]:
    if not get_settings().PASSWORD_RESET_ENABLED:
        raise FeatureDisabled("Password reset is not enabled.")
    await ratelimit.enforce(ratelimit.AUTH_EMAIL, f"ip:{client_ip(request)}")
    user = await service.reset_password(body.token, body.password)
    clear_auth_cookies(response)
    await audit("user.password_reset", actor_id=user["_id"], ip=client_ip(request))
    return {"status": "password_reset"}


@router.post("/change-password")
async def change_password(body: ChangePasswordIn, request: Request, principal: Principal = Depends(current_principal)) -> dict[str, str]:
    await ratelimit.enforce(ratelimit.AUTH_LOGIN, f"user:{principal.id}")
    await service.change_password(principal.user, body.current_password, body.new_password, principal.session_id)
    await audit("user.password_changed", actor_id=principal.id, ip=client_ip(request))
    return {"status": "password_changed"}


@router.get("/sessions")
async def sessions(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    items = await service.list_sessions(principal.id)
    for it in items:
        it["current"] = it["id"] == principal.session_id
    return {"items": items}


@router.delete("/sessions/{session_id}")
async def revoke_session(session_id: str, request: Request, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    ok = await service.revoke_session(session_id, principal.id, reason="user_revoked")
    await audit("session.revoked", actor_id=principal.id, target_id=session_id, ip=client_ip(request))
    return {"revoked": ok}


@router.post("/sessions/revoke-others")
async def revoke_others(request: Request, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    n = await service.revoke_all_sessions(principal.id, except_session=principal.session_id, reason="user_revoked_others")
    await audit("session.revoked_others", actor_id=principal.id, ip=client_ip(request), metadata={"count": n})
    return {"revoked": n}


# --- Google OAuth ---------------------------------------------------------------------------

@router.get("/google/start")
async def google_start(next: str | None = Query(default=None, max_length=300)) -> RedirectResponse:  # noqa: A002
    if not get_settings().GOOGLE_AUTH_ENABLED:
        raise FeatureDisabled("Google sign-in is disabled.")
    if not google.google_available():
        raise AppError("Google sign-in is enabled but not configured. Ask an administrator to set "
                       "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.", code="configuration_required", status_code=503)
    url, state = google.build_authorization(_safe_next(next))
    resp = RedirectResponse(url, status_code=302)
    s = get_settings()
    resp.set_cookie(OAUTH_COOKIE, sign_state(state, ttl_seconds=600), httponly=True, secure=s.secure_cookies,
                    samesite="lax", path="/api/v1/auth/google", max_age=600)
    return resp


@router.get("/google/callback")
async def google_callback(request: Request, code: str | None = None, state: str | None = None,
                          error: str | None = None) -> RedirectResponse:
    s = get_settings()
    if not s.GOOGLE_AUTH_ENABLED:
        raise FeatureDisabled("Google sign-in is disabled.")

    def fail(reason: str) -> RedirectResponse:
        r = RedirectResponse(_frontend(f"/login?error={reason}"), status_code=302)
        r.delete_cookie(OAUTH_COOKIE, path="/api/v1/auth/google")
        return r

    if error or not code or not state:
        return fail("oauth_cancelled")
    raw = request.cookies.get(OAUTH_COOKIE)
    stored = verify_state(raw) if raw else None
    import secrets as _secrets

    if not stored or not _secrets.compare_digest(str(stored.get("state", "")), state):
        return fail("oauth_state_mismatch")
    ip = client_ip(request)
    try:
        await google.consume_state_jti(stored["jti"])
        claims = await google.exchange_code(code, stored["verifier"], stored["nonce"])
        user = await google.resolve_google_user(claims)
    except AppError as e:
        await audit("user.login", actor_id=None, ip=ip, outcome="failure", metadata={"method": "google", "reason": e.code})
        return fail(e.code)
    issued = await service.create_session(user, ip=ip, user_agent=request.headers.get("user-agent"), method="google")
    resp = RedirectResponse(_frontend(_safe_next(stored.get("next"))), status_code=302)
    resp.delete_cookie(OAUTH_COOKIE, path="/api/v1/auth/google")
    set_auth_cookies(resp, issued.access_token, issued.refresh_token)
    await audit("user.login", actor_id=user["_id"], ip=ip, metadata={"method": "google"})
    return resp
