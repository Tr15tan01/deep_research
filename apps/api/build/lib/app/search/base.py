"""Search and extraction provider interfaces."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.llm.base import ErrorKind


class SearchError(Exception):
    def __init__(self, kind: ErrorKind, provider: str, detail: str = "", retry_after: float | None = None,
                 status: int | None = None) -> None:
        self.kind = kind
        self.provider = provider
        self.detail = detail[:300]
        self.retry_after = retry_after
        self.status = status
        super().__init__(f"{provider}:{kind.value}:{detail[:120]}")

    @property
    def retryable(self) -> bool:
        return self.kind in (ErrorKind.RATE_LIMIT, ErrorKind.UNAVAILABLE, ErrorKind.TIMEOUT)


class SearchQuery(BaseModel):
    q: str = Field(min_length=1, max_length=400)
    max_results: int = Field(default=8, ge=1, le=20)
    include_domains: list[str] = Field(default_factory=list)
    exclude_domains: list[str] = Field(default_factory=list)
    date_from: str | None = None  # YYYY-MM-DD
    date_to: str | None = None
    language: str | None = None
    scholarly: bool = False


class SearchHit(BaseModel):
    url: str
    title: str = ""
    snippet: str = ""
    published_at: str | None = None
    author: str | None = None
    provider: str
    rank: int = 0
    score: float | None = None
    content: str | None = None  # some providers return page/abstract text with the hit
    content_kind: str | None = None  # full_text | abstract | snippet
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractedPage(BaseModel):
    url: str
    final_url: str | None = None
    title: str | None = None
    text: str = ""
    author: str | None = None
    published_at: str | None = None
    site_name: str | None = None
    provider: str
    content_type: str | None = None
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list)


class SearchProvider(Protocol):
    name: str
    capabilities: set[str]  # {"search", "extract", "scholarly"}

    async def search(self, query: SearchQuery) -> list[SearchHit]: ...

    async def extract(self, url: str) -> ExtractedPage: ...
