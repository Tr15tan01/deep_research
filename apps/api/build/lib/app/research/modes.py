"""Research modes and their explicit, bounded budgets.

Every mode budget is additionally capped by the global environment limits
(MAX_SEARCH_CALLS_PER_JOB, MAX_SOURCES_PER_JOB, ...)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.research.context import Budgets


@dataclass(frozen=True)
class ModeSpec:
    key: str
    label: str
    description: str
    max_subquestions: int
    max_iterations: int
    results_per_query: int
    max_sources: int
    max_search_calls: int
    max_tool_calls: int
    max_output_tokens: int
    max_duration_seconds: int
    scholarly: bool = False
    web: bool = True
    comparison_matrix: bool = False
    uses_uploads: bool = False
    est_minutes: tuple[int, int] = (2, 5)

    def public(self) -> dict[str, Any]:
        b = budgets_for(self.key)
        return {"key": self.key, "label": self.label, "description": self.description,
                "estimated_minutes": list(self.est_minutes), "scholarly": self.scholarly, "web": self.web,
                "comparison_matrix": self.comparison_matrix, "limits": b.as_dict()}


MODES: dict[str, ModeSpec] = {m.key: m for m in [
    ModeSpec("quick", "Quick Research", "A fast scan of the most relevant sources for a focused answer.",
             3, 1, 5, 8, 8, 30, 12_000, 300, est_minutes=(1, 3)),
    ModeSpec("standard", "Standard Research", "Balanced depth: a structured plan, one round of follow-up research.",
             5, 2, 6, 15, 16, 50, 20_000, 900, est_minutes=(3, 8)),
    ModeSpec("deep", "Deep Research", "Broad coverage with multiple follow-up rounds and stricter verification.",
             7, 3, 8, 30, 25, 90, 40_000, 1800, est_minutes=(8, 25)),
    ModeSpec("academic", "Academic Literature Review", "Scholarly index (OpenAlex) plus the web; abstracts are labelled as such.",
             6, 2, 8, 25, 22, 80, 32_000, 1500, scholarly=True, est_minutes=(6, 20)),
    ModeSpec("competitive", "Competitive Analysis", "Compare companies or products with a cited comparison matrix.",
             6, 2, 6, 22, 20, 70, 28_000, 1200, comparison_matrix=True, est_minutes=(5, 15)),
    ModeSpec("technology", "Technology Comparison", "Compare technologies, frameworks or approaches side by side.",
             6, 2, 6, 22, 20, 70, 28_000, 1200, comparison_matrix=True, est_minutes=(5, 15)),
    ModeSpec("market", "Market Research", "Market size, segments, trends and players, with charts where data allows.",
             6, 2, 7, 24, 20, 70, 28_000, 1200, comparison_matrix=True, est_minutes=(5, 15)),
    ModeSpec("documents", "Research from Uploaded Documents", "Analyse only your uploaded files (no web search).",
             5, 1, 0, 10, 0, 60, 24_000, 900, web=False, uses_uploads=True, est_minutes=(2, 6)),
    ModeSpec("verify_claim", "Verify a Claim", "Look for evidence for and against a specific claim.",
             3, 1, 6, 12, 10, 40, 14_000, 600, est_minutes=(2, 5)),
    ModeSpec("counterarguments", "Find Counterarguments", "Seek the strongest evidence against a position or report.",
             4, 1, 6, 14, 12, 45, 16_000, 700, est_minutes=(2, 6)),
]}


def budgets_for(mode: str, overrides: dict[str, Any] | None = None) -> Budgets:
    s = get_settings()
    m = MODES.get(mode, MODES["standard"])
    o = overrides or {}

    def cap(user: Any, mode_val: int, global_val: int) -> int:
        v = mode_val if not isinstance(user, int) or user <= 0 else min(user, mode_val)
        return max(0, min(v, global_val))

    return Budgets(
        max_search_calls=cap(o.get("max_search_calls"), m.max_search_calls, s.MAX_SEARCH_CALLS_PER_JOB),
        max_sources=max(1, cap(o.get("max_sources"), m.max_sources, s.MAX_SOURCES_PER_JOB)),
        max_tool_calls=cap(None, m.max_tool_calls, s.MAX_TOOL_CALLS_PER_JOB) + 0,
        max_output_tokens=cap(None, m.max_output_tokens, s.MAX_OUTPUT_TOKENS_PER_JOB),
        max_cost_usd=float(o["max_cost_usd"]) if isinstance(o.get("max_cost_usd"), (int, float)) and o["max_cost_usd"] > 0
        else max(0.5, s.MONTHLY_COST_LIMIT_USD_PER_USER),
        max_duration_seconds=cap(o.get("max_duration_seconds"), m.max_duration_seconds, s.MAX_RESEARCH_DURATION_SECONDS),
        max_iterations=m.max_iterations,
        max_subquestions=m.max_subquestions,
        results_per_query=m.results_per_query,
    )
