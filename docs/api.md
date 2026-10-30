# API

Versioned REST under `/api/v1`. The full machine-readable contract is
[`packages/shared/openapi.json`](../packages/shared/openapi.json). In development, interactive docs are served at
`http://localhost:8000/docs`; they are disabled in production.

## Conventions

- **Auth**: browser sessions use HttpOnly cookies set by FastAPI (`dr_access` 15 min, `dr_refresh` scoped to
  `/api/v1/auth` and rotated on every refresh). Every protected endpoint authenticates and authorizes independently.
  Bearer tokens are accepted for server-to-server use and tests.
- **CSRF**: unsafe methods (POST/PUT/PATCH/DELETE) require `X-CSRF-Token` equal to the `dr_csrf` cookie
  (double submit), plus an allowed `Origin` when one is present. `GET /auth/csrf` issues the cookie. Webhooks are exempt
  and HMAC-verified instead.
- **Errors**: always the same envelope, never a stack trace:
  ```json
  {"error": {"code": "quota_exhausted", "message": "The AI provider's quota is exhausted…", "reference_id": "9f2c…", "details": {}}}
  ```
  `reference_id` matches the `X-Request-ID` header and the server logs. Validation errors are `422 validation_error`
  with `details.errors[] = {loc, msg, type}`. Rate limits are `429 rate_limited` with `Retry-After`.
- **Ownership**: objects belonging to other users return `404`.
- **Idempotency**: `POST /research` honours `Idempotency-Key` (same key returns the same job).
- **Pagination**: `GET /research` takes `limit` and `before` (a job ID) and returns `next_cursor`; other lists are bounded (see OpenAPI).

## Endpoints by area

| Area | Endpoints |
| --- | --- |
| Health | `GET /health/live`, `GET /health/ready`, `GET /health/dependencies` (admin) |
| Public | `GET /public/config`: feature flags, setup readiness, research modes and their limits (no secrets) |
| Auth | `GET csrf`, `GET session` (never 401s), `GET me`, `POST register`, `POST login`, `POST refresh`, `POST logout`, `POST verify-email`, `POST resend-verification`, `POST forgot-password`, `POST reset-password`, `POST change-password`, `GET sessions`, `DELETE sessions/{id}`, `POST sessions/revoke-others`, `GET google/start`, `GET google/callback` (all under `/auth`) |
| Account | `PATCH /account/profile`, `GET /account/export` (all personal data, JSON), `POST /account/delete` |
| Research | `POST /research`, `GET /research`, `GET /research/modes`, `GET /research/{id}`, `DELETE /research/{id}`, `POST /research/{id}/approve` (edit and approve plan), `POST /research/{id}/cancel`, `POST /research/{id}/resume`, `POST /research/{id}/followup`, `POST /research/{id}/feedback` (flag citations, rate sections) |
| Progress | `GET /research/{id}/stream` (SSE), `GET /research/{id}/events?after=N` (polling fallback) |
| Report | `GET /research/{id}/report[?version=]`, `GET /research/{id}/report/versions`, `GET /research/{id}/report/diff?a=&b=`, `POST /research/{id}/report/sections/{sid}/regenerate`, `GET /research/{id}/graph` |
| Sources | `GET /research/{id}/sources`, `GET /research/{id}/sources/{source_id}` (metadata, verified passages, text excerpt), `GET /research/{id}/evidence` |
| Export | `GET /research/{id}/export.md`, `GET /research/{id}/charts.csv`, `POST /research/{id}/exports` (PDF/DOCX background job), `GET /research/exports/{export_id}` |
| Sharing | `POST/DELETE /research/{id}/share`, `GET /shared/{token}` (only when `PUBLIC_REPORT_SHARING_ENABLED=1`) |
| Uploads | `POST /uploads` (multipart), `GET /uploads`, `DELETE /uploads/{id}` |
| Library | `GET /library`, `POST/DELETE /library/collections[/{id}]`, `POST /library/items`, `PATCH/DELETE /library/items/{id}`, `GET /library/related/{job_id}` |
| Templates | `GET/POST /templates`, `DELETE /templates/{id}` |
| Models | `GET /models` (admin-approved choices), `PUT /models/own-key` (when `ALLOW_USER_API_KEYS=1`) |
| Usage | `GET /usage`, `GET /notifications`, `POST /notifications/read-all` |
| Billing | `GET /billing/plans`, `GET /billing/subscription`, `POST /billing/checkout`, `POST /billing/portal`, `POST /billing/cancel`, `POST /billing/reconcile`, `POST /billing/webhook` (inert when `BILLING_ENABLED=0`) |
| Admin | `/admin/users`, `/admin/providers` (+ `keys`, `test`, `capabilities`, `{provider}/models`), `/admin/pricing`, `/admin/usage`, `/admin/jobs` (+ `retry`, `cancel`, `reconcile`), `/admin/system-health`, `/admin/dependencies`, `/admin/audit` |

