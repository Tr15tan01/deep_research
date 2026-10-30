"""Authentication, sessions, CSRF, verification, reset, OAuth flags and rate limits."""

from __future__ import annotations

from typing import Any

from tests.conftest import ApiClient


async def test_register_login_me_logout(client: ApiClient) -> None:
    r = await client.register("alice@example.com")
    assert r.status_code == 201 and r.json()["status"] == "signed_in"
    assert "dr_access" in client.c.cookies and "dr_refresh" in client.c.cookies
    me = await client.get("/api/v1/auth/me")
    assert me.json()["user"]["email"] == "alice@example.com"
    assert "password_hash" not in me.text
    assert (await client.post("/api/v1/auth/logout")).status_code == 200
    client.c.cookies.clear()
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_weak_password_rejected(client: ApiClient) -> None:
    r = await client.register("weak@example.com", password="password")
    assert r.status_code == 422 and r.json()["error"]["code"] == "weak_password"


async def test_login_errors_are_generic(client: ApiClient) -> None:
    await client.register("bob@example.com")
    client.c.cookies.clear()
    client.csrf = None
    wrong = await client.login("bob@example.com", "Wrong!Passw0rd1")
    missing = await client.login("nobody@example.com", "Wrong!Passw0rd1")
    assert wrong.status_code == missing.status_code == 401
    assert wrong.json()["error"]["message"] == missing.json()["error"]["message"]


async def test_csrf_required_for_unsafe_methods(client: ApiClient) -> None:
    r = await client.c.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "x"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
    await client.ensure_csrf()
    bad_origin = await client.c.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "x"},
                                     headers={"x-csrf-token": client.csrf, "origin": "https://evil.example"})
    assert bad_origin.status_code == 403


async def test_refresh_rotation_and_reuse_detection(client: ApiClient, monkeypatch: Any) -> None:
    from app.auth import service

    await client.register("carol@example.com")
    old_refresh = client.c.cookies.get("dr_refresh")
    r1 = await client.post("/api/v1/auth/refresh")
    assert r1.status_code == 200
    new_refresh = r1.cookies.get("dr_refresh")
    assert new_refresh and new_refresh != old_refresh

    def use_refresh(token: str) -> None:
        client.c.cookies.delete("dr_refresh")
        client.c.cookies.set("dr_refresh", token, domain="localhost.local", path="/api/v1/auth")

    # Within the grace window a concurrent replay just gets a fresh access token.
    use_refresh(old_refresh)
    assert (await client.post("/api/v1/auth/refresh")).status_code == 200
    # After the grace window, replaying a rotated token revokes the session (theft signal).
    monkeypatch.setattr(service, "REFRESH_REUSE_GRACE_SECONDS", -1)
    use_refresh(old_refresh)
    r2 = await client.post("/api/v1/auth/refresh")
    assert r2.status_code == 401 and r2.json()["error"]["code"] == "session_revoked"
    use_refresh(new_refresh)
    r3 = await client.post("/api/v1/auth/refresh")
    assert r3.status_code == 401  # the whole session is revoked


async def test_email_verification_enforced(make_client: Any, env: Any) -> None:
    env(EMAIL_VERIFICATION_ENABLED="1")
    from app.services.mailer import DEV_OUTBOX

    c = await make_client()
    r = await c.register("dave@example.com")
    assert r.json()["status"] == "verification_required"
    # Same response for an existing account (no enumeration).
    r2 = await c.register("dave@example.com")
    assert r2.status_code == 201 and r2.json() == r.json()
    assert (await c.login("dave@example.com")).status_code == 200
    blocked = await c.post("/api/v1/research", json={"question": "What is the capital of France really?"})
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "email_not_verified"
    link = next(m for m in DEV_OUTBOX if "Verify" in m["subject"])["text"]
    token = link.split("token=")[1].split()[0]
    assert (await c.post("/api/v1/auth/verify-email", json={"token": token})).status_code == 200
    replay = await c.post("/api/v1/auth/verify-email", json={"token": token})
    assert replay.status_code == 400  # one-time use
    me = await c.get("/api/v1/auth/me")
    assert me.json()["user"]["email_verified"] is True


