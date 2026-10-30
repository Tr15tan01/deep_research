"""AI service: task-based model routing, budgets, structured output with validation and
repair, usage/cost accounting, provider health tracking and explicit fallback."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import utcnow
from app.db.mongo import Collections, col, new_id
from app.db.redis import get_redis
from app.llm.base import (
    FALLBACK_ELIGIBLE,
    ErrorKind,
    LLMError,
    LLMRequest,
    LLMResult,
    Message,
    ModelCapabilities,
    estimate_request_tokens,
)
from app.llm.capabilities import resolve_capabilities
from app.llm.config_store import AIConfig, ModelRef, get_api_key, get_user_api_key, load_config
from app.llm.schema_utils import extract_json, model_schema

log = get_logger("llm")
T = TypeVar("T", bound=BaseModel)


def build_provider(provider: str, api_key: str, *, base_url: str = "") -> Any:
    from app.llm.demo import DemoProvider
    from app.llm.providers import AnthropicProvider, GeminiProvider, OpenAIProvider

    timeout = float(get_settings().AI_REQUEST_TIMEOUT_SECONDS)
    if provider == "openai":
        return OpenAIProvider(api_key, timeout=timeout)
    if provider == "openai_compatible":
        if not base_url:
            raise LLMError(ErrorKind.NOT_CONFIGURED, "The OpenAI-compatible provider needs a base URL.", provider=provider)
        return OpenAIProvider(api_key, base_url=base_url, name="openai_compatible", timeout=timeout)
    if provider == "anthropic":
        return AnthropicProvider(api_key, timeout=timeout)
    if provider == "gemini":
        return GeminiProvider(api_key, timeout=timeout)
    if provider == "demo":
        return DemoProvider()
    raise LLMError(ErrorKind.NOT_CONFIGURED, provider=provider)


def estimate_cost(cfg: AIConfig, ref: ModelRef, input_tokens: int, output_tokens: int) -> float | None:
    if ref.provider == "demo":
        return 0.0
    price = cfg.pricing.get(ref.key)
    if not price:
        return None
    return (input_tokens * price.input_per_mtok_usd + output_tokens * price.output_per_mtok_usd) / 1_000_000


async def record_health(kind: str, provider: str, ok: bool, error_kind: str | None = None, latency_ms: int | None = None) -> None:
    """Observed provider health from real calls (not synthetic)."""
    try:
        r = get_redis()
        key = f"health:{kind}:{provider}"
        now = str(int(time.time()))
        mapping: dict[str, str] = {"last_ok_at" if ok else "last_error_at": now}
        if error_kind:
            mapping["last_error_kind"] = error_kind
        if latency_ms is not None:
            mapping["last_latency_ms"] = str(latency_ms)
        pipe = r.pipeline()
        pipe.hset(key, mapping=mapping)
        pipe.hincrby(key, "ok" if ok else "errors", 1)
        pipe.expire(key, 7 * 86400)
        await pipe.execute()
    except Exception:  # noqa: BLE001
        pass


@dataclass
class TaskSelection:
    ref: ModelRef
    caps: ModelCapabilities
    via: str  # default | task | cheap | user | fallback


@dataclass
class AIService:
    cfg: AIConfig
    user_id: str | None = None
    job: Any = None  # JobContext | None
    user_choice: ModelRef | None = None
    use_user_key: bool = False
    fallback_used: list[dict[str, Any]] = field(default_factory=list)
    _providers: dict[str, Any] = field(default_factory=dict)

    @classmethod
    async def create(cls, *, user_id: str | None = None, job: Any = None, user_choice: ModelRef | None = None,
                     use_user_key: bool = False) -> AIService:
        return cls(cfg=await load_config(), user_id=user_id, job=job, user_choice=user_choice, use_user_key=use_user_key)

    # --- Routing ---------------------------------------------------------------------------
    def select(self, task: str) -> TaskSelection:
        cfg = self.cfg
        ref: ModelRef | None = None
        via = "default"
        if self.user_choice is not None and task in ("planning", "synthesis"):
            ref, via = self.user_choice, "user"
        elif task == "routine" and cfg.cheap:
            ref, via = cfg.cheap, "cheap"
        elif cfg.tasks.get(task):
            ref, via = cfg.tasks[task], "task"
        elif task in ("extraction", "verification") and cfg.cheap:
            ref, via = cfg.cheap, "cheap"
        else:
            ref = self.user_choice or cfg.default
            via = "user" if self.user_choice else "default"
        if ref is None:
            raise LLMError(ErrorKind.NOT_CONFIGURED)
        return TaskSelection(ref=ref, caps=resolve_capabilities(ref, cfg), via=via)

    def describe(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for t in ("planning", "extraction", "verification", "synthesis", "charts", "routine"):
            try:
                sel = self.select(t)
                out[t] = {"provider": sel.ref.provider, "model": sel.ref.model, "via": sel.via,
                          "capabilities_source": sel.caps.source}
            except LLMError:
                out[t] = None
        return out

    async def _provider(self, ref: ModelRef) -> Any:
        cache_key = ref.provider + (":user" if self.use_user_key else "")
        if cache_key in self._providers:
            return self._providers[cache_key]
        key = ""
        if self.use_user_key and self.user_id:
            key = await get_user_api_key(self.user_id, ref.provider) or ""
        if not key:
            key, _src = await get_api_key(ref.provider)
        if not key:
            raise LLMError(ErrorKind.NOT_CONFIGURED,
                           f"No API key is configured for {ref.provider}. An administrator must add one in Admin → Providers.",
                           provider=ref.provider)
        prov = build_provider(ref.provider, key, base_url=self.cfg.openai_compatible_base_url)
        self._providers[cache_key] = prov
        return prov

    async def aclose(self) -> None:
        for p in self._providers.values():
            closer = getattr(p, "aclose", None)
            if closer:
                await closer()
        self._providers.clear()

    # --- Core call -------------------------------------------------------------------------
    async def _call(self, sel: TaskSelection, req: LLMRequest) -> LLMResult:
        est_in = estimate_request_tokens(req)
        if est_in + 512 > sel.caps.context_window:
            raise LLMError(ErrorKind.CONTEXT_OVERFLOW, provider=sel.ref.provider,
                           detail=f"estimated {est_in} tokens > context {sel.caps.context_window}")
        if self.job is not None:
            await self.job.check_alive()
            remaining = await self.job.remaining_output_tokens()
            if remaining < 256:
                raise LLMError(ErrorKind.BUDGET, provider=sel.ref.provider, detail="output tokens")
            req = req.model_copy(update={"max_output_tokens": min(req.max_output_tokens, remaining)})
            est_cost = estimate_cost(self.cfg, sel.ref, est_in, req.max_output_tokens)
            if est_cost is not None and est_cost > await self.job.remaining_cost():
                raise LLMError(ErrorKind.BUDGET, provider=sel.ref.provider, detail="cost")
            await self.job.reserve_tool_call("llm")
        provider = await self._provider(sel.ref)
        started = time.monotonic()
        try:
            result: LLMResult = await provider.generate(req, sel.ref.model, sel.caps)
        except LLMError as e:
            await record_health("llm", sel.ref.provider, False, e.kind.value)
            await self._record_usage(sel, req, None, error=e.kind.value)
            raise
        result.latency_ms = result.latency_ms or int((time.monotonic() - started) * 1000)
        await record_health("llm", sel.ref.provider, True, latency_ms=result.latency_ms)
        await self._record_usage(sel, req, result)
        return result

    async def _record_usage(self, sel: TaskSelection, req: LLMRequest, result: LLMResult | None, error: str | None = None) -> None:
        in_t = result.usage.input_tokens if result else 0
        out_t = result.usage.output_tokens if result else 0
        cost = estimate_cost(self.cfg, sel.ref, in_t, out_t) if result else 0.0
        price = self.cfg.pricing.get(sel.ref.key)
        doc = {
            "_id": new_id("use"),
            "user_id": self.user_id,
            "job_id": self.job.job_id if self.job else None,
            "kind": "llm",
            "task": req.task,
            "provider": sel.ref.provider,
            "model": sel.ref.model,
            "via": sel.via,
            "input_tokens": in_t,
            "output_tokens": out_t,
            "usage_reported_by_provider": bool(result and result.usage.reported),
            "cost_usd_est": cost,
            "cost_known": cost is not None,
            "pricing_as_of": price.as_of if price else None,
            "latency_ms": result.latency_ms if result else None,
            "error": error,
            "created_at": utcnow(),
        }
        try:
            await col(Collections.usage_records).insert_one(doc)
            if self.job is not None:
                inc: dict[str, float] = {"llm_calls": 1, "input_tokens": in_t, "output_tokens": out_t}
                if cost is not None:
                    inc["cost_usd_est"] = cost
                elif result is not None:
                    inc["cost_unknown_calls"] = 1
                if error:
                    inc["llm_errors"] = 1
                await self.job.add_usage(**inc)
        except Exception as e:  # noqa: BLE001
            log.error("usage_record_failed", error=type(e).__name__)

    async def complete(self, task: str, messages: list[Message], *, max_output_tokens: int = 2048,
                       temperature: float | None = 0.2, metadata: dict[str, Any] | None = None) -> LLMResult:
        req = LLMRequest(messages=messages, max_output_tokens=max_output_tokens, temperature=temperature, task=task,
                         metadata=metadata or {})
        return await self._with_fallback(task, req)

    async def structured(self, task: str, messages: list[Message], schema: type[T], *, max_output_tokens: int = 4096,
                         temperature: float | None = 0.1, metadata: dict[str, Any] | None = None) -> T:
        js = model_schema(schema)
        req = LLMRequest(messages=messages, max_output_tokens=max_output_tokens, temperature=temperature, task=task,
                         json_schema=js, schema_name=schema.__name__, metadata=metadata or {})
        result = await self._with_fallback(task, req)
        try:
            return self._parse(result, schema)
        except (ValueError, ValidationError) as first_error:
            # One repair round: show the validation error and ask for corrected JSON only.
            repair = req.model_copy(update={
                "messages": [*messages, Message(role="assistant", content=result.text[:20000]),
                             Message(role="user", content="That output was invalid: " + str(first_error)[:1500]
                                     + "\nReturn only the corrected JSON object.")],
            })
            result2 = await self._with_fallback(task, repair)
            try:
                return self._parse(result2, schema)
            except (ValueError, ValidationError) as e:
                raise LLMError(ErrorKind.BAD_OUTPUT, provider=result2.provider, detail=str(e)[:300]) from e

    @staticmethod
    def _parse(result: LLMResult, schema: type[T]) -> T:
        data = result.parsed if result.parsed is not None else extract_json(result.text)
        return schema.model_validate(data)

    async def _with_fallback(self, task: str, req: LLMRequest) -> LLMResult:
        sel = self.select(task)
        try:
            return await self._call(sel, req)
        except LLMError as e:
            fb = self.cfg.fallback
            if (
                e.kind in FALLBACK_ELIGIBLE
                and get_settings().AI_FALLBACK_ENABLED
                and fb is not None
                and fb.key != sel.ref.key
            ):
                fsel = TaskSelection(ref=fb, caps=resolve_capabilities(fb, self.cfg), via="fallback")
                note = {"task": task, "from": sel.ref.key, "to": fb.key, "reason": e.kind.value, "at": utcnow().isoformat()}
                self.fallback_used.append(note)
                if self.job is not None:
                    await col(Collections.research_jobs).update_one({"_id": self.job.job_id}, {"$push": {"fallbacks": note}})
                    await self.job.emit("warning", f"Switched {task} from {sel.ref.model} to fallback model {fb.model} "
                                        f"({e.kind.value.replace('_', ' ')}).", note, level="warning")
                return await self._call(fsel, req)
            raise


async def test_connection(ref: ModelRef, cfg: AIConfig) -> dict[str, Any]:
    """Real connectivity check: a tiny completion against the exact configured model."""
    key, source = await get_api_key(ref.provider)
    if not key:
        return {"ok": False, "error": ErrorKind.NOT_CONFIGURED.value, "message": "No API key configured.", "key_source": source}
    prov = build_provider(ref.provider, key, base_url=cfg.openai_compatible_base_url)
    caps = resolve_capabilities(ref, cfg)
    started = time.monotonic()
    try:
        res = await prov.generate(LLMRequest(messages=[Message(role="user", content="Reply with the single word: pong")],
                                             max_output_tokens=16, temperature=0, task="health"), ref.model, caps)
        await record_health("llm", ref.provider, True, latency_ms=res.latency_ms)
        return {"ok": True, "latency_ms": int((time.monotonic() - started) * 1000), "model_reported": res.model,
                "sample": res.text[:40], "key_source": source}
    except LLMError as e:
        await record_health("llm", ref.provider, False, e.kind.value)
        return {"ok": False, "error": e.kind.value, "message": e.user_message, "status": e.status, "key_source": source}
    finally:
        closer = getattr(prov, "aclose", None)
        if closer:
            await closer()
