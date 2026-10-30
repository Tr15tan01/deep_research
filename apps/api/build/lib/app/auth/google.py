"""Google OAuth 2.0 / OpenID Connect login (authorization code + PKCE + state + nonce)."""

from __future__ import annotations

import base64
import hashlib
import time
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from pymongo.errors import DuplicateKeyError

from app.auth.service import create_user, get_user_by_email, maybe_promote_bootstrap_admin, normalize_email
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import new_token, utcnow
from app.db.mongo import Collections, col

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 — public endpoint URL
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")

_jwks_cache: dict[str, Any] = {"keys": None, "fetched": 0.0}


def redirect_uri() -> str:
    # Callback goes through the frontend origin (same-site proxy) so cookies are first-party.
    return get_settings().FRONTEND_URL.rstrip("/") + "/api/v1/auth/google/callback"


def google_available() -> bool:
    s = get_settings()
    return bool(s.GOOGLE_AUTH_ENABLED and s.GOOGLE_CLIENT_ID and s.GOOGLE_CLIENT_SECRET)


def _pkce_pair() -> tuple[str, str]:
    verifier = new_token(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def build_authorization(next_path: str) -> tuple[str, dict[str, Any]]:
    s = get_settings()
    state, nonce = new_token(24), new_token(24)
    verifier, challenge = _pkce_pair()
    params = {
        "client_id": s.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
        "access_type": "online",
    }
    return AUTH_URL + "?" + urlencode(params), {"state": state, "nonce": nonce, "verifier": verifier,
                                                "next": next_path, "jti": new_token(16)}


async def consume_state_jti(jti: str, ttl_seconds: int = 900) -> None:
    from datetime import timedelta

    try:
        await col(Collections.oauth_states).insert_one({"_id": jti, "jti": jti, "expires_at": utcnow() + timedelta(seconds=ttl_seconds)})
    except DuplicateKeyError as e:
        raise AppError("This sign-in attempt was already used. Please try again.", code="oauth_replay") from e


async def _jwks(client: httpx.AsyncClient) -> dict[str, Any]:
    if _jwks_cache["keys"] is None or time.time() - _jwks_cache["fetched"] > 3600:
        r = await client.get(JWKS_URL, timeout=10)
        r.raise_for_status()
        _jwks_cache["keys"] = r.json()
        _jwks_cache["fetched"] = time.time()
    return _jwks_cache["keys"]


async def exchange_code(code: str, verifier: str, nonce: str, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    s = get_settings()
    own = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        r = await client.post(TOKEN_URL, data={
            "code": code,
            "client_id": s.GOOGLE_CLIENT_ID,
            "client_secret": s.GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        })
        if r.status_code != 200:
            raise AppError("Google sign-in failed. Please try again.", code="oauth_exchange_failed")
        id_token = r.json().get("id_token")
        if not id_token:
            raise AppError("Google did not return an identity token.", code="oauth_exchange_failed")
        jwks = await _jwks(client)
        header = jwt.get_unverified_header(id_token)
        key_data = next((k for k in jwks.get("keys", []) if k.get("kid") == header.get("kid")), None)
        if key_data is None:
            _jwks_cache["keys"] = None
            raise AppError("Could not verify Google identity token.", code="oauth_invalid_token")
        key = jwt.PyJWK(key_data).key
        claims = jwt.decode(id_token, key, algorithms=["RS256"], audience=s.GOOGLE_CLIENT_ID,
                            options={"require": ["exp", "iat", "iss", "sub", "aud"]}, leeway=30)
    except jwt.PyJWTError as e:
        raise AppError("Could not verify Google identity token.", code="oauth_invalid_token") from e
    except httpx.HTTPError as e:
        raise AppError("Could not reach Google. Please try again.", code="oauth_unavailable", status_code=503) from e
    finally:
        if own:
            await client.aclose()
    if claims.get("iss") not in ISSUERS:
        raise AppError("Invalid identity token issuer.", code="oauth_invalid_token")
    if claims.get("nonce") != nonce:
        raise AppError("Invalid sign-in nonce.", code="oauth_invalid_token")
    return claims


async def resolve_google_user(claims: dict[str, Any]) -> dict[str, Any]:
    """Find or create the account for a verified Google identity.

    Linking rule: an existing local account is linked only if *both* its address and the
    Google address are verified. Unverified addresses are never merged.
    """
    s = get_settings()
    users = col(Collections.users)
    sub = str(claims["sub"])
    email = normalize_email(str(claims.get("email", "")))
    email_verified = claims.get("email_verified") in (True, "true")

    by_sub = await users.find_one({"google_sub": sub})
    if by_sub:
        if by_sub.get("status") != "active":
            raise AppError("This account is disabled.", code="account_disabled", status_code=403)
        return by_sub
    if not email or not email_verified:
        raise AppError("Your Google account email is not verified.", code="oauth_email_unverified", status_code=403)
    existing = await get_user_by_email(email)
    if existing:
        if not existing.get("email_verified"):
            raise AppError(
                "An account with this email already exists but its email is not verified. Sign in with your password "
                "and verify your email first, then link Google from Settings → Security.",
                code="oauth_link_requires_verification", status_code=409)
        if existing.get("status") != "active":
            raise AppError("This account is disabled.", code="account_disabled", status_code=403)
        await users.update_one({"_id": existing["_id"]}, {"$set": {"google_sub": sub, "updated_at": utcnow()}})
        existing["google_sub"] = sub
        return await maybe_promote_bootstrap_admin(existing)
    if not s.PUBLIC_SIGNUP_ENABLED:
        raise AppError("New sign-ups are currently closed.", code="signup_disabled", status_code=403)
    return await create_user(email, None, str(claims.get("name", ""))[:120], email_verified=True, google_sub=sub)
