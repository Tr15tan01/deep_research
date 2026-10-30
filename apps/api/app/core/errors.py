"""Application error taxonomy and FastAPI exception handlers.

Every error response has the shape::

    {"error": {"code": "...", "message": "...", "reference_id": "...", "details": {...}}}

Stack traces are never returned to clients; the ``reference_id`` correlates the response
with server logs.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import correlation_id_var, get_logger

log = get_logger("errors")


class AppError(Exception):
    status_code = 400
    code = "bad_request"
    message = "The request could not be processed."

    def __init__(self, message: str | None = None, *, code: str | None = None, status_code: int | None = None,
                 details: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details or {}
        self.headers = headers


class NotAuthenticated(AppError):
    status_code = 401
    code = "not_authenticated"
    message = "Please sign in to continue."


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"
    message = "You do not have permission to perform this action."


class NotFound(AppError):
    status_code = 404
    code = "not_found"
    message = "The requested resource was not found."


class Conflict(AppError):
    status_code = 409
    code = "conflict"
    message = "The request conflicts with the current state."


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many requests. Please wait and try again."


class FeatureDisabled(AppError):
    status_code = 404
    code = "feature_disabled"
    message = "This feature is not enabled."


class LimitExceeded(AppError):
    status_code = 402
    code = "limit_exceeded"
    message = "You have reached a usage limit."


class ServiceUnavailable(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "A required service is temporarily unavailable. Please try again shortly."


class ConfigurationRequired(AppError):
    status_code = 503
    code = "configuration_required"
    message = "This feature needs to be configured by an administrator."


def new_reference_id() -> str:
    return correlation_id_var.get() or uuid.uuid4().hex[:16]


def _body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "reference_id": new_reference_id(), "details": details or {}}}


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_req: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            log.warning("app_error", code=exc.code, message=exc.message)
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_req: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": [str(p) for p in e.get("loc", [])], "msg": e.get("msg", "invalid"), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return JSONResponse(_body("validation_error", "Some fields are invalid.", {"errors": errors}), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_req: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed", 401: "not_authenticated", 403: "forbidden"}.get(exc.status_code, "http_error")
        msg = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(_body(code, msg), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_req: Request, exc: Exception) -> JSONResponse:
        ref = new_reference_id()
        log.exception("unhandled_error", reference_id=ref, error_type=type(exc).__name__)
        from app.core.tracking import capture

        capture(exc, reference_id=ref, path=_req.url.path)
        body = {"error": {"code": "internal_error", "message": "Something went wrong on our side. Please try again.",
                          "reference_id": ref, "details": {}}}
        return JSONResponse(body, status_code=500)
