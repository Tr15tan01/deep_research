"""Shared HTTP plumbing for provider adapters: bounded retries and error normalisation."""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.llm.base import ErrorKind, LLMError

_CONTEXT_MARKERS = ("context_length", "context length", "prompt is too long", "maximum context", "too many tokens",
                    "exceeds the maximum number of tokens", "input is too long", "token limit")
_BILLING_MARKERS = ("credit balance", "billing", "payment required", "insufficient funds")
_QUOTA_MARKERS = ("insufficient_quota", "quota", "exceeded your current", "resource_exhausted")


def backoff_delay(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    """Exponential backoff with full jitter."""
    return random.uniform(0, min(cap, base * (2**attempt)))


def _error_text(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        return json.dumps(data)[:2000]
    except Exception:  # noqa: BLE001
        return resp.text[:2000]


def classify_http_error(provider: str, resp: httpx.Response) -> LLMError:
    status = resp.status_code
    text = _error_text(resp)
    low = text.lower()
    retry_after = None
    ra = resp.headers.get("retry-after")
    if ra:
        try:
            retry_after = float(ra)
        except ValueError:
            retry_after = None
    if status in (401,):
        return LLMError(ErrorKind.AUTH, provider=provider, status=status, detail=text)
    if status == 403:
        if any(m in low for m in _BILLING_MARKERS):
            return LLMError(ErrorKind.BILLING, provider=provider, status=status, detail=text)
        return LLMError(ErrorKind.AUTH, provider=provider, status=status, detail=text)
    if status == 404:
        return LLMError(ErrorKind.MODEL_NOT_FOUND, provider=provider, status=status, detail=text)
    if status == 413 or (status == 400 and any(m in low for m in _CONTEXT_MARKERS)):
        return LLMError(ErrorKind.CONTEXT_OVERFLOW, provider=provider, status=status, detail=text)
    if status == 429:
        # Providers that send an explicit retry delay (e.g. Gemini RetryInfo) mean "rate limited, come back later".
        import re as _re

        m = _re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', text)
        if m:
            return LLMError(ErrorKind.RATE_LIMIT, provider=provider, status=status, retry_after=float(m.group(1)), detail=text)
        # Quota exhaustion is not fixed by waiting a few seconds; rate limits are.
        if "insufficient_quota" in low or ("quota" in low and ("billing" in low or "plan" in low or "exceeded your current" in low)):
            return LLMError(ErrorKind.QUOTA, provider=provider, status=status, detail=text)
        return LLMError(ErrorKind.RATE_LIMIT, provider=provider, status=status, retry_after=retry_after, detail=text)
    if status == 402 or any(m in low for m in _BILLING_MARKERS):
        return LLMError(ErrorKind.BILLING, provider=provider, status=status, detail=text)
    if status == 400:
        if "api key not valid" in low or "api_key_invalid" in low or "invalid api key" in low or "invalid x-api-key" in low:
            return LLMError(ErrorKind.AUTH, provider=provider, status=status, detail=text)
        if "safety" in low or "blocked" in low or "content_policy" in low or "content management policy" in low:
            return LLMError(ErrorKind.CONTENT_BLOCKED, provider=provider, status=status, detail=text)
        if "not support" in low or "unsupported" in low or "unknown parameter" in low or "unrecognized" in low:
            return LLMError(ErrorKind.UNSUPPORTED, provider=provider, status=status, detail=text)
        return LLMError(ErrorKind.UNKNOWN, "The AI provider rejected the request.", provider=provider, status=status, detail=text)
    if status in (500, 502, 503, 504, 520, 522, 524, 529):
        return LLMError(ErrorKind.UNAVAILABLE, provider=provider, status=status, retry_after=retry_after, detail=text)
    return LLMError(ErrorKind.UNKNOWN, provider=provider, status=status, detail=text)


async def post_json_with_retries(
    client: httpx.AsyncClient,
    provider: str,
    url: str,
    *,
    json_body: dict[str, Any],
    headers: dict[str, str],
    params: dict[str, str] | None = None,
    attempts: int = 3,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> tuple[dict[str, Any], int]:
    """POST with bounded retries for transient failures. Returns (json, latency_ms)."""
    last: LLMError | None = None
    for attempt in range(attempts):
        started = time.monotonic()
        try:
            resp = await client.post(url, json=json_body, headers=headers, params=params)
        except httpx.TimeoutException as e:
            last = LLMError(ErrorKind.TIMEOUT, provider=provider, detail=type(e).__name__)
        except httpx.TransportError as e:
            last = LLMError(ErrorKind.UNAVAILABLE, provider=provider, detail=type(e).__name__)
        else:
            latency = int((time.monotonic() - started) * 1000)
            if resp.status_code < 400:
                try:
                    return resp.json(), latency
                except ValueError as e:
                    raise LLMError(ErrorKind.BAD_OUTPUT, provider=provider, detail="non-JSON response body") from e
            last = classify_http_error(provider, resp)
        if not last.retryable or attempt == attempts - 1:
            raise last
        delay = last.retry_after if last.retry_after is not None else backoff_delay(attempt)
        await sleep(min(delay, 30.0))
    assert last is not None
    raise last