async def test_password_reset_flow(client: ApiClient) -> None:
    from app.services.mailer import DEV_OUTBOX

    await client.register("erin@example.com")
    r = await client.post("/api/v1/auth/forgot-password", json={"email": "erin@example.com"})
    unknown = await client.post("/api/v1/auth/forgot-password", json={"email": "ghost@example.com"})
    assert r.status_code == unknown.status_code == 202 and r.json() == unknown.json()
    token = DEV_OUTBOX[-1]["text"].split("token=")[1].split()[0]
    ok = await client.post("/api/v1/auth/reset-password", json={"token": token, "password": "N3w!Password-xyz"})
    assert ok.status_code == 200
    again = await client.post("/api/v1/auth/reset-password", json={"token": token, "password": "N3w!Password-abc"})
    assert again.status_code == 400
    # Old sessions were revoked.
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    client.c.cookies.clear()
    client.csrf = None
    assert (await client.login("erin@example.com", "N3w!Password-xyz")).status_code == 200


async def test_google_disabled_and_misconfigured(make_client: Any, env: Any) -> None:
    c = await make_client()
    assert (await c.get("/api/v1/auth/google/start")).status_code == 404
    env(GOOGLE_AUTH_ENABLED="1")
    r = await c.get("/api/v1/auth/google/start")
    assert r.status_code == 503 and r.json()["error"]["code"] == "configuration_required"
    env(GOOGLE_AUTH_ENABLED="1", GOOGLE_CLIENT_ID="cid", GOOGLE_CLIENT_SECRET="sec")
    r = await c.get("/api/v1/auth/google/start", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert "code_challenge_method=S256" in loc and "nonce=" in loc and "state=" in loc
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A3000%2Fapi%2Fv1%2Fauth%2Fgoogle%2Fcallback" in loc
    bad = await c.get("/api/v1/auth/google/callback?code=x&state=forged", follow_redirects=False)
    assert bad.status_code == 302 and "oauth_state_mismatch" in bad.headers["location"]


async def test_google_never_merges_unverified_accounts(infra: Any) -> None:
    import pytest

    from app.auth.google import resolve_google_user
    from app.auth.service import create_user
    from app.core.errors import AppError

    await create_user("frank@example.com", "Str0ng!Passw0rd", "Frank", email_verified=False)
    with pytest.raises(AppError) as ei:
        await resolve_google_user({"sub": "g-1", "email": "frank@example.com", "email_verified": True})
    assert ei.value.code == "oauth_link_requires_verification"
    with pytest.raises(AppError):
        await resolve_google_user({"sub": "g-2", "email": "new@example.com", "email_verified": False})
    u = await resolve_google_user({"sub": "g-3", "email": "gina@example.com", "email_verified": True, "name": "Gina"})
    assert u["email_verified"] is True and u["google_sub"] == "g-3"


async def test_login_rate_limited(make_client: Any, env: Any) -> None:
    env(RATE_LIMIT_ENABLED="1")
    c = await make_client()
    codes = [(await c.login("rl@example.com", "Wrong!Passw0rd1")).status_code for _ in range(12)]
    assert codes[-1] == 429 and 401 in codes


async def test_session_revocation_is_immediate(client: ApiClient) -> None:
    await client.register("hank@example.com")
    sessions = (await client.get("/api/v1/auth/sessions")).json()["items"]
    assert len(sessions) == 1 and sessions[0]["current"]
    await client.delete(f"/api/v1/auth/sessions/{sessions[0]['id']}")
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_signup_disabled(make_client: Any, env: Any) -> None:
    env(PUBLIC_SIGNUP_ENABLED="0")
    c = await make_client()
    r = await c.register("ivy@example.com")
    assert r.status_code == 403 and r.json()["error"]["code"] == "signup_disabled"


async def test_account_export_and_delete(client: ApiClient) -> None:
    await client.register("jack@example.com")
    exp = await client.get("/api/v1/account/export")
    assert exp.status_code == 200 and exp.json()["user"]["email"] == "jack@example.com"
    assert "password_hash" not in exp.text
    r = await client.post("/api/v1/account/delete", json={"password": "Str0ng!Passw0rd", "confirm": "DELETE"})
    assert r.status_code == 200
    client.c.cookies.clear()
    client.csrf = None
    assert (await client.login("jack@example.com")).status_code == 401


async def test_security_headers(client: ApiClient) -> None:
    r = await client.get("/health/live")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "x-request-id" in r.headers


async def test_session_probe_never_401s(client: ApiClient) -> None:
    anon = await client.get("/api/v1/auth/session")
    assert anon.status_code == 200 and anon.json() == {"user": None, "refreshable": False}
    await client.register("probe@example.com")
    signed_in = (await client.get("/api/v1/auth/session")).json()
    assert signed_in["user"]["email"] == "probe@example.com" and signed_in["refreshable"] is False
    # Access cookie gone but refresh cookie present → client is told a refresh is worthwhile.
    client.c.cookies.delete("dr_access")
    expired = (await client.get("/api/v1/auth/session")).json()
    assert expired == {"user": None, "refreshable": True}
