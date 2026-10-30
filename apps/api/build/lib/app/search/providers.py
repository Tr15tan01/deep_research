"""Concrete search / extraction providers.

Responsibilities (they are *not* interchangeable):
  * Tavily     — web search (+ optional page extraction via /extract).
  * Brave      — web search only (snippets); pages are extracted by the built-in fetcher.
  * Firecrawl  — web search (/search) and page scraping to markdown (/scrape).
  * OpenAlex   — scholarly metadata search (works + abstracts); keyless public API.
  * BuiltinFetcher — SSRF-safe direct fetch + sandboxed HTML/PDF text extraction.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.config import get_settings
from app.extract.sandbox import ExtractionFailed, extract
from app.llm.base import ErrorKind
from app.search.base import ExtractedPage, SearchError, SearchHit, SearchQuery
from app.security.ssrf import FetchError, SSRFBlocked, safe_fetch, validate_url_shape


def _http_error(provider: str, resp: httpx.Response) -> SearchError:
    s = resp.status_code
    text = resp.text[:300]
    ra = resp.headers.get("retry-after")
    retry_after = float(ra) if ra and ra.replace(".", "", 1).isdigit() else None
    low = text.lower()
    if s in (401, 403):
        return SearchError(ErrorKind.AUTH, provider, text, status=s)
    if s == 429:
        if any(m in low for m in ("usage limit", "insufficient credits", "quota exceeded", "upgrade your plan")):
            return SearchError(ErrorKind.QUOTA, provider, text, status=s)
        return SearchError(ErrorKind.RATE_LIMIT, provider, text, retry_after=retry_after, status=s)
    if s in (402, 432, 433) or "insufficient credits" in low:
        return SearchError(ErrorKind.QUOTA, provider, text, status=s)
    if s >= 500:
        return SearchError(ErrorKind.UNAVAILABLE, provider, text, retry_after=retry_after, status=s)
    return SearchError(ErrorKind.UNKNOWN, provider, text, status=s)


async def _request(client: httpx.AsyncClient, provider: str, method: str, url: str, **kw: Any) -> dict[str, Any]:
    try:
        resp = await client.request(method, url, **kw)
    except httpx.TimeoutException as e:
        raise SearchError(ErrorKind.TIMEOUT, provider, type(e).__name__) from e
    except httpx.TransportError as e:
        raise SearchError(ErrorKind.UNAVAILABLE, provider, type(e).__name__) from e
    if resp.status_code >= 400:
        raise _http_error(provider, resp)
    try:
        return resp.json()
    except ValueError as e:
        raise SearchError(ErrorKind.BAD_OUTPUT, provider, "non-JSON response") from e


def _public_http_url(url: str) -> bool:
    try:
        validate_url_shape(url)
        return True
    except SSRFBlocked:
        return False


class _HTTPProvider:
    name = "base"
    capabilities: set[str] = set()

    def __init__(self, api_key: str = "", client: httpx.AsyncClient | None = None, timeout: float = 30.0) -> None:
        self.api_key = api_key
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0))

    async def aclose(self) -> None:
        await self.client.aclose()

    async def extract(self, url: str) -> ExtractedPage:
        raise SearchError(ErrorKind.UNSUPPORTED, self.name, "extraction not supported")


class TavilyProvider(_HTTPProvider):
    name = "tavily"
    capabilities = {"search", "extract"}
    BASE = "https://api.tavily.com"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def search(self, query: SearchQuery) -> list[SearchHit]:
        body: dict[str, Any] = {"query": query.q, "max_results": query.max_results, "search_depth": "advanced",
                                "include_answer": False, "include_raw_content": False, "topic": "general"}
        if query.include_domains:
            body["include_domains"] = query.include_domains[:20]
        if query.exclude_domains:
            body["exclude_domains"] = query.exclude_domains[:20]
        if query.date_from:
            body["start_date"] = query.date_from
        if query.date_to:
            body["end_date"] = query.date_to
        data = await _request(self.client, self.name, "POST", f"{self.BASE}/search", json=body, headers=self._headers())
        hits = []
        for i, r in enumerate(data.get("results") or []):
            if not r.get("url") or not _public_http_url(r["url"]):
                continue
            hits.append(SearchHit(url=r["url"], title=r.get("title") or "", snippet=(r.get("content") or "")[:1000],
                                  published_at=r.get("published_date"), provider=self.name, rank=i,
                                  score=r.get("score")))
        return hits

    async def extract(self, url: str) -> ExtractedPage:
        data = await _request(self.client, self.name, "POST", f"{self.BASE}/extract",
                              json={"urls": [url], "extract_depth": "basic"}, headers=self._headers())
        res = (data.get("results") or [])
        if not res or not res[0].get("raw_content"):
            failed = (data.get("failed_results") or [{}])[0]
            raise SearchError(ErrorKind.UNKNOWN, self.name, f"extract failed: {failed.get('error', 'no content')}")
        return ExtractedPage(url=url, final_url=res[0].get("url"), text=res[0]["raw_content"], provider=self.name)


class BraveProvider(_HTTPProvider):
    name = "brave"
    capabilities = {"search"}
    URL = "https://api.search.brave.com/res/v1/web/search"

    async def search(self, query: SearchQuery) -> list[SearchHit]:
        q = query.q
        if query.include_domains:
            q += " (" + " OR ".join(f"site:{d}" for d in query.include_domains[:5]) + ")"
        for d in query.exclude_domains[:10]:
            q += f" -site:{d}"
        params: dict[str, str] = {"q": q[:400], "count": str(min(query.max_results, 20)), "safesearch": "moderate",
                                  "text_decorations": "false"}
        if query.date_from or query.date_to:
            params["freshness"] = f"{query.date_from or '1990-01-01'}to{query.date_to or '2100-01-01'}"
        if query.language:
            params["search_lang"] = query.language
        data = await _request(self.client, self.name, "GET", self.URL, params=params,
                              headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"})
        hits = []
        for i, r in enumerate(((data.get("web") or {}).get("results")) or []):
            if not r.get("url") or not _public_http_url(r["url"]):
                continue
            hits.append(SearchHit(url=r["url"], title=r.get("title") or "", snippet=(r.get("description") or "")[:1000],
                                  published_at=r.get("page_age"), provider=self.name, rank=i,
                                  metadata={"site": (r.get("profile") or {}).get("name")}))
        return hits


class FirecrawlProvider(_HTTPProvider):
    name = "firecrawl"
    capabilities = {"search", "extract"}
    BASE = "https://api.firecrawl.dev/v2"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def search(self, query: SearchQuery) -> list[SearchHit]:
        q = query.q
        if query.include_domains:
            q += " (" + " OR ".join(f"site:{d}" for d in query.include_domains[:5]) + ")"
        for d in query.exclude_domains[:10]:
            q += f" -site:{d}"
        body: dict[str, Any] = {"query": q[:400], "limit": query.max_results}
        if query.date_from or query.date_to:
            def mdy(d: str) -> str:
                y, m, dd = d.split("-")
                return f"{m}/{dd}/{y}"
            parts = ["cdr:1"]
            if query.date_from:
                parts.append("cd_min:" + mdy(query.date_from))
            if query.date_to:
                parts.append("cd_max:" + mdy(query.date_to))
            body["tbs"] = ",".join(parts)
        data = await _request(self.client, self.name, "POST", f"{self.BASE}/search", json=body, headers=self._headers())
        raw = data.get("data")
        items = raw.get("web", []) if isinstance(raw, dict) else (raw or [])
        hits = []
        for i, r in enumerate(items):
            url = r.get("url")
            if not url or not _public_http_url(url):
                continue
            hits.append(SearchHit(url=url, title=r.get("title") or "", snippet=(r.get("description") or "")[:1000],
                                  provider=self.name, rank=i))
        return hits

    async def extract(self, url: str) -> ExtractedPage:
        data = await _request(self.client, self.name, "POST", f"{self.BASE}/scrape",
                              json={"url": url, "formats": ["markdown"], "onlyMainContent": True, "timeout": 30000,
                                    "blockAds": True},
                              headers=self._headers())
        d = data.get("data") or {}
        md = d.get("markdown") or ""
        meta = d.get("metadata") or {}
        status = meta.get("statusCode")
        if not md or (isinstance(status, int) and status >= 400):
            raise SearchError(ErrorKind.UNKNOWN, self.name, f"scrape returned no content (status {status})")
        return ExtractedPage(url=url, final_url=meta.get("url") or meta.get("sourceURL"), title=meta.get("title"),
                             text=md, author=meta.get("author"),
                             published_at=meta.get("publishedTime") or meta.get("article:published_time"),
                             site_name=meta.get("ogSiteName"), provider=self.name)


class OpenAlexProvider(_HTTPProvider):
    """Scholarly works index. Results carry *metadata and abstracts*, not full text, and
    are labelled by publication venue type — never as 'peer-reviewed' by assumption."""

    name = "openalex"
    capabilities = {"search", "scholarly"}
    URL = "https://api.openalex.org/works"

    @staticmethod
    def _abstract(inv: dict[str, list[int]] | None) -> str:
        if not inv:
            return ""
        positions: list[tuple[int, str]] = [(p, w) for w, ps in inv.items() for p in ps]
        return " ".join(w for _, w in sorted(positions))[:20000]

    async def search(self, query: SearchQuery) -> list[SearchHit]:
        filters = []
        if query.date_from:
            filters.append(f"from_publication_date:{query.date_from}")
        if query.date_to:
            filters.append(f"to_publication_date:{query.date_to}")
        params: dict[str, str] = {"search": query.q[:300], "per-page": str(min(query.max_results, 25)),
                                  "select": "id,doi,display_name,publication_date,authorships,primary_location,"
                                            "abstract_inverted_index,type,cited_by_count,open_access"}
        if filters:
            params["filter"] = ",".join(filters)
        mailto = get_settings().OPENALEX_MAILTO
        if mailto:
            params["mailto"] = mailto
        data = await _request(self.client, self.name, "GET", self.URL, params=params)
        hits = []
        for i, w in enumerate(data.get("results") or []):
            loc = w.get("primary_location") or {}
            src = loc.get("source") or {}
            url = loc.get("landing_page_url") or (f"https://doi.org/{w['doi'].removeprefix('https://doi.org/')}" if w.get("doi") else None) or w.get("id")
            if not url or not _public_http_url(url):
                continue
            authors = [a.get("author", {}).get("display_name") for a in (w.get("authorships") or [])[:6]]
            abstract = self._abstract(w.get("abstract_inverted_index"))
            venue_type = src.get("type")  # journal | repository | conference | book series | ...
            hits.append(SearchHit(
                url=url, title=w.get("display_name") or "", snippet=abstract[:600], published_at=w.get("publication_date"),
                author=", ".join(a for a in authors if a) or None, provider=self.name, rank=i,
                content=abstract or None, content_kind="abstract" if abstract else None,
                metadata={"openalex_id": w.get("id"), "doi": w.get("doi"), "venue": src.get("display_name"),
                          "venue_type": venue_type, "work_type": w.get("type"), "cited_by_count": w.get("cited_by_count"),
                          "open_access_url": (w.get("open_access") or {}).get("oa_url"),
                          "scholarly_label": "journal-published" if venue_type == "journal" else
                          ("preprint/repository" if venue_type == "repository" else (venue_type or "scholarly record"))},
            ))
        return hits


class BuiltinFetcher:
    """Direct, SSRF-safe page fetch with sandboxed extraction (no third-party API)."""

    name = "builtin"
    capabilities = {"extract"}

    async def search(self, query: SearchQuery) -> list[SearchHit]:
        raise SearchError(ErrorKind.UNSUPPORTED, self.name, "search not supported")

    async def extract(self, url: str) -> ExtractedPage:
        try:
            res = await safe_fetch(url)
        except SSRFBlocked as e:
            raise SearchError(ErrorKind.UNSUPPORTED, self.name, f"blocked: {e.reason}") from e
        except FetchError as e:
            kind = ErrorKind.TIMEOUT if e.reason == "timeout" else (
                ErrorKind.UNAVAILABLE if e.status and e.status >= 500 else ErrorKind.UNKNOWN)
            raise SearchError(kind, self.name, e.reason, status=e.status) from e
        kind = "pdf" if res.content_type == "application/pdf" or res.body.startswith(b"%PDF-") else (
            "txt" if res.content_type in ("text/plain", "text/markdown") else "html")
        try:
            parsed = await extract(res.body, kind)
        except ExtractionFailed as e:
            raise SearchError(ErrorKind.UNKNOWN, self.name, f"extraction failed: {e}") from e
        warnings = list(parsed.get("warnings") or [])
        if res.truncated:
            warnings.append("response truncated at size limit")
        return ExtractedPage(url=url, final_url=res.url, title=parsed.get("title"), text=parsed.get("text") or "",
                             author=parsed.get("author"), published_at=parsed.get("published"),
                             site_name=parsed.get("site_name"), provider=self.name, content_type=res.content_type,
                             truncated=res.truncated, warnings=warnings)

    async def aclose(self) -> None:
        return None


async def gather_limited(coros: list[Any], limit: int = 4) -> list[Any]:
    sem = asyncio.Semaphore(limit)

    async def run(c: Any) -> Any:
        async with sem:
            try:
                return await c
            except Exception as e:  # noqa: BLE001
                return e

    return await asyncio.gather(*(run(c) for c in coros))
