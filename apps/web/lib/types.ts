// API contracts (mirrors the FastAPI responses under /api/v1). Kept in one place so pages
// and tests share a single source of truth for shapes.

export type Role = "USER" | "ADMIN" | "CONTENT_MANAGER";

export interface User {
  id: string;
  email: string;
  name: string;
  role: Role;
  email_verified: boolean;
  has_password: boolean;
  google_linked: boolean;
  created_at: string;
  plan: string;
  preferences: Record<string, unknown>;
}

export interface ApiErrorBody {
  error: { code: string; message: string; reference_id: string; details: Record<string, unknown> };
}

export interface ModeInfo {
  key: string;
  label: string;
  description: string;
  estimated_minutes: [number, number];
  scholarly: boolean;
  web: boolean;
  comparison_matrix: boolean;
  limits: Record<string, number>;
}

export interface PublicConfig {
  app_name: string;
  environment: string;
  features: {
    google_auth: boolean;
    google_auth_configured: boolean;
    email_verification: boolean;
    password_reset: boolean;
    public_signup: boolean;
    billing: boolean;
    uploads: boolean;
    charts: boolean;
    public_sharing: boolean;
    user_model_selection: boolean;
    user_api_keys: boolean;
    demo_mode: boolean;
    content_safety: boolean;
  };
  setup: { ai_ready: boolean; search_ready: boolean; scholarly_search: boolean };
  limits: { max_file_size_mb: number; max_uploads_per_job: number; max_question_chars: number };
  modes: ModeInfo[];
}

export type JobStatus =
  | "queued"
  | "planning"
  | "awaiting_approval"
  | "searching"
  | "extracting"
  | "verifying"
  | "synthesizing"
  | "completed"
  | "failed"
  | "cancelled"
  | "waiting_for_retry";

export interface SubQuestion {
  id: string;
  question: string;
  rationale?: string;
  queries: string[];
  status?: "open" | "covered" | "insufficient";
  missing?: string;
}

export interface Plan {
  objective: string;
  subquestions: SubQuestion[];
  entities: string[];
  attributes: string[];
  out_of_scope: string[];
  edited_by_user?: boolean;
}

export interface Usage {
  tool_calls?: number;
  search_calls?: number;
  llm_calls?: number;
  input_tokens?: number;
  output_tokens?: number;
  extracted_pages?: number;
  cost_usd_est?: number;
  cost_unknown_calls?: number;
  llm_errors?: number;
}

export interface Job {
  id: string;
  kind: string;
  question: string;
  title?: string | null;
  mode: string;
  mode_label: string;
  status: JobStatus;
  stage?: string | null;
  options: Record<string, unknown>;
  plan?: Plan | null;
  clarifications: string[];
  assessment?: { clarifying_questions?: string[]; assumptions_if_unclarified?: string[]; restated_question?: string } | null;
  usage: Usage;
  budgets: Record<string, number>;
  model_config?: Record<string, { provider: string; model: string; via: string } | null> | null;
  fallbacks: { task: string; from: string; to: string; reason: string; at: string }[];
  attempts: number;
  last_error?: { code: string; message: string; retryable?: boolean; resumable?: boolean; at?: string } | null;
  dead_lettered: boolean;
  cancel_requested: boolean;
  report_id?: string | null;
  report_version?: number | null;
  partial: boolean;
  is_demo: boolean;
  parent_job_id?: string | null;
  event_seq: number;
  next_attempt_at?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  deadline_at?: string | null;
  resumable: boolean;
}

export interface JobEvent {
  seq: number;
  type: string;
  stage?: string | null;
  level: "info" | "warning" | "error";
  message: string;
  data: Record<string, unknown>;
  at: string;
}

export interface Source {
  id: string;
  number: number;
  url: string;
  canonical_url: string;
  final_url?: string | null;
  domain: string;
  title: string;
  snippet?: string;
  provider: string;
  published_at?: string | null;
  published_at_basis?: string | null;
  author?: string | null;
  publisher?: string | null;
  status: "candidate" | "extracted" | "inaccessible" | "rejected";
  source_type?: "primary" | "secondary" | "commentary" | "unknown" | null;
  source_type_basis?: string | null;
  source_type_reason?: string | null;
  relevance?: number | null;
  reliability_notes?: string | null;
  content_kind?: string | null;
  word_count?: number | null;
  injection_flags?: string[] | null;
  inaccessible_reason?: string | null;
  retrieved_at?: string | null;
  subquestion_ids?: string[];
  extract_provider?: string | null;
  extract_warnings?: string[] | null;
  metadata?: Record<string, unknown>;
  verified_evidence?: number;
  is_demo?: boolean;
}

export interface Segment {
  text: string;
  evidence_ids: string[];
  sources: number[];
  support: "supported" | "partially_supported" | "not_supported" | "unverified" | "uncited" | "n/a";
  support_note: string;
  dropped_markers?: string[];
}

export interface Paragraph {
  id: string;
  segments: Segment[];
}