## Creating research

```http
POST /api/v1/research
X-CSRF-Token: …
Idempotency-Key: 7d1e…            (optional)

{
  "question": "Compare managed Postgres providers for a regulated EU workload",
  "mode": "competitive",
  "options": {
    "include_domains": [], "exclude_domains": ["pinterest.com"],
    "date_from": "2024-01-01", "date_to": null, "language": "en",
    "source_preferences": ["official", "documentation"],
    "review_plan": true,
    "upload_ids": [],
    "model": {"provider": "anthropic", "model": "<exact model id>"},
    "budget_overrides": {"max_sources": 12}
  }
}
→ 202 {"job": {"id": "job_…", "status": "queued", "budgets": {…}, …}}
```

Refusals are explicit: `429 concurrency_limit` / `daily_limit`, `402 monthly_budget` / `billing_required` /
`mode_not_allowed`, `503 queue_unavailable`, `503 ai_not_configured` / `search_not_configured`
(with a setup hint), and `422` for invalid options or uploads.
Budget overrides can only lower limits.

## Live progress (SSE)

```
GET /api/v1/research/{id}/stream        (Last-Event-ID: 41 | ?after=41)

id: 42
event: progress
data: {"seq":42,"type":"query","stage":"searching","level":"info","message":"Searched “…”","data":{…},"at":"…"}

event: status
data: {…job…}                  (when idle in a terminal or paused state)

event: end
data: {"reason":"finished"}

: keep-alive
```

Event types and stages are enumerated in [`packages/shared/contracts.json`](../packages/shared/contracts.json).
Reconnect with the last `id` to resume without gaps. If the stream can't be held open (proxies, flaky networks), poll
`GET /research/{id}/events?after=N`, which returns `{events, job}`.

## Report shape (abridged)

```json
{
  "id": "rep_…", "version": 2, "status": "complete|partial", "partial_reason": null, "is_demo": false,
  "title": "…", "executive_summary": [Paragraph], "key_findings": [Paragraph & {"strength": {"label","basis",…}}],
  "sections": [{"id","title","paragraphs":[Paragraph]}], "conflicts": [...], "unknowns": [{"question","why"}],
  "limitations": ["…"], "conclusions": [...], "recommendations": [...],
  "tables": [{"type":"matrix","columns":[…],"rows":[{"attribute","cells":[{"value","evidence_ids","sources"}]}]}],
  "charts": [{"kind":"data|process","type":"bar|line|donut|…","title","unit","series":[{"points":[{"x","y","evidence_id","source_number"}]}],"sources":[…],"notes":[…]}],
  "citation_validation": {"markers","valid","invalid","sentences","cited_sentences","uncited_sentences"},
  "support_check": {"checked","supported","partially_supported","not_supported","not_checked"},
  "methodology": {"plan","queries","providers","models","budgets","usage","timestamps"},
  "source_stats": {…}, "freshness": {"label","newest","oldest"}, "warnings": ["…"]
}
Paragraph = {"id", "segments": [{"text", "evidence_ids": ["E12"], "sources": [3], "support": "supported|partially_supported|not_supported|unverified|uncited", "support_note"}]}
```
