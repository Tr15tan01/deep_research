"""Provider-independent LLM interface and normalised error taxonomy."""

from __future__ import annotations

import enum
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


class ErrorKind(str, enum.Enum):
    AUTH = "invalid_credentials"
    QUOTA = "quota_exhausted"
    BILLING = "billing_exhausted"
    RATE_LIMIT = "rate_limited"
    UNAVAILABLE = "provider_unavailable"
    TIMEOUT = "timeout"
    BAD_OUTPUT = "malformed_output"
    CONTEXT_OVERFLOW = "context_overflow"
    UNSUPPORTED = "unsupported_capability"
    MODEL_NOT_FOUND = "model_not_found"
    NOT_CONFIGURED = "not_configured"
    CONTENT_BLOCKED = "content_blocked"
    BUDGET = "budget_exhausted"
    UNKNOWN = "unknown_error"


RETRYABLE = {ErrorKind.RATE_LIMIT, ErrorKind.UNAVAILABLE, ErrorKind.TIMEOUT, ErrorKind.BAD_OUTPUT}
# Errors where an explicitly configured fallback provider may be tried.
FALLBACK_ELIGIBLE = {ErrorKind.RATE_LIMIT, ErrorKind.UNAVAILABLE, ErrorKind.TIMEOUT, ErrorKind.QUOTA,
                     ErrorKind.BILLING, ErrorKind.AUTH, ErrorKind.MODEL_NOT_FOUND, ErrorKind.UNSUPPORTED}

USER_MESSAGES: dict[ErrorKind, str] = {
    ErrorKind.AUTH: "The AI provider rejected the configured API key. An administrator needs to update the credentials.",
    ErrorKind.QUOTA: "The AI provider quota is exhausted. Research is paused until the quota resets or is increased.",
    ErrorKind.BILLING: "The AI provider account has no remaining credit. An administrator needs to resolve billing.",
    ErrorKind.RATE_LIMIT: "The AI provider is rate limiting requests. We will retry automatically.",
    ErrorKind.UNAVAILABLE: "The AI provider is temporarily unavailable. We will retry automatically.",
    ErrorKind.TIMEOUT: "The AI provider took too long to respond. We will retry automatically.",
    ErrorKind.BAD_OUTPUT: "The AI model returned output that could not be parsed.",
    ErrorKind.CONTEXT_OVERFLOW: "The request exceeded the model's context window.",
    ErrorKind.UNSUPPORTED: "The selected model does not support a capability this step needs.",
    ErrorKind.MODEL_NOT_FOUND: "The configured model ID was not found at the provider. Check the exact model ID.",
    ErrorKind.NOT_CONFIGURED: "No AI provider is configured. An administrator must configure a provider and model.",
    ErrorKind.CONTENT_BLOCKED: "The AI provider declined to process this content.",
    ErrorKind.BUDGET: "This research reached its configured cost or token budget.",
    ErrorKind.UNKNOWN: "The AI provider returned an unexpected error.",
}


class LLMError(Exception):
    def __init__(self, kind: ErrorKind, message: str | None = None, *, provider: str = "", status: int | None = None,
                 retry_after: float | None = None, detail: str = "") -> None:
        self.kind = kind
        self.provider = provider
        self.status = status
        self.retry_after = retry_after
        self.detail = detail[:500]
        self.user_message = message or USER_MESSAGES[kind]
        super().__init__(f"{provider}:{kind.value}:{status}:{self.detail}")

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    reported: bool = False  # True when the provider reported usage (vs. our estimate)


class LLMRequest(BaseModel):
    messages: list[Message]
    max_output_tokens: int = 2048
    temperature: float | None = 0.2
    json_schema: dict[str, Any] | None = None
    schema_name: str = "output"
    task: str = "general"
    # Never sent to a provider. Carries structured context for the deterministic demo provider.
    metadata: dict[str, Any] = Field(default_factory=dict, exclude=True)


class LLMResult(BaseModel):
    text: str
    parsed: Any | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    provider: str
    model: str
    finish_reason: str | None = None
    latency_ms: int = 0


class ModelInfo(BaseModel):
    id: str
    display_name: str | None = None
    context_window: int | None = None
    max_output_tokens: int | None = None
    source: str = "provider"


@dataclass
class ModelCapabilities:
    context_window: int = 32_000
    max_output_tokens: int = 4_096
    supports_json_schema: bool = False
    supports_tools: bool = False
    supports_streaming: bool = True
    supports_temperature: bool = True
    supports_system_prompt: bool = True
    source: str = "default"  # default | discovered | admin
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ("context_window", "max_output_tokens", "supports_json_schema",
                                               "supports_tools", "supports_streaming", "supports_temperature",
                                               "supports_system_prompt", "source", "notes")}


class LLMProvider(Protocol):
    name: str

    async def generate(self, req: LLMRequest, model: str, caps: ModelCapabilities) -> LLMResult: ...

    def stream(self, req: LLMRequest, model: str, caps: ModelCapabilities) -> AsyncIterator[str]: ...

    async def list_models(self) -> list[ModelInfo]: ...


def estimate_tokens(text: str) -> int:
    # Conservative heuristic (~4 chars/token for English, rounded up); used only for budgeting.
    return max(1, (len(text) + 3) // 4)


def estimate_request_tokens(req: LLMRequest) -> int:
    return sum(estimate_tokens(m.content) + 4 for m in req.messages) + (
        estimate_tokens(str(req.json_schema)) if req.json_schema else 0)
