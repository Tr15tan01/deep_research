"""Shared fixtures: in-memory MongoDB (mongomock) + fakeredis, settings overrides and an
HTTP client that speaks the app's cookie + CSRF protocol.

These are *mocked-infrastructure* tests. Live integration tests against real providers are
marked ``@pytest.mark.live`` and only run with LIVE_TESTS=1 and real credentials.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from typing import Any

import pytest

BASE_ENV = {
    "APP_ENV": "test",
    "ENV_FILE": "/nonexistent.env",
    "AUTH_SECRET": "test-secret-" + "x" * 40,
    "MONGODB_URI": "mongomock://",
    "REDIS_URL": "",
    "FRONTEND_URL": "http://localhost:3000",
    "DEMO_MODE": "0",
    "RATE_LIMIT_ENABLED": "0",
    "GOOGLE_AUTH_ENABLED": "0",
    "EMAIL_VERIFICATION_ENABLED": "0",
    "AI_PROVIDER": "gemini",
    "AI_MODEL": "",
    "SEARCH_PROVIDER": "tavily",
    "TAVILY_API_KEY": "",
    "FIRECRAWL_API_KEY": "",
    "BRAVE_SEARCH_API_KEY": "",
    "SCHOLARLY_SEARCH_ENABLED": "0",
    "UPLOAD_DIR": tempfile.mkdtemp(prefix="dr-uploads-"),
    "WORKER_POLL_SECONDS": "1",
    "LOG_LEVEL": "WARNING",
}
for k, v in BASE_ENV.items():
    os.environ[k] = v


def apply_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    from app.core.config import reset_settings_cache

    for k, v in overrides.items():
        monkeypatch.setenv(k, v)
    reset_settings_cache()


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch: pytest.MonkeyPatch) -> Any:
    from app.core.config import reset_settings_cache
    from app.llm.config_store import reset_search_key_cache

    for k, v in BASE_ENV.items():
        monkeypatch.setenv(k, v)
    reset_settings_cache()
    reset_search_key_cache()
    yield
    reset_settings_cache()
    reset_search_key_cache()


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Any:
    def _set(**kw: str) -> None:
        apply_env(monkeypatch, **kw)

    return _set


@pytest.fixture
async def infra() -> AsyncIterator[Any]:
    import fakeredis
    from mongomock_motor import AsyncMongoMockClient

    from app.db import mongo, redis

    client = AsyncMongoMockClient(tz_aware=False)
    db = client[f"test_{os.urandom(4).hex()}"]
    mongo.use_database(db)
    r = fakeredis.FakeAsyncRedis(decode_responses=True)
    redis.use_redis(r)
    await mongo.ensure_indexes()
    from app.services.mailer import DEV_OUTBOX

    DEV_OUTBOX.clear()
    yield db
    await r.aclose()


class ApiClient:
    def __init__(self, client: Any) -> None:
        self.c = client
        self.csrf: str | None = None

    async def ensure_csrf(self) -> None:
        # Like the browser frontend, read the (rotating) double-submit token from the cookie jar.
        jar = self.c.cookies.get("dr_csrf")
        if jar:
            self.csrf = jar
            return
        r = await self.c.get("/api/v1/auth/csrf")
        self.csrf = r.json()["csrf_token"]

    async def request(self, method: str, url: str, **kw: Any) -> Any:
        if method.upper() in ("POST", "PUT", "PATCH", "DELETE"):
            await self.ensure_csrf()
            headers = {"x-csrf-token": self.csrf or "", "origin": "http://localhost:3000", **kw.pop("headers", {})}
            kw["headers"] = headers
        return await self.c.request(method, url, **kw)

    async def get(self, url: str, **kw: Any) -> Any:
        return await self.request("GET", url, **kw)

    async def post(self, url: str, **kw: Any) -> Any:
        return await self.request("POST", url, **kw)

    async def put(self, url: str, **kw: Any) -> Any:
        return await self.request("PUT", url, **kw)

    async def patch(self, url: str, **kw: Any) -> Any:
        return await self.request("PATCH", url, **kw)

    async def delete(self, url: str, **kw: Any) -> Any:
        return await self.request("DELETE", url, **kw)

    async def register(self, email: str, password: str = "Str0ng!Passw0rd", name: str = "Test") -> Any:
        return await self.post("/api/v1/auth/register", json={"email": email, "password": password, "name": name})

    async def login(self, email: str, password: str = "Str0ng!Passw0rd") -> Any:
        return await self.post("/api/v1/auth/login", json={"email": email, "password": password})


@pytest.fixture
async def make_client(infra: Any) -> AsyncIterator[Any]:
    import httpx

    from app.main import create_app

    clients: list[httpx.AsyncClient] = []

    async def _make() -> ApiClient:
        app = create_app()
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost:3000")
        clients.append(c)
        return ApiClient(c)

    yield _make
    for c in clients:
        await c.aclose()


@pytest.fixture
async def client(make_client: Any) -> ApiClient:
    return await make_client()


async def make_admin(email: str) -> None:
    from app.db.mongo import Collections, col

    await col(Collections.users).update_one({"email": email}, {"$set": {"role": "ADMIN"}})
