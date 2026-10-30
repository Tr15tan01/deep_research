"""Structured logging with correlation IDs and secret redaction."""

from __future__ import annotations

import logging
import re
import sys
from contextvars import ContextVar
from typing import Any

import structlog

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)

_SENSITIVE_KEYS = re.compile(
    r"(pass(word)?|secret|token|api[_-]?key|authorization|cookie|set-cookie|credential|session|refresh|access_token|private)",
    re.IGNORECASE,
)
# Patterns that look like credentials even when they appear inside free text.
_SENSITIVE_VALUES = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),  # OpenAI-style
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}"),  # Anthropic-style
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),  # Google API key
    re.compile(r"fc-[A-Za-z0-9]{20,}"),  # Firecrawl
    re.compile(r"tvly-[A-Za-z0-9\-]{16,}"),  # Tavily
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWT
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{12,}"),
]
_QUERY_SECRET = re.compile(r"(?i)([?&](?:key|api_key|apikey|token|access_token|code|state)=)[^&\s\"']+")
REDACTED = "[REDACTED]"


def redact_text(text: str) -> str:
    out = _QUERY_SECRET.sub(lambda m: m.group(1) + REDACTED, text)
    for pat in _SENSITIVE_VALUES:
        out = pat.sub(REDACTED, out)
    return out


def redact(value: Any, key: str | None = None, depth: int = 0) -> Any:
    if depth > 8:
        return "…"
    if key is not None and _SENSITIVE_KEYS.search(key) and not key.endswith(("_count", "_tokens", "tokens")):
        return REDACTED if value not in (None, "", False) else value
    if isinstance(value, dict):
        return {k: redact(v, str(k), depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, None, depth + 1) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def _redact_processor(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    return {k: (redact(v, k) if k not in ("event", "level", "timestamp", "logger") else v) for k, v in event_dict.items()} | {
        "event": redact_text(str(event_dict.get("event", "")))
    }


def _add_correlation(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    cid = correlation_id_var.get()
    if cid and "correlation_id" not in event_dict:
        event_dict["correlation_id"] = cid
    return event_dict


def configure_logging(level: str = "INFO", json_logs: bool = False) -> None:
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_correlation,
        structlog.processors.format_exc_info,
        _redact_processor,
    ]
    renderer: Any = structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer(colors=False)
    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), stream=sys.stdout, format="%(levelname)s %(name)s %(message)s")
    # Third-party loggers can echo URLs with credentials; keep them quiet.
    for noisy in ("httpx", "httpcore", "pymongo", "trafilatura", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str = "app") -> Any:
    return structlog.get_logger(name)
