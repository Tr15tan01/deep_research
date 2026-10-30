"""REST adapters for OpenAI, OpenAI-compatible, Anthropic and Google Gemini.

The adapters talk to each vendor's documented HTTP API directly (stable, versioned
endpoints) through one ``httpx`` client per adapter. This keeps timeouts, retries and
error normalisation uniform and makes every adapter testable with HTTP mocks.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.llm.base import (
    ErrorKind,
    LLMError,
    LLMRequest,
    LLMResult,
    Message,
    ModelCapabilities,
    ModelInfo,
    TokenUsage,
    estimate_request_tokens,
    estimate_tokens,
)
from app.llm.http_common import classify_http_error, post_json_with_retries


def _split_system(messages: list[Message]) -> tuple[str, list[Message]]:
    system = "\n\n".join(m.content for m in messages if m.role == "system")
    rest = [m for m in messages if m.role != "system"]
    return system, rest


def _json_instruction(req: LLMRequest) -> str:
    return ("\n\nRespond with a single JSON object only (no prose, no code fences) that validates against this JSON "
            "schema:\n" + json.dumps(req.json_schema, separators=(",", ":")))


class _Base:
    name = "base"

    def __init__(self, api_key: str, *, timeout: float = 120.0, client: httpx.AsyncClient | None = None) -> None:
        if not api_key:
            raise LLMError(ErrorKind.NOT_CONFIGURED, provider=self.name)
        self.api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0))

    async def aclose(self) -> None:
        await self._client.aclose()


# --------------------------------------------------------------------------------------------
class OpenAIProvider(_Base):
    """OpenAI Chat Completions API. Also used for OpenAI-compatible servers via ``base_url``."""

    name = "openai"

    def __init__(self, api_key: str, *, base_url: str = "https://api.openai.com/v1", name: str = "openai",
                 timeout: float = 120.0, client: httpx.AsyncClient | None = None) -> None:
        self.name = name
        super().__init__(api_key, timeout=timeout, client=client)
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _body(self, req: LLMRequest, model: str, caps: ModelCapabilities, stream: bool = False) -> dict[str, Any]:
        msgs = list(req.messages)
        if req.json_schema and not caps.supports_json_schema:
            msgs = [*msgs[:-1], Message(role=msgs[-1].role, content=msgs[-1].content + _json_instruction(req))]
        if not caps.supports_system_prompt:
            system, rest = _split_system(msgs)
            if system and rest:
                rest[0] = Message(role=rest[0].role, content=system + "\n\n" + rest[0].content)
            msgs = rest
        body: dict[str, Any] = {"model": model, "messages": [m.model_dump() for m in msgs]}
        # OpenAI's current parameter is max_completion_tokens; many compatible servers only accept max_tokens.
        body["max_completion_tokens" if self.name == "openai" else "max_tokens"] = min(req.max_output_tokens, caps.max_output_tokens)
        if caps.supports_temperature and req.temperature is not None:
            body["temperature"] = req.temperature
        if req.json_schema and caps.supports_json_schema:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": req.schema_name[:64], "schema": req.json_schema, "strict": False}}
        if stream:
            body["stream"] = True
            if self.name == "openai":
                body["stream_options"] = {"include_usage": True}
        return body

    async def generate(self, req: LLMRequest, model: str, caps: ModelCapabilities) -> LLMResult:
        data, latency = await post_json_with_retries(self._client, self.name, f"{self.base_url}/chat/completions",
                                                     json_body=self._body(req, model, caps), headers=self._headers())
        choices = data.get("choices") or []
        if not choices:
            raise LLMError(ErrorKind.BAD_OUTPUT, provider=self.name, detail="no choices")
        msg = choices[0].get("message") or {}
        if msg.get("refusal"):
            raise LLMError(ErrorKind.CONTENT_BLOCKED, provider=self.name, detail=str(msg.get("refusal"))[:300])
        finish = choices[0].get("finish_reason")
        if finish == "content_filter":
            raise LLMError(ErrorKind.CONTENT_BLOCKED, provider=self.name)
        text = msg.get("content") or ""
        u = data.get("usage") or {}
        usage = TokenUsage(input_tokens=int(u.get("prompt_tokens", 0)), output_tokens=int(u.get("completion_tokens", 0)),
                           reported=bool(u))
        if not usage.reported:
            usage = TokenUsage(input_tokens=estimate_request_tokens(req), output_tokens=estimate_tokens(text))
        return LLMResult(text=text, usage=usage, provider=self.name, model=data.get("model", model),
                         finish_reason=finish, latency_ms=latency)

    async def stream(self, req: LLMRequest, model: str, caps: ModelCapabilities) -> AsyncIterator[str]:
        if not caps.supports_streaming:
            raise LLMError(ErrorKind.UNSUPPORTED, provider=self.name, detail="streaming")
        async with self._client.stream("POST", f"{self.base_url}/chat/completions", headers=self._headers(),
                                       json=self._body(req, model, caps, stream=True)) as resp:
            if resp.status_code >= 400:
                await resp.aread()
                raise classify_http_error(self.name, resp)
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except ValueError:
                    continue
                for ch in chunk.get("choices") or []:
                    delta = (ch.get("delta") or {}).get("content")
                    if delta:
                        yield delta

    async def list_models(self) -> list[ModelInfo]:
        try:
            resp = await self._client.get(f"{self.base_url}/models", headers=self._headers())
        except httpx.TimeoutException as e:
            raise LLMError(ErrorKind.TIMEOUT, provider=self.name) from e
        except httpx.TransportError as e:
            raise LLMError(ErrorKind.UNAVAILABLE, provider=self.name, detail=type(e).__name__) from e
        if resp.status_code >= 400:
            raise classify_http_error(self.name, resp)
        items = resp.json().get("data") or []
        return sorted((ModelInfo(id=str(m["id"])) for m in items if m.get("id")), key=lambda m: m.id)


# --------------------------------------------------------------------------------------------
class AnthropicProvider(_Base):
    """Anthropic Messages API. Structured output uses a forced tool call (input_schema)."""

    name = "anthropic"
    API_VERSION = "2023-06-01"

    def __init__(self, api_key: str, *, base_url: str = "https://api.anthropic.com/v1", timeout: float = 120.0,
                 client: httpx.AsyncClient | None = None) -> None:
        super().__init__(api_key, timeout=timeout, client=client)
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key, "anthropic-version": self.API_VERSION, "content-type": "application/json"}

    def _body(self, req: LLMRequest, model: str, caps: ModelCapabilities, stream: bool = False) -> dict[str, Any]:
        system, rest = _split_system(req.messages)
        # Anthropic requires alternating turns starting with "user".
        merged: list[dict[str, str]] = []
        for m in rest:
            if merged and merged[-1]["role"] == m.role:
                merged[-1]["content"] += "\n\n" + m.content
            else:
                merged.append({"role": m.role, "content": m.content})
        if not merged or merged[0]["role"] != "user":
            merged.insert(0, {"role": "user", "content": "Continue."})
        body: dict[str, Any] = {"model": model, "max_tokens": min(req.max_output_tokens, caps.max_output_tokens),
                                "messages": merged}
        if system:
            body["system"] = system
        if caps.supports_temperature and req.temperature is not None:
            body["temperature"] = req.temperature
        if req.json_schema:
            if caps.supports_tools:
                tool_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in req.schema_name)[:64] or "output"
                schema = req.json_schema if req.json_schema.get("type") == "object" else {
                    "type": "object", "properties": {"value": req.json_schema}, "required": ["value"]}
                body["tools"] = [{"name": tool_name, "description": "Return the structured result.", "input_schema": schema}]
                body["tool_choice"] = {"type": "tool", "name": tool_name}
            else:
                body["messages"][-1]["content"] += _json_instruction(req)
        if stream:
            body["stream"] = True
        return body

    async def generate(self, req: LLMRequest, model: str, caps: ModelCapabilities) -> LLMResult:
        data, latency = await post_json_with_retries(self._client, self.name, f"{self.base_url}/messages",
                                                     json_body=self._body(req, model, caps), headers=self._headers())
        if data.get("type") == "error":
            raise LLMError(ErrorKind.UNKNOWN, provider=self.name, detail=json.dumps(data)[:300])
        text_parts: list[str] = []
        parsed: Any = None
        for block in data.get("content") or []:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                parsed = block.get("input")
                if req.json_schema and req.json_schema.get("type") != "object" and isinstance(parsed, dict):
                    parsed = parsed.get("value")
        if data.get("stop_reason") == "refusal":
            raise LLMError(ErrorKind.CONTENT_BLOCKED, provider=self.name)
        text = "".join(text_parts) if parsed is None else json.dumps(parsed)
        u = data.get("usage") or {}
        usage = TokenUsage(input_tokens=int(u.get("input_tokens", 0)) + int(u.get("cache_read_input_tokens", 0) or 0)
                           + int(u.get("cache_creation_input_tokens", 0) or 0),
                           output_tokens=int(u.get("output_tokens", 0)), reported=bool(u))
        return LLMResult(text=text, parsed=parsed, usage=usage, provider=self.name, model=data.get("model", model),
                         finish_reason=data.get("stop_reason"), latency_ms=latency)

    async def stream(self, req: LLMRequest, model: str, caps: ModelCapabilities) -> AsyncIterator[str]:
        async with self._client.stream("POST", f"{self.base_url}/messages", headers=self._headers(),
                                       json=self._body(req, model, caps, stream=True)) as resp:
            if resp.status_code >= 400:
                await resp.aread()
                raise classify_http_error(self.name, resp)
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    evt = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if evt.get("type") == "content_block_delta":
                    delta = evt.get("delta") or {}
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        yield delta["text"]
                elif evt.get("type") == "error":
                    raise LLMError(ErrorKind.UNAVAILABLE, provider=self.name, detail=json.dumps(evt)[:300])

    async def list_models(self) -> list[ModelInfo]:
        try:
            resp = await self._client.get(f"{self.base_url}/models", headers=self._headers(), params={"limit": "1000"})
        except httpx.TimeoutException as e:
            raise LLMError(ErrorKind.TIMEOUT, provider=self.name) from e
        except httpx.TransportError as e:
            raise LLMError(ErrorKind.UNAVAILABLE, provider=self.name, detail=type(e).__name__) from e
        if resp.status_code >= 400:
            raise classify_http_error(self.name, resp)
        out = []
        for m in resp.json().get("data") or []:
            out.append(ModelInfo(id=m["id"], display_name=m.get("display_name"),
                                 context_window=m.get("max_input_tokens"), max_output_tokens=m.get("max_tokens")))
        return out


# --------------------------------------------------------------------------------------------
class GeminiProvider(_Base):
    """Google Gemini API (Generative Language API, v1beta)."""

    name = "gemini"

    def __init__(self, api_key: str, *, base_url: str = "https://generativelanguage.googleapis.com/v1beta",
                 timeout: float = 120.0, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(api_key, timeout=timeout, client=client)
        self.base_url = base_url.rstrip("/")

    @staticmethod
    def _model_path(model: str) -> str:
        return model if model.startswith("models/") else f"models/{model}"

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

    def _body(self, req: LLMRequest, caps: ModelCapabilities) -> dict[str, Any]:
        system, rest = _split_system(req.messages)
        contents = [{"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]} for m in rest]
        gen: dict[str, Any] = {"maxOutputTokens": min(req.max_output_tokens, caps.max_output_tokens)}
        if caps.supports_temperature and req.temperature is not None:
            gen["temperature"] = req.temperature
        if req.json_schema:
            gen["responseMimeType"] = "application/json"
            if caps.supports_json_schema:
                gen["responseJsonSchema"] = req.json_schema
            elif contents:
                contents[-1]["parts"][0]["text"] += _json_instruction(req)
        body: dict[str, Any] = {"contents": contents, "generationConfig": gen}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return body

    @staticmethod
    def _text(cand: dict[str, Any]) -> str:
        parts = (cand.get("content") or {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts if not p.get("thought"))

    async def generate(self, req: LLMRequest, model: str, caps: ModelCapabilities) -> LLMResult:
        url = f"{self.base_url}/{self._model_path(model)}:generateContent"
        data, latency = await post_json_with_retries(self._client, self.name, url, json_body=self._body(req, caps),
                                                     headers=self._headers())
        fb = data.get("promptFeedback") or {}
        if fb.get("blockReason"):
            raise LLMError(ErrorKind.CONTENT_BLOCKED, provider=self.name, detail=str(fb.get("blockReason")))
        cands = data.get("candidates") or []
        if not cands:
            raise LLMError(ErrorKind.BAD_OUTPUT, provider=self.name, detail="no candidates")
        finish = cands[0].get("finishReason")
        if finish in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"):
            raise LLMError(ErrorKind.CONTENT_BLOCKED, provider=self.name, detail=str(finish))
        text = self._text(cands[0])
        um = data.get("usageMetadata") or {}
        usage = TokenUsage(input_tokens=int(um.get("promptTokenCount", 0)),
                           output_tokens=int(um.get("candidatesTokenCount", 0)) + int(um.get("thoughtsTokenCount", 0)),
                           reported=bool(um))
        return LLMResult(text=text, usage=usage, provider=self.name, model=data.get("modelVersion", model),
                         finish_reason=finish, latency_ms=latency)

    async def stream(self, req: LLMRequest, model: str, caps: ModelCapabilities) -> AsyncIterator[str]:
        url = f"{self.base_url}/{self._model_path(model)}:streamGenerateContent"
        async with self._client.stream("POST", url, headers=self._headers(), params={"alt": "sse"},
                                       json=self._body(req, caps)) as resp:
            if resp.status_code >= 400:
                await resp.aread()
                raise classify_http_error(self.name, resp)
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    chunk = json.loads(line[5:].strip())
                except ValueError:
                    continue
                for cand in chunk.get("candidates") or []:
                    t = self._text(cand)
                    if t:
                        yield t

    async def list_models(self) -> list[ModelInfo]:
        out: list[ModelInfo] = []
        page_token = None
        for _ in range(10):
            params = {"pageSize": "200"}
            if page_token:
                params["pageToken"] = page_token
            try:
                resp = await self._client.get(f"{self.base_url}/models", headers=self._headers(), params=params)
            except httpx.TimeoutException as e:
                raise LLMError(ErrorKind.TIMEOUT, provider=self.name) from e
            except httpx.TransportError as e:
                raise LLMError(ErrorKind.UNAVAILABLE, provider=self.name, detail=type(e).__name__) from e
            if resp.status_code >= 400:
                raise classify_http_error(self.name, resp)
            data = resp.json()
            for m in data.get("models") or []:
                if "generateContent" not in (m.get("supportedGenerationMethods") or []):
                    continue
                out.append(ModelInfo(id=str(m["name"]).removeprefix("models/"), display_name=m.get("displayName"),
                                     context_window=m.get("inputTokenLimit"), max_output_tokens=m.get("outputTokenLimit")))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return out


def _now_ms() -> int:
    return int(time.time() * 1000)