export interface Strength {
  label: "strong" | "moderate" | "limited" | "contested" | "unsupported";
  basis: string;
  independent_domains: number;
  primary_sources: number;
}

export interface ChartPoint {
  x: string;
  y: number;
  y2?: number;
  label?: string;
  evidence_ids: string[];
  sources: number[];
  estimated?: boolean;
}

export interface ChartSpec {
  id: string;
  type: "bar" | "line" | "donut";
  title: string;
  x_label?: string;
  y_label?: string;
  unit?: string;
  series: { name: string; points: ChartPoint[] }[];
  notes: string[];
  kind: "data" | "process";
}

export interface MatrixTable {
  id: string;
  type: "matrix";
  title: string;
  columns: string[];
  rows: { attribute: string; cells: { value: string; evidence_ids: string[]; sources: number[] }[] }[];
  notes: string[];
}

export interface BibEntry {
  number: number;
  title: string;
  url: string;
  domain?: string;
  publisher?: string | null;
  author?: string | null;
  published_at?: string | null;
  retrieved_at?: string | null;
  source_type?: string | null;
  content_kind?: string | null;
  cited: boolean;
}

export interface Report {
  id: string;
  job_id: string;
  version: number;
  status: "complete" | "partial";
  partial_reason?: string | null;
  is_demo: boolean;
  question: string;
  mode: string;
  title: string;
  executive_summary: Paragraph[];
  key_findings: (Paragraph & { strength?: Strength | null })[];
  sections: { id: string; title: string; paragraphs: Paragraph[]; regenerated_at?: string }[];
  conflicts: (Paragraph & { topic: string })[];
  limitations: string[];
  unknowns: { question: string; why: string }[];
  conclusions: Paragraph[];
  recommendations: Paragraph[];
  tables: MatrixTable[];
  charts: ChartSpec[];
  citation_validation: {
    markers?: number;
    valid?: number;
    invalid?: number;
    sentences?: number;
    cited_sentences?: number;
    uncited_sentences?: number;
    invalid_ids?: string[];
  };
  support_check: { checked?: number; supported?: number; partially_supported?: number; not_supported?: number; not_checked?: number };
  insufficient_evidence: boolean;
  contradictions: { topic: string; evidence_ids: string[]; explanation: string }[];
  methodology: {
    objective: string;
    subquestions: SubQuestion[];
    plan_edited_by_user: boolean;
    queries: { subq_id: string; query: string; kind: string; provider?: string | null; results: number; from_cache: boolean; iteration: number; error?: string | null }[];
    search_providers: string[];
    model_config?: Record<string, { provider: string; model: string; via: string } | null> | null;
    fallbacks: { task: string; from: string; to: string; reason: string }[];
    budgets: Record<string, number>;
    usage: Usage;
    assumptions: string[];
    clarifications: string[];
    iterations: number;
    stop_reason?: string | null;
    rejected_candidates: number;
    started_at?: string | null;
    executed_at: string;
    duration_seconds?: number | null;
    mode: string;
  };
  source_stats: { total: number; extracted: number; inaccessible: number; by_type: Record<string, number>; domains: number; abstract_only: number; injection_flagged: number };
  freshness: { dated: number; undated: number; newest?: string | null; oldest?: string | null; median_age_days?: number | null; label: string };
  strength_criteria: Record<string, string>;
  warnings: string[];
  change_note?: string;
  created_at: string;
  bibliography: BibEntry[];
  shared: boolean;
}

export interface Evidence {
  id: string;
  kind: "claim" | "datapoint";
  source_id: string;
  source_number: number;
  subquestion_id: string;
  claim: string;
  quote: string;
  stance?: string;
  claim_type?: string;
  verified: boolean;
  match_method?: string;
  match_score?: number;
  source_type?: string;
  published?: string | null;
  domain?: string;
  metric?: string;
  entity?: string;
  value?: number;
  unit?: string;
  period?: string | null;
}

export interface SourceDetail {
  source: Source;
  passages: {
    evidence_id: string;
    claim: string;
    quote: string;
    verified: boolean;
    match_method?: string;
    stance?: string;
    kind?: string;
    subquestion_id?: string;
    context_before: string;
    context_after: string;
  }[];
  excerpt: string;
  content_kind?: string | null;
}

export interface UsageSnapshot {
  plan: { plan: string; label: string; daily_jobs: number; concurrent_jobs: number; monthly_cost_usd: number; allowed_modes: string[]; max_uploads_per_job: number };
  billing_enabled: boolean;
  active_jobs: number;
  jobs_last_24h: number;
  month_cost_usd_est: number;
  can_start_jobs: boolean;
  notice?: string | null;
  cost_note: string;
}

export interface Upload {
  id: string;
  filename: string;
  kind: string;
  size: number;
  status: "processing" | "ready" | "failed";
  chars?: number;
  pages?: number;
  warnings: string[];
  scan?: string;
  injection_suspected: boolean;
  created_at: string;
  expires_at?: string;
  error?: string;
}

export interface Template {
  id: string;
  name: string;
  description: string;
  question_template: string;
  mode: string;
  options?: Record<string, unknown>;
}
