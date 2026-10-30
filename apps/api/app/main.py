"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, billing, research, system, uploads, user
from app.auth import routes as auth_routes
from app.auth.deps import CSRFMiddleware
from app.core.config import get_settings
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging, correlation_id_var, get_logger

log = get_logger("app")


class RequestContextMiddleware:
    """Correlation IDs + security headers, as pure ASGI (safe for SSE streaming)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id", b"").decode()[:64]
        cid = incoming if incoming and incoming.replace("-", "").isalnum() else uuid.uuid4().hex[:16]
        token = correlation_id_var.set(cid)
        secure = get_settings().secure_cookies

        async def send_wrapper(message: Any) -> None:
            if message["type"] == "http.response.start":
                hdrs = list(message.get("headers") or [])
                extra = [
                    (b"x-request-id", cid.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'"),
                    (b"cross-origin-opener-policy", b"same-origin"),
                ]
                if secure:
                    extra.append((b"strict-transport-security", b"max-age=63072000; includeSubDomains"))
                existing = {k.lower() for k, _ in hdrs}
                hdrs.extend(h for h in extra if h[0] not in existing)
                if scope["path"].startswith("/api/") and b"cache-control" not in existing:
                    hdrs.append((b"cache-control", b"no-store"))
                message["headers"] = hdrs
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            correlation_id_var.reset(token)


class InternalTokenMiddleware:
    """When INTERNAL_PROXY_TOKEN is set, only callers presenting it (the web app's proxy) may use the API.
    Health checks stay open for the hosting platform. Pure ASGI, so SSE streaming is unaffected."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        token = get_settings().INTERNAL_PROXY_TOKEN
        if scope["type"] != "http" or not token or scope["path"].startswith("/health/"):
            await self.app(scope, receive, send)
            return
        import hmac
        import json

        presented = dict(scope.get("headers") or []).get(b"x-internal-token", b"")
        if hmac.compare_digest(presented, token.encode()):
            await self.app(scope, receive, send)
            return
        body = json.dumps({"error": {"code": "forbidden", "message": "Direct API access is not allowed.",
                                     "reference_id": correlation_id_var.get() or "", "details": {}}}).encode()
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


async def _maintenance_loop(stop: asyncio.Event) -> None:
    from app.api.uploads import purge_expired_uploads

    while not stop.is_set():
        try:
            n = await purge_expired_uploads()
            if n:
                log.info("purged_expired_uploads", count=n)
        except Exception as e:  # noqa: BLE001
            log.warning("maintenance_failed", error=type(e).__name__)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=3600)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from app.db.mongo import close, connect, ensure_indexes, get_db
    from app.db.redis import close_redis, connect_redis, get_redis

    s = get_settings()
    configure_logging(s.LOG_LEVEL, s.log_json)
    from app.core.tracking import init_tracking

    init_tracking("api")
    for w in s.config_warnings:
        log.warning("config_warning", message=w)
    owns_db = False
    try:
        get_db()
    except RuntimeError:
        await connect()
        owns_db = True
    await ensure_indexes()
    try:
        get_redis()
    except RuntimeError:
        await connect_redis()
    stop = asyncio.Event()
    tasks: list[asyncio.Task[Any]] = [asyncio.create_task(_maintenance_loop(stop))]
    worker = None
    if s.EMBEDDED_WORKER:
        from app.jobs.worker import Worker

        worker = Worker()
        tasks.append(asyncio.create_task(worker.run(install_signals=False)))
        log.warning("embedded_worker_started", note="jobs run inside the API process (single-service mode)")
    log.info("api_started", env=s.APP_ENV, demo_mode=s.DEMO_MODE)
    try:
        yield
    finally:
        stop.set()
        if worker:
            worker.stopping.set()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if owns_db:
            await close()
            await close_redis()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=f"{s.APP_NAME} API", version="1.0.0", lifespan=lifespan,
                  docs_url=None if s.is_production else "/docs", redoc_url=None,
                  openapi_url=None if s.is_production else "/openapi.json")
    install_exception_handlers(app)
    # Order: last added runs first. Context → CORS → CSRF → routes.
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(InternalTokenMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                       allow_headers=["content-type", "x-csrf-token", "idempotency-key", "last-event-id", "x-request-id"],
                       expose_headers=["x-request-id", "retry-after"], max_age=600)
    app.add_middleware(RequestContextMiddleware)
    for r in (system.router, auth_routes.router, research.router, research.shared_router, uploads.router, user.router,
              admin.router, billing.router):
        app.include_router(r)
    return app


app = create_app()
