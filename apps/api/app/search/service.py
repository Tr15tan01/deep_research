"""Search service: provider routing, fallback, retries, caching, budgets, usage and health."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import utcnow
from app.db.mongo import Collections, col, new_id
from app.db.redis import get_redis
from app.llm.base import ErrorKind
from app.llm.config_store import refresh_search_keys, search_key
from app.llm.http_common import backoff_delay
from app.llm.service import record_health
from app.search.base import ExtractedPage, SearchError, SearchHit, SearchQuery
from app.search.providers import (
    BraveProvider,
    BuiltinFetcher,
    FirecrawlProvider,
    OpenAlexProvider,
    TavilyProvider,
)

log = get_logger("search")
_ORDER = ("firecrawl", "tavily", "brave")
NON_RETRY_SKIP = {ErrorKind.AUTH, ErrorKind.QUOTA, ErrorKind.BILLING, ErrorKind.NOT_CONFIGURED}


def configured_search_providers() -> dict[str, bool]:
    s = get_settings()
    return {"firecrawl": bool(search_key("firecrawl")), "tavily": bool(search_key("tavily")),
            "brave": bool(search_key("brave")), "openalex": bool(s.SCHOLARLY_SEARCH_ENABLED),
            "demo": bool(s.DEMO_MODE)}


def build_search_provider(name: str) -> Any:
    s = get_settings()
    if name == "firecrawl" and search_key("firecrawl"):
        return FirecrawlProvider(search_key("firecrawl"))
    if name == "tavily" and search_key("tavily"):
        return TavilyProvider(search_key("tavily"))
    if name == "brave" and search_key("brave"):
        return BraveProvider(search_key("brave"))
    if name == "openalex" and s.SCHOLARLY_SEARCH_ENABLED:
        return OpenAlexProvider()
    if name == "builtin":
        return BuiltinFetcher()
    if name == "demo":
        from app.search.demo import DemoSearchProvider

        return DemoSearchProvider()
    return None


class SearchNotConfigured(Exception):
    pass


class SearchService:
    def __init__(self, job: Any = None, user_id: str | None = None) -> None:
        self.job = job
        self.user_id = user_id
        self._cache: dict[str, Any] = {}
        s = get_settings()
        if s.DEMO_MODE:
            order = ["demo"]
        else:
            primary = s.SEARCH_PROVIDER
            order = [primary] + ([p for p in _ORDER if p != primary] if s.SEARCH_FALLBACK_ENABLED else [])
        configured = configured_search_providers()
        self.order = [p for p in order if configured.get(p)]
        self.disabled: set[str] = set()  # providers that failed non-retryably during this job

    @classmethod
    async def create(cls, job: Any = None, user_id: str | None = None) -> SearchService:
        """Preferred constructor in async code: picks up keys saved in the admin console."""
        await refresh_search_keys()
        return cls(job=job, user_id=user_id)

    def available(self) -> bool:
        return bool(self.order)

    def _provider(self, name: str) -> Any:
        if name not in self._cache:
            self._cache[name] = build_search_provider(name)
        return self._cache[name]

    async def aclose(self) -> None:
        for p in self._cache.values():
            if p is not None and hasattr(p, "aclose"):
                await p.aclose()

    # --- caching ---------------------------------------------------------------------------
    @staticmethod
    def _key(prefix: str, payload: Any) -> str:
        return prefix + hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    async def _cache_get(self, key: str) -> Any:
        try:
            raw = await get_redis().get(key)
            return json.loads(raw) if raw else None
        except Exception:  # noqa: BLE001
            return None

    async def _cache_set(self, key: str, value: Any) -> None:
        try:
            data = json.dumps(value, default=str)
            if len(data) < 400_000:
                await get_redis().set(key, data, ex=get_settings().SEARCH_CACHE_TTL_SECONDS)
        except Exception:  # noqa: BLE001
            pass

    async def _record(self, kind: str, provider: str, ok: bool, detail: dict[str, Any]) -> None:
        try:
            await col(Collections.usage_records).insert_one({
                "_id": new_id("use"), "user_id": self.user_id, "job_id": self.job.job_id if self.job else None,
                "kind": kind, "provider": provider, "ok": ok, "cost_usd_est": None, "cost_known": False,
                "created_at": utcnow(), **detail})
        except Exception:  # noqa: BLE001
            pass

    # --- search ------------------------------------------------------------------------------
    async def search(self, query: SearchQuery) -> tuple[list[SearchHit], str, bool]:
        """Returns (hits, provider_name, from_cache)."""
        if not self.order:
            raise SearchNotConfigured("No search provider is configured.")
        last_error: SearchError | None = None
        for name in self.order:
            if name in self.disabled:
                continue
            ck = self._key(f"sc:{name}:", query.model_dump())
            cached = await self._cache_get(ck)
            if cached is not None:
                return [SearchHit.model_validate(h) for h in cached], name, True
            if self.job is not None:
                await self.job.reserve_tool_call("search")
            try:
                hits = await self._try(name, lambda p: p.search(query))
            except SearchError as e:
                last_error = e
                if e.kind in NON_RETRY_SKIP:
                    self.disabled.add(name)
                if self.job is not None and len(self.order) > 1:
                    await self.job.emit("warning", f"Search provider {name} failed ({e.kind.value.replace('_', ' ')}); "
                                        "trying the next configured provider.", {"provider": name, "error": e.kind.value},
                                        level="warning")
                continue
            await self._cache_set(ck, [h.model_dump() for h in hits])
            return hits, name, False
        assert last_error is not None or not self.order
        raise last_error or SearchNotConfigured("No search provider available.")

    async def scholarly(self, query: SearchQuery) -> list[SearchHit]:
        if get_settings().DEMO_MODE:
            return []
        p = self._provider("openalex")
        if p is None:
            return []
        ck = self._key("sc:openalex:", query.model_dump())
        cached = await self._cache_get(ck)
        if cached is not None:
            return [SearchHit.model_validate(h) for h in cached]
        if self.job is not None:
            await self.job.reserve_tool_call("search")
        hits = await self._try("openalex", lambda p: p.search(query))
        await self._cache_set(ck, [h.model_dump() for h in hits])
        return hits

    async def _try(self, name: str, fn: Any, attempts: int = 3) -> Any:
        provider = self._provider(name)
        for attempt in range(attempts):
            started = time.monotonic()
            try:
                result = await fn(provider)
                latency = int((time.monotonic() - started) * 1000)
                await record_health("search", name, True, latency_ms=latency)
                await self._record("search", name, True, {"latency_ms": latency})
                return result
            except SearchError as e:
                await record_health("search", name, False, e.kind.value)
                await self._record("search", name, False, {"error": e.kind.value})
                if not e.retryable or attempt == attempts - 1:
                    raise
                await asyncio.sleep(min(e.retry_after or backoff_delay(attempt, base=0.8), 15))
        raise SearchError(ErrorKind.UNKNOWN, name, "unreachable")

    # --- extraction --------------------------------------------------------------------------
    async def extract(self, url: str) -> ExtractedPage:
        s = get_settings()
        ck = self._key("ec:", url)
        cached = await self._cache_get(ck)
        if cached is not None:
            return ExtractedPage.model_validate(cached)
        if s.DEMO_MODE:
            chain = ["demo"]
        else:
            chain = [p for p in self.order if p in ("firecrawl", "tavily") and p not in self.disabled] + ["builtin"]
        last: SearchError | None = None
        for name in chain:
            if self.job is not None:
                await self.job.reserve_tool_call("extract")
            try:
                page = await self._try(name, lambda p: p.extract(url), attempts=2)
            except SearchError as e:
                last = e
                if e.kind in NON_RETRY_SKIP:
                    self.disabled.add(name)
                continue
            if len(page.text.strip()) < 200:
                last = SearchError(ErrorKind.UNKNOWN, name, "too little text extracted")
                continue
            data = page.model_dump()
            if len(data["text"]) > 150_000:
                data["text"] = data["text"][:150_000]
                data["truncated"] = True
            await self._cache_set(ck, data)
            return ExtractedPage.model_validate(data)
        raise last or SearchError(ErrorKind.UNKNOWN, "extract", "no extractor available")
