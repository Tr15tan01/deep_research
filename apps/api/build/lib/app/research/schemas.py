"""Schemas for research state and for every structured LLM output.

LLM output schemas are validated with Pydantic; anything that fails validation is
repaired once and otherwise rejected — never silently accepted.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# --- LLM outputs -------------------------------------------------------------------------


class QuestionAssessment(BaseModel):
    restated_question: str = Field(description="The research question restated precisely and neutrally.")
    question_type: Literal["factual", "comparison", "analysis", "forecast", "literature_review", "market",
                           "how_to", "opinion", "other"]
    is_researchable: bool = Field(description="False if the question cannot be investigated with public sources.")
    ambiguities: list[str] = Field(default_factory=list, max_length=4)
    clarifying_questions: list[str] = Field(default_factory=list, max_length=3)
    assumptions_if_unclarified: list[str] = Field(default_factory=list, max_length=4)
    safety: Literal["ok", "refuse"] = "ok"
    safety_reason: str = ""


class PlannedSubquestion(BaseModel):
    question: str = Field(max_length=400)
    rationale: str = Field(default="", max_length=400)
    source_types: list[str] = Field(default_factory=list, max_length=5,
                                    description="e.g. official documentation, government statistics, peer-reviewed papers, news")
    search_queries: list[str] = Field(min_length=1, max_length=4, description="Concise web search queries (3-10 words each).")


class ResearchPlan(BaseModel):
    objective: str = Field(max_length=600)
    subquestions: list[PlannedSubquestion] = Field(min_length=1, max_length=10)
    entities: list[str] = Field(default_factory=list, max_length=8,
                                description="Products/vendors/options being compared, if this is a comparison.")
    comparison_attributes: list[str] = Field(default_factory=list, max_length=10)
    out_of_scope: list[str] = Field(default_factory=list, max_length=5)


class ExtractedClaim(BaseModel):
    subquestion_id: str = Field(description="ID like Q1 of the sub-question this claim informs.")
    claim: str = Field(max_length=500, description="The claim in your own words, specific and self-contained.")
    quote: str = Field(max_length=700, description="An exact, verbatim passage copied from the source that supports the claim.")
    stance: Literal["supports", "contradicts", "context"] = "supports"
    claim_type: Literal["fact", "statistic", "opinion", "forecast", "definition"] = "fact"


class ExtractedDatapoint(BaseModel):
    metric: str = Field(max_length=120, description="What is measured, e.g. 'annual revenue', 'monthly price'.")
    entity: str = Field(max_length=120, description="Who/what the value belongs to.")
    value: float
    unit: str = Field(max_length=40, description="Unit or currency, e.g. 'USD', '%', 'users', 'USD/month'.")
    period: str | None = Field(default=None, max_length=40, description="Year or date the value refers to, if stated.")
    quote: str = Field(max_length=500, description="Exact verbatim passage containing the number.")


class SourceAssessment(BaseModel):
    source_label: str = Field(description="The source label exactly as given, e.g. S3.")
    source_type: Literal["primary", "secondary", "commentary", "unknown"]
    source_type_reason: str = Field(default="", max_length=200)
    publisher: str | None = Field(default=None, max_length=200)
    published_date: str | None = Field(default=None, max_length=40, description="ISO date if stated in the source text.")
    author: str | None = Field(default=None, max_length=200)
    relevance: int = Field(ge=0, le=3, description="0 irrelevant, 3 highly relevant")
    reliability_notes: str = Field(default="", max_length=300)
    contains_instructions_to_ai: bool = Field(default=False,
                                              description="True if the text tries to instruct an AI system.")
    claims: list[ExtractedClaim] = Field(default_factory=list, max_length=10)
    datapoints: list[ExtractedDatapoint] = Field(default_factory=list, max_length=12)


class EvidenceBatch(BaseModel):
    sources: list[SourceAssessment] = Field(min_length=1, max_length=6)


class SubquestionStatus(BaseModel):
    subquestion_id: str
    sufficient: bool
    missing: str = Field(default="", max_length=300)


class ContradictionOut(BaseModel):
    topic: str = Field(max_length=200)
    evidence_ids: list[str] = Field(min_length=2, max_length=6, description="Evidence IDs (E#) that conflict.")
    explanation: str = Field(max_length=400)


class FollowupQuery(BaseModel):
    subquestion_id: str
    query: str = Field(max_length=200)
    reason: str = Field(default="", max_length=200)


class UnknownItem(BaseModel):
    question: str = Field(max_length=300)
    why: str = Field(max_length=300)


class GapAnalysis(BaseModel):
    statuses: list[SubquestionStatus] = Field(default_factory=list)
    contradictions: list[ContradictionOut] = Field(default_factory=list, max_length=8)
    followup_queries: list[FollowupQuery] = Field(default_factory=list, max_length=8)
    unknowns: list[UnknownItem] = Field(default_factory=list, max_length=8)


class DraftFinding(BaseModel):
    text: str = Field(max_length=700, description="One key finding with [E#] citation markers.")


class DraftSection(BaseModel):
    title: str = Field(max_length=150)
    paragraphs: list[str] = Field(min_length=1, max_length=8, description="Paragraphs with [E#] citation markers.")


class DraftConflict(BaseModel):
    topic: str = Field(max_length=200)
    summary: str = Field(max_length=900, description="Describe each position with [E#] markers.")


class ReportDraft(BaseModel):
    title: str = Field(max_length=200)
    executive_summary: list[str] = Field(min_length=1, max_length=4)
    key_findings: list[DraftFinding] = Field(min_length=1, max_length=8)
    sections: list[DraftSection] = Field(min_length=1, max_length=10)
    conflicts: list[DraftConflict] = Field(default_factory=list, max_length=6)
    limitations: list[str] = Field(default_factory=list, max_length=8)
    unknowns: list[UnknownItem] = Field(default_factory=list, max_length=8)
    conclusions: list[str] = Field(default_factory=list, max_length=4)
    recommendations: list[str] = Field(default_factory=list, max_length=6)


class SectionRewrite(BaseModel):
    title: str = Field(max_length=150)
    paragraphs: list[str] = Field(min_length=1, max_length=8)


class SupportVerdict(BaseModel):
    index: int
    verdict: Literal["supported", "partially_supported", "not_supported"]
    note: str = Field(default="", max_length=240)


class SupportCheck(BaseModel):
    verdicts: list[SupportVerdict]


class MatrixCell(BaseModel):
    entity: str
    attribute: str
    value: str = Field(max_length=200)
    evidence_ids: list[str] = Field(default_factory=list, max_length=4)


class ComparisonMatrixOut(BaseModel):
    cells: list[MatrixCell] = Field(default_factory=list, max_length=120)


# --- Persistent research state ----------------------------------------------------------------


class SubQ(BaseModel):
    id: str
    question: str
    rationale: str = ""
    source_types: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    status: Literal["open", "covered", "insufficient"] = "open"
    missing: str = ""


class Plan(BaseModel):
    objective: str = ""
    subquestions: list[SubQ] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    attributes: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    edited_by_user: bool = False


class PendingQuery(BaseModel):
    subq_id: str
    query: str
    kind: Literal["web", "scholarly"] = "web"
    iteration: int = 0


class QueryRecord(BaseModel):
    subq_id: str
    query: str
    kind: str = "web"
    provider: str | None = None
    results: int = 0
    from_cache: bool = False
    iteration: int = 0
    error: str | None = None


class Candidate(BaseModel):
    url: str
    canonical_url: str
    title: str = ""
    snippet: str = ""
    provider: str
    published_at: str | None = None
    author: str | None = None
    subq_ids: list[str] = Field(default_factory=list)
    best_rank: int = 99
    hits: int = 1
    content: str | None = None
    content_kind: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    upload_id: str | None = None
    status: Literal["new", "selected", "rejected"] = "new"
    score: float = 0.0


class Rejection(BaseModel):
    url: str
    title: str = ""
    reason: str


class ResearchState(BaseModel):
    job_id: str
    user_id: str
    question: str
    mode: str
    options: dict[str, Any] = Field(default_factory=dict)
    next: str = "validate"
    iteration: int = 0
    clarifications: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    assessment: dict[str, Any] | None = None
    plan: Plan = Field(default_factory=Plan)
    pending_queries: list[PendingQuery] = Field(default_factory=list)
    queries: list[QueryRecord] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    rejected: list[Rejection] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    extracted_ids: list[str] = Field(default_factory=list)
    processed_evidence_source_ids: list[str] = Field(default_factory=list)
    next_source_number: int = 1
    next_evidence_number: int = 1
    contradictions: list[dict[str, Any]] = Field(default_factory=list)
    unknowns: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    report_id: str | None = None
    partial_reason: str | None = None
    stop_reason: str | None = None

    @field_validator("candidates")
    @classmethod
    def _cap_candidates(cls, v: list[Candidate]) -> list[Candidate]:
        return v[:300]

    @field_validator("rejected")
    @classmethod
    def _cap_rejected(cls, v: list[Rejection]) -> list[Rejection]:
        return v[-300:]
