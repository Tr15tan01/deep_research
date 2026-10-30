"""Cryptographic primitives: password hashing, tokens, JWTs and at-rest encryption."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import get_settings

# Argon2id with OWASP-recommended baseline parameters (m=19 MiB, t=2, p=1) raised slightly.
_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2, hash_len=32, salt_len=16)
# A precomputed hash used to equalise timing when the account does not exist.
_DUMMY_HASH = _hasher.hash("timing-equalisation-placeholder")

_EPHEMERAL_SECRET = secrets.token_urlsafe(48)


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(dt: datetime | None) -> datetime | None:
    """Mongo returns naive datetimes (UTC); normalise for comparisons."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# --- Passwords -----------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# --- Opaque tokens -------------------------------------------------------------------------

def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Tokens are stored only as keyed hashes so a DB leak does not reveal usable tokens."""
    return hmac.new(_derived_key(b"token-hash"), token.encode(), hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# --- Keys ----------------------------------------------------------------------------------

def _auth_secret() -> bytes:
    s = get_settings().AUTH_SECRET
    return (s or _EPHEMERAL_SECRET).encode()


@lru_cache(maxsize=16)
def _derived_key_cached(secret: bytes, purpose: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"deep-research/v1", info=purpose).derive(secret)


def _derived_key(purpose: bytes) -> bytes:
    return _derived_key_cached(_auth_secret(), purpose)


# --- JWT access tokens ---------------------------------------------------------------------
JWT_ALG = "HS256"
JWT_AUDIENCE = "deep-research-api"
JWT_ISSUER = "deep-research"


def create_access_token(*, user_id: str, session_id: str, role: str, ttl_minutes: int | None = None,
                        extra: dict[str, Any] | None = None) -> str:
    now = utcnow()
    ttl = ttl_minutes or get_settings().ACCESS_TOKEN_TTL_MINUTES
    payload = {
        "sub": user_id,
        "sid": session_id,
        "role": role,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()) - 5,
        "exp": int((now + timedelta(minutes=ttl)).timestamp()),
        "aud": JWT_AUDIENCE,
        "iss": JWT_ISSUER,
        "typ": "access",
        **(extra or {}),
    }
    return jwt.encode(payload, _derived_key(b"jwt-access"), algorithm=JWT_ALG)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        data = jwt.decode(token, _derived_key(b"jwt-access"), algorithms=[JWT_ALG], audience=JWT_AUDIENCE,
                          issuer=JWT_ISSUER, options={"require": ["exp", "sub", "sid", "iat"]}, leeway=5)
    except jwt.PyJWTError:
        return None
    if data.get("typ") != "access":
        return None
    return data


def sign_state(payload: dict[str, Any], ttl_seconds: int = 600) -> str:
    """Short-lived signed blob (e.g. OAuth state cookie)."""
    now = utcnow()
    body = {**payload, "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()), "typ": "state"}
    return jwt.encode(body, _derived_key(b"signed-state"), algorithm=JWT_ALG)


def verify_state(token: str) -> dict[str, Any] | None:
    try:
        data = jwt.decode(token, _derived_key(b"signed-state"), algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        return None
    return data if data.get("typ") == "state" else None


# --- At-rest encryption (AES-256-GCM with key rotation) -----------------------------------

class EncryptionError(RuntimeError):
    pass


_EPHEMERAL_ENC_KEY = os.urandom(32)


def _encryption_keys() -> list[bytes]:
    raw = get_settings().ENCRYPTION_KEYS
    keys: list[bytes] = []
    for item in [k.strip() for k in raw.split(",") if k.strip()]:
        try:
            key = base64.urlsafe_b64decode(item + "=" * (-len(item) % 4))
        except Exception as e:  # noqa: BLE001
            raise EncryptionError("ENCRYPTION_KEYS contains an invalid key") from e
        if len(key) != 32:
            raise EncryptionError("each ENCRYPTION_KEYS entry must decode to 32 bytes")
        keys.append(key)
    if not keys:
        if get_settings().is_production:
            raise EncryptionError("ENCRYPTION_KEYS is not configured")
        # Development: derive from AUTH_SECRET if set (stable), else ephemeral.
        keys = [_derived_key(b"dev-encryption") if get_settings().AUTH_SECRET else _EPHEMERAL_ENC_KEY]
    return keys


def _key_id(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:8]


def encrypt_secret(plaintext: str, context: str) -> str:
    key = _encryption_keys()[0]
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode(), context.encode())
    return "v1:" + _key_id(key) + ":" + base64.urlsafe_b64encode(nonce).decode() + ":" + base64.urlsafe_b64encode(ct).decode()


def decrypt_secret(blob: str, context: str) -> str:
    try:
        version, kid, nonce_b64, ct_b64 = blob.split(":", 3)
    except ValueError as e:
        raise EncryptionError("malformed ciphertext") from e
    if version != "v1":
        raise EncryptionError("unsupported ciphertext version")
    for key in _encryption_keys():
        if _key_id(key) == kid:
            try:
                return AESGCM(key).decrypt(base64.urlsafe_b64decode(nonce_b64), base64.urlsafe_b64decode(ct_b64),
                                           context.encode()).decode()
            except Exception as e:  # noqa: BLE001
                raise EncryptionError("decryption failed") from e
    raise EncryptionError("no matching encryption key (was ENCRYPTION_KEYS rotated without keeping the old key?)")


def mask_secret(value: str) -> str:
    if not value:
        return ""
    return ("•" * 6) + value[-4:] if len(value) > 8 else "•" * 8
