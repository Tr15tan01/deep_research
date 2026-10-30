"""Error-tracking hook.

When ``ERROR_TRACKING_DSN`` is set and ``sentry-sdk`` is installed (``pip install sentry-sdk``;
any Sentry-protocol service such as Sentry or GlitchTip works), unhandled API errors and
unexpected worker failures are reported with their reference ID. Event payloads pass
through the same redaction used for logs, and request bodies/cookies are never sent.
Without a DSN this module is a no-op.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger, redact

log = get_logger("tracking")
_enabled = False


def _scrub(event: dict[str, Any], _hint: Any) -> dict[str, Any]:
    req = event.get("request") or {}
    for k in ("cookies", "data", "headers"):
        req.pop(k, None)
    return redact(event)  # type: ignore[no-any-return]


def init_tracking(component: str) -> bool:
    """Initialise once per process. Returns True when reporting is active."""
    global _enabled
    from app.core.config import get_settings

    s = get_settings()
    if not s.ERROR_TRACKING_DSN or _enabled:
        return _enabled
    try:
        import sentry_sdk  # type: ignore[import-not-found]
    except ImportError:
        log.warning("error_tracking_unavailable", note="ERROR_TRACKING_DSN is set but sentry-sdk is not installed")
        return False
    sentry_sdk.init(dsn=s.ERROR_TRACKING_DSN, environment=s.APP_ENV, send_default_pii=False, traces_sample_rate=0.0,
                    before_send=_scrub, server_name=component)
    _enabled = True
    log.info("error_tracking_enabled", component=component)
    return True


def capture(exc: BaseException, **context: Any) -> None:
    if not _enabled:
        return
    try:
        import sentry_sdk  # type: ignore[import-not-found]

        with sentry_sdk.new_scope() as scope:
            for k, v in redact(context).items():
                scope.set_tag(k, str(v)[:200])
            sentry_sdk.capture_exception(exc)
    except Exception:  # noqa: BLE001 — tracking must never break the request or job
        pass
