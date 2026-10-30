"""Single-service hosting (e.g. Render free tier): embedded worker in production, an API with a public URL
locked to the web proxy by a shared token, and trustworthy client IPs for rate limiting."""

from __future__ import annotations

from typing import Any

import pytest

TOKEN = "t" * 40


def test_embedded_worker_allowed_in_production_with_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import ConfigError, Settings

    env = {"APP_ENV": "production", "FRONTEND_URL": "https://deep-research-web.onrender.com",
           "MONGODB_URI": "mongodb+srv://u:p@c.example.mongodb.net/", "REDIS_URL": "redis://red:6379",
           "AUTH_SECRET": "a" * 44, "ENCRYPTION_KEYS": "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=",
           "PASSWORD_RESET_ENABLED": "0", "EMAIL_VERIFICATION_ENABLED": "0", "EMBEDDED_WORKER": "1",
           "INTERNAL_PROXY_TOKEN": TOKEN}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    s = Settings()
    assert s.EMBEDDED_WORKER and any("single-service" in w for w in s.config_warnings)
    monkeypatch.setenv("INTERNAL_PROXY_TOKEN", "short")
    with pytest.raises(ConfigError, match="INTERNAL_PROXY_TOKEN"):
        Settings()


async def test_internal_token_required_except_health(make_client: Any, env: Any) -> None:
    env(INTERNAL_PROXY_TOKEN=TOKEN)
    c = await make_client()
    assert (await c.c.get("/health/live")).status_code == 200
    assert (await c.c.get("/health/ready")).status_code == 200
    r = await c.c.get("/api/v1/public/config")
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    assert (await c.c.get("/api/v1/public/config", headers={"x-internal-token": "x" * 40})).status_code == 403
    ok = await c.c.get("/api/v1/public/config", headers={"x-internal-token": TOKEN})
    assert ok.status_code == 200
    # The full browser flow works through the proxy header.
    c.c.headers["x-internal-token"] = TOKEN
    assert (await c.register("proxy@example.com")).status_code == 201
    assert (await c.get("/api/v1/auth/me")).json()["user"]["email"] == "proxy@example.com"


async def test_client_ip_from_proxy_header_only_with_token(make_client: Any, env: Any) -> None:
    from starlette.requests import Request

    from app.core.ratelimit import client_ip

    def req(headers: dict[str, str]) -> Request:
        return Request({"type": "http", "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
                        "client": ("10.0.0.5", 1234), "method": "GET", "path": "/"})

    env(TRUSTED_PROXY_HOPS="1")
    # Without the token mode, a client-supplied X-DR-Client-IP is ignored.
    assert client_ip(req({"x-dr-client-ip": "6.6.6.6", "x-forwarded-for": "1.2.3.4"})) == "1.2.3.4"
    env(INTERNAL_PROXY_TOKEN=TOKEN)
    assert client_ip(req({"x-dr-client-ip": "203.0.113.9", "x-forwarded-for": "1.2.3.4, 9.9.9.9"})) == "203.0.113.9"
    assert client_ip(req({"x-forwarded-for": "1.2.3.4"})) == "1.2.3.4"  # falls back to hop logic
