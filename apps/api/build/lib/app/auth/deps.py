"""Request authentication, authorization and CSRF protection."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Request, Response
from starlette.responses import JSONResponse

from app.auth.service import get_user, session_is_active
from app.core.config import get_settings
from app.core.errors import AppError, Forbidden, NotAuthenticated, new_reference_id
from app.core.security import decode_access_token

ACCESS_COOKIE = "dr_access"
REFRESH_COOKIE = "dr_refresh"
CSRF_COOKIE = "dr_csrf"
SESSION_HINT_COOKIE = "dr_session"  # non-secret hint so the frontend proxy can route signed-in users
CSRF_HEADER = "x-csrf-token"
REFRESH_COOKIE_PATH = "/api/v1/auth"

# Endpoints that legitimately receive cross-site, cookie-less POSTs (verified by signature).
CSRF_EXEMPT_PREFIXES = ("/api/v1/billing/webhook",)
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass
class Principal:
    user: dict[str, Any]
    session_id: str

    @property
    def id(self) -> str:
        return self.user["_id"]

    @property
    def role(self) -> str:
        return self.user.get("role", "USER")

    @property
    def is_admin(self) -> bool:
        return self.role == "ADMIN"


def _cookie_kwargs() -> dict[str, Any]:
    s = get_settings()
    kw: dict[str, Any] = {"secure": s.secure_cookies, "samesite": "lax"}
    if s.COOKIE_DOMAIN:
        kw["domain"] = s.COOKIE_DOMAIN
    return kw


def set_auth_cookies(response: Response, access: str, refresh: str | None) -> None:
    s = get_settings()
    response.set_cookie(ACCESS_COOKIE, access, httponly=True, path="/", max_age=s.ACCESS_TOKEN_TTL_MINUTES * 60,
                        **_cookie_kwargs())
    if refresh is not None:
        response.set_cookie(REFRESH_COOKIE, refresh, httponly=True, path=REFRESH_COOKIE_PATH,
                            max_age=s.REFRESH_TOKEN_TTL_DAYS * 86400, **_cookie_kwargs())
        response.set_cookie(SESSION_HINT_COOKIE, "1", httponly=True, path="/", max_age=s.REFRESH_TOKEN_TTL_DAYS * 86400,
                            **_cookie_kwargs())
    ensure_csrf_cookie(response, None)


def clear_auth_cookies(response: Response) -> None:
    kw = _cookie_kwargs()
    response.delete_cookie(ACCESS_COOKIE, path="/", **kw)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, **kw)
    response.delete_cookie(SESSION_HINT_COOKIE, path="/", **kw)


def ensure_csrf_cookie(response: Response, existing: str | None) -> str:
    token = existing if existing and len(existing) >= 32 else secrets.token_urlsafe(32)
    # Readable by JS on the frontend origin (double-submit pattern); not a secret by itself.
    response.set_cookie(CSRF_COOKIE, token, httponly=False, path="/", max_age=7 * 86400, **_cookie_kwargs())
    return token


class CSRFMiddleware:
    """Pure-ASGI double-submit CSRF protection plus Origin allow-listing for unsafe methods.

    Every unsafe request under /api/ must carry an ``X-CSRF-Token`` header equal to the
    ``dr_csrf`` cookie. Signature-verified webhooks are exempt.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope["method"] in UNSAFE_METHODS:
            path: str = scope["path"]
            if path.startswith("/api/") and not path.startswith(CSRF_EXEMPT_PREFIXES):
                request = Request(scope)
                settings = get_settings()
                origin = request.headers.get("origin")
                if origin and origin.rstrip("/") not in settings.cors_origins:
                    await _csrf_error("Cross-origin request blocked.")(scope, receive, send)
                    return
                cookie = request.cookies.get(CSRF_COOKIE)
                header = request.headers.get(CSRF_HEADER)
                if not cookie or not header or not secrets.compare_digest(cookie, header):
                    await _csrf_error("Missing or invalid CSRF token. Refresh the page and try again.")(scope, receive, send)
                    return
        await self.app(scope, receive, send)


def _csrf_error(message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": "csrf_failed", "message": message, "reference_id": new_reference_id(),
                                   "details": {}}}, status_code=403)


async def optional_principal(request: Request) -> Principal | None:
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        auth = request.headers.get("authorization", "")
        # Bearer support exists for server-to-server calls and tests; browsers use cookies.
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    if not token:
        return None
    claims = decode_access_token(token)
    if not claims:
        return None
    # Per-request session check gives immediate revocation (logout, password change, admin disable).
    if not await session_is_active(claims["sid"], claims["sub"]):
        return None
    user = await get_user(claims["sub"])
    if not user or user.get("status") != "active":
        return None
    request.state.user_id = user["_id"]
    return Principal(user=user, session_id=claims["sid"])


async def current_principal(principal: Principal | None = Depends(optional_principal)) -> Principal:
    if principal is None:
        raise NotAuthenticated()
    return principal


async def verified_principal(principal: Principal = Depends(current_principal)) -> Principal:
    if get_settings().email_verification_required and not principal.user.get("email_verified"):
        raise Forbidden("Verify your email address to use this feature.", code="email_not_verified")
    return principal


def require_role(*roles: str) -> Callable[[Principal], Awaitable[Principal]]:
    async def _dep(principal: Principal = Depends(current_principal)) -> Principal:
        if principal.role not in roles:
            raise Forbidden()
        return principal

    return _dep


require_admin = require_role("ADMIN")


def require_feature(flag: str, message: str = "This feature is not enabled.") -> Callable[[], Awaitable[None]]:
    async def _dep() -> None:
        if not getattr(get_settings(), flag):
            raise AppError(message, code="feature_disabled", status_code=404)

    return _dep
