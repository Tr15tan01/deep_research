"""Provider adapters against mocked HTTP APIs (respx). These verify request shapes, response
parsing and error normalisation; they are NOT live integration tests (see test_live.py)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.llm.base import ErrorKind, LLMError, LLMRequest, Message, ModelCapabilities
from app.llm.providers import AnthropicProvider, GeminiProvider, OpenAIProvider

CAPS = ModelCapabilities(context_window=100_000, max_output_tokens=4096, supports_json_schema=True, supports_tools=True)
REQ = LLMRequest(messages=[Message(role="system", content="sys"), Message(role="user", content="hi")], max_output_tokens=100)
SCHEMA_REQ = REQ.model_copy(update={"json_schema": {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]},
                                    "schema_name": "Out"})


async def _no_sleep(_: float) -> None:
    return None


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.llm.http_common as hc

    original = hc.post_json_with_retries

    async def patched(*a: Any, **kw: Any) -> Any:
        kw["sleep"] = _no_sleep
        return await original(*a, **kw)

    monkeypatch.setattr("app.llm.providers.post_json_with_retries", patched)


@respx.mock
async def test_openai_success_and_schema() -> None:
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, json={
        "model": "m-1", "choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 3}}))
    p = OpenAIProvider("sk-test")
    res = await p.generate(SCHEMA_REQ, "m-1", CAPS)
    body = route.calls[0].request.content.decode()
    assert '"max_completion_tokens":100' in body.replace(" ", "")
    assert '"response_format"' in body and '"json_schema"' in body
    assert route.calls[0].request.headers["authorization"] == "Bearer sk-test"
    assert res.text == '{"a": 1}' and res.usage.input_tokens == 11 and res.usage.reported


@respx.mock
async def test_openai_compatible_uses_max_tokens_and_prompt_json() -> None:
    route = respx.post("https://llm.internal.example/v1/chat/completions").mock(return_value=httpx.Response(200, json={
        "choices": [{"message": {"content": '{"a": 2}'}}]}))
    p = OpenAIProvider("k", base_url="https://llm.internal.example/v1", name="openai_compatible")
    caps = ModelCapabilities(supports_json_schema=False)
    res = await p.generate(SCHEMA_REQ, "local-model", caps)
    body = route.calls[0].request.content.decode()
    assert '"max_tokens"' in body and "response_format" not in body and "JSON schema" in body
    assert not res.usage.reported and res.usage.input_tokens > 0  # estimated when not reported


@pytest.mark.parametrize("status,payload,kind", [
    (401, {"error": {"message": "Incorrect API key"}}, ErrorKind.AUTH),
    (429, {"error": {"code": "insufficient_quota", "message": "You exceeded your current quota, please check your plan and billing"}}, ErrorKind.QUOTA),
    (400, {"error": {"code": "context_length_exceeded", "message": "maximum context length"}}, ErrorKind.CONTEXT_OVERFLOW),
    (404, {"error": {"message": "The model does not exist"}}, ErrorKind.MODEL_NOT_FOUND),
])
@respx.mock
async def test_openai_error_mapping(status: int, payload: dict, kind: ErrorKind) -> None:
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(status, json=payload))
    with pytest.raises(LLMError) as ei:
        await OpenAIProvider("sk").generate(REQ, "m", CAPS)
    assert ei.value.kind == kind
    assert route.call_count == 1  # non-retryable errors are never retried


@respx.mock
async def test_rate_limit_retried_then_succeeds() -> None:
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=[
        httpx.Response(429, json={"error": {"message": "Rate limit reached"}}, headers={"retry-after": "1"}),
        httpx.Response(503, json={"error": {"message": "overloaded"}}),
        httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}),
    ])
    res = await OpenAIProvider("sk").generate(REQ, "m", CAPS)
    assert res.text == "ok" and route.call_count == 3


@respx.mock
async def test_retries_are_bounded() -> None:
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(500, json={}))
    with pytest.raises(LLMError) as ei:
        await OpenAIProvider("sk").generate(REQ, "m", CAPS)
    assert ei.value.kind == ErrorKind.UNAVAILABLE and route.call_count == 3


@respx.mock
async def test_timeout_normalised() -> None:
    respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(LLMError) as ei:
        await OpenAIProvider("sk").generate(REQ, "m", CAPS)
    assert ei.value.kind == ErrorKind.TIMEOUT and ei.value.retryable


@respx.mock
async def test_anthropic_tool_forcing_for_structured_output() -> None:
    route = respx.post("https://api.anthropic.com/v1/messages").mock(return_value=httpx.Response(200, json={
        "model": "claude-x", "stop_reason": "tool_use",
        "content": [{"type": "tool_use", "name": "Out", "input": {"a": 5}}],
        "usage": {"input_tokens": 20, "output_tokens": 7}}))
    res = await AnthropicProvider("sk-ant").generate(SCHEMA_REQ, "claude-x", CAPS)
    req = route.calls[0].request
    assert req.headers["x-api-key"] == "sk-ant" and req.headers["anthropic-version"] == "2023-06-01"
    body = req.content.decode()
    assert '"tool_choice"' in body and '"system":"sys"' in body.replace(" ", "")
    assert res.parsed == {"a": 5} and res.usage.output_tokens == 7


@respx.mock
async def test_anthropic_overloaded_and_billing() -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(side_effect=[
        httpx.Response(529, json={"type": "error", "error": {"type": "overloaded_error"}}),
        httpx.Response(529, json={"type": "error", "error": {"type": "overloaded_error"}}),
        httpx.Response(529, json={"type": "error", "error": {"type": "overloaded_error"}}),
    ])
    with pytest.raises(LLMError) as ei:
        await AnthropicProvider("k").generate(REQ, "m", CAPS)
    assert ei.value.kind == ErrorKind.UNAVAILABLE
    respx.post("https://api.anthropic.com/v1/messages").mock(return_value=httpx.Response(400, json={
        "type": "error", "error": {"message": "Your credit balance is too low to access the Anthropic API."}}))
    with pytest.raises(LLMError) as ei:
        await AnthropicProvider("k").generate(REQ, "m", CAPS)
    assert ei.value.kind == ErrorKind.BILLING and not ei.value.retryable


@respx.mock
async def test_gemini_parsing_safety_and_retry_delay() -> None:
    route = respx.post("https://generativelanguage.googleapis.com/v1beta/models/gem-1:generateContent").mock(side_effect=[
        httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED", "message": "You exceeded your current quota",
                                            "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "0s"}]}}),
        httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "thinking", "thought": True}, {"text": '{"a":3}'}]},
                                                  "finishReason": "STOP"}],
                                  "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 4, "thoughtsTokenCount": 6}}),
    ])
    res = await GeminiProvider("AIzaTEST").generate(SCHEMA_REQ, "models/gem-1", CAPS)
    assert res.text == '{"a":3}' and res.usage.output_tokens == 10
    body = route.calls[1].request.content.decode()
    assert '"responseJsonSchema"' in body and '"systemInstruction"' in body
    assert route.calls[1].request.headers["x-goog-api-key"] == "AIzaTEST"
    respx.post("https://generativelanguage.googleapis.com/v1beta/models/gem-1:generateContent").mock(
        return_value=httpx.Response(200, json={"candidates": [{"finishReason": "SAFETY"}]}))
    with pytest.raises(LLMError) as ei:
        await GeminiProvider("k").generate(REQ, "gem-1", CAPS)
    assert ei.value.kind == ErrorKind.CONTENT_BLOCKED


@respx.mock
async def test_gemini_model_discovery() -> None:
    respx.get("https://generativelanguage.googleapis.com/v1beta/models").mock(return_value=httpx.Response(200, json={
        "models": [{"name": "models/gem-a", "displayName": "A", "inputTokenLimit": 1048576, "outputTokenLimit": 65536,
                    "supportedGenerationMethods": ["generateContent"]},
                   {"name": "models/embed", "supportedGenerationMethods": ["embedContent"]}]}))
    models = await GeminiProvider("k").list_models()
    assert [m.id for m in models] == ["gem-a"] and models[0].context_window == 1048576


async def test_structured_output_repair_and_failure(infra: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import BaseModel

    from app.llm.base import LLMResult
    from app.llm.config_store import AIConfig, ModelRef
    from app.llm.service import AIService

    class Out(BaseModel):
        a: int

    outputs = iter(['not json at all', '{"a": 7}'])

    class Fake:
        async def generate(self, req: Any, model: str, caps: Any) -> LLMResult:
            return LLMResult(text=next(outputs), provider="openai", model=model)

    svc = AIService(cfg=AIConfig(default=ModelRef(provider="openai", model="m")))
    svc._providers["openai"] = Fake()
    out = await svc.structured("planning", [Message(role="user", content="x")], Out)
    assert out.a == 7
    outputs = iter(["bad", "still bad"])
    with pytest.raises(LLMError) as ei:
        await svc.structured("planning", [Message(role="user", content="x")], Out)
    assert ei.value.kind == ErrorKind.BAD_OUTPUT


async def test_fallback_is_explicit_and_recorded(infra: Any) -> None:
    from app.llm.base import LLMResult
    from app.llm.config_store import AIConfig, ModelRef
    from app.llm.service import AIService

    class Down:
        async def generate(self, req: Any, model: str, caps: Any) -> LLMResult:
            raise LLMError(ErrorKind.UNAVAILABLE, provider="openai")

    class Up:
        async def generate(self, req: Any, model: str, caps: Any) -> LLMResult:
            return LLMResult(text="ok", provider="anthropic", model=model)

    cfg = AIConfig(default=ModelRef(provider="openai", model="a"))
    svc = AIService(cfg=cfg)
    svc._providers.update({"openai": Down(), "anthropic": Up()})
    with pytest.raises(LLMError):
        await svc.complete("synthesis", [Message(role="user", content="x")])  # no fallback configured
    cfg.fallback = ModelRef(provider="anthropic", model="b")
    res = await svc.complete("synthesis", [Message(role="user", content="x")])
    assert res.text == "ok" and svc.fallback_used[0]["to"] == "anthropic:b"


async def test_task_routing(infra: Any) -> None:
    from app.llm.config_store import AIConfig, ModelRef
    from app.llm.service import AIService

    cfg = AIConfig(default=ModelRef(provider="openai", model="big"), cheap=ModelRef(provider="gemini", model="small"),
                   tasks={"synthesis": ModelRef(provider="anthropic", model="writer")})
    svc = AIService(cfg=cfg)
    assert svc.select("synthesis").ref.model == "writer"
    assert svc.select("extraction").ref.model == "small"
    assert svc.select("planning").ref.model == "big"
    svc2 = AIService(cfg=cfg, user_choice=ModelRef(provider="openai", model="user-pick"))
    assert svc2.select("planning").ref.model == "user-pick" and svc2.select("synthesis").ref.model == "user-pick"


# --- Search providers --------------------------------------------------------------------------

@respx.mock
async def test_tavily_search_and_extract() -> None:
    from app.search.base import SearchQuery
    from app.search.providers import TavilyProvider

    route = respx.post("https://api.tavily.com/search").mock(return_value=httpx.Response(200, json={"results": [
        {"url": "https://example.com/a", "title": "A", "content": "snippet", "score": 0.9},
        {"url": "http://127.0.0.1/internal", "title": "bad"}]}))
    hits = await TavilyProvider("tvly-x").search(SearchQuery(q="test", include_domains=["example.com"], date_from="2024-01-01"))
    assert [h.url for h in hits] == ["https://example.com/a"]  # internal URL dropped
    assert '"include_domains":["example.com"]' in route.calls[0].request.content.decode().replace(" ", "")
    respx.post("https://api.tavily.com/extract").mock(return_value=httpx.Response(200, json={
        "results": [{"url": "https://example.com/a", "raw_content": "Full text " * 50}]}))
    page = await TavilyProvider("tvly-x").extract("https://example.com/a")
    assert page.text.startswith("Full text")


@respx.mock
async def test_brave_and_firecrawl_and_openalex() -> None:
    from app.search.base import SearchQuery
    from app.search.providers import BraveProvider, FirecrawlProvider, OpenAlexProvider

    b = respx.get("https://api.search.brave.com/res/v1/web/search").mock(return_value=httpx.Response(200, json={
        "web": {"results": [{"url": "https://news.example/x", "title": "X", "description": "d", "page_age": "2024-05-01"}]}}))
    hits = await BraveProvider("bsk").search(SearchQuery(q="q", exclude_domains=["spam.example"], date_from="2024-01-01"))
    assert hits[0].published_at == "2024-05-01"
    req = b.calls[0].request
    assert req.headers["x-subscription-token"] == "bsk" and "-site%3Aspam.example" in str(req.url)
    respx.post("https://api.firecrawl.dev/v2/search").mock(return_value=httpx.Response(200, json={
        "success": True, "data": {"web": [{"url": "https://docs.example/y", "title": "Y", "description": "dd"}]}}))
    assert (await FirecrawlProvider("fc").search(SearchQuery(q="q")))[0].url == "https://docs.example/y"
    respx.post("https://api.firecrawl.dev/v2/scrape").mock(return_value=httpx.Response(200, json={
        "success": True, "data": {"markdown": "# Title\n\nBody " * 40, "metadata": {"title": "T", "statusCode": 200}}}))
    assert (await FirecrawlProvider("fc").extract("https://docs.example/y")).title == "T"
    respx.get("https://api.openalex.org/works").mock(return_value=httpx.Response(200, json={"results": [{
        "id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/abc", "display_name": "Paper",
        "publication_date": "2023-02-01", "authorships": [{"author": {"display_name": "Ada"}}],
        "primary_location": {"landing_page_url": "https://journal.example/p", "source": {"display_name": "J", "type": "journal"}},
        "abstract_inverted_index": {"Hello": [0], "world": [1]}, "type": "article"}]}))
    oa = await OpenAlexProvider().search(SearchQuery(q="q"))
    assert oa[0].content == "Hello world" and oa[0].content_kind == "abstract"
    assert oa[0].metadata["scholarly_label"] == "journal-published"


@respx.mock
async def test_search_errors_mapped() -> None:
    from app.search.base import SearchError, SearchQuery
    from app.search.providers import TavilyProvider

    respx.post("https://api.tavily.com/search").mock(return_value=httpx.Response(401, json={"detail": "bad key"}))
    with pytest.raises(SearchError) as ei:
        await TavilyProvider("x").search(SearchQuery(q="q"))
    assert ei.value.kind == ErrorKind.AUTH and not ei.value.retryable


async def test_search_service_falls_back(infra: Any, env: Any) -> None:
    env(SEARCH_PROVIDER="tavily", TAVILY_API_KEY="tvly-x", BRAVE_SEARCH_API_KEY="bsk", SEARCH_FALLBACK_ENABLED="1")
    from app.search.base import SearchQuery
    from app.search.service import SearchService

    with respx.mock:
        respx.post("https://api.tavily.com/search").mock(return_value=httpx.Response(401, json={}))
        respx.get("https://api.search.brave.com/res/v1/web/search").mock(return_value=httpx.Response(200, json={
            "web": {"results": [{"url": "https://ok.example/", "title": "ok"}]}}))
        svc = SearchService()
        hits, provider, cached = await svc.search(SearchQuery(q="fallback"))
        assert provider == "brave" and hits[0].url == "https://ok.example/" and not cached
        assert "tavily" in svc.disabled  # invalid credentials are not retried for the rest of the job
        hits2, provider2, cached2 = await svc.search(SearchQuery(q="fallback"))
        assert cached2  # served from cache (TTL)
        await svc.aclose()


@pytest.mark.live
@pytest.mark.skipif("not __import__('os').environ.get('LIVE_TESTS')")
async def test_live_provider_smoke() -> None:  # pragma: no cover - requires real credentials
    import os

    from app.llm.providers import GeminiProvider

    key = os.environ["GEMINI_API_KEY"]
    model = os.environ["AI_MODEL"]
    res = await GeminiProvider(key).generate(REQ, model, CAPS)
    assert res.text
