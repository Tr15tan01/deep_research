# Configuration

All configuration comes from environment variables, validated at startup by `apps/api/app/core/config.py` (Pydantic
Settings). [`.env.example`](../.env.example) documents every variable, and a test fails if a setting is missing from it.
The web app reads only `API_INTERNAL_URL` (server-side).

## Rules

- **Feature flags are `1` or `0`.** Anything else (`true`, `yes`, empty for a required flag) fails startup.
- **Feature flags, credentials and security policy are separate.** Flags turn product features on and off. Credentials
  enable providers. Security controls (authentication, authorization, tenant isolation, SSRF protection, CSRF,
  injection handling, upload sandboxing) have no flag.
- **Email verification precedence**: `EMAIL_VERIFICATION_ENABLED` is canonical. `REQUIRE_EMAIL_VERIFICATION` is a
  compatibility alias consulted only when the canonical flag is unset. If both are set and disagree, the canonical flag
  wins and a startup warning is logged (also visible in **Admin → System health**).
- **Disabled means gone, not just hidden.** `GOOGLE_AUTH_ENABLED=0` removes the button *and* makes the OAuth
  endpoints return `404 feature_disabled`. The same applies to uploads, sharing, billing, BYOK and model selection.
  The UI reads flags from `GET /api/v1/public/config`, and the backend enforces them independently.
- **Misconfigured is different from disabled.** For example, `GOOGLE_AUTH_ENABLED=1` without client credentials shows
  "enabled but not configured" instead of a broken button, and fails startup in production. A missing AI or search key
  makes `POST /research` return an actionable `503 ai_not_configured` / `search_not_configured` *before* a job is
  created, so nothing retries against a provider that cannot work.

## Production refusals

With `APP_ENV=production` (or `staging`) startup aborts when:

- `AUTH_SECRET` is shorter than 32 characters
- `MONGODB_URI` is missing or `mongomock://`
- `REDIS_URL` is missing
- `FRONTEND_URL` is not `https://`
- `DEMO_MODE=1`
- `INTERNAL_PROXY_TOKEN` is set but shorter than 32 characters
- email verification or password reset is on but `SMTP_HOST` / `EMAIL_FROM` are missing
- `ENCRYPTION_KEYS` is missing
- `BILLING_ENABLED=1` without Paddle API key and webhook secret
- `GOOGLE_AUTH_ENABLED=1` without client ID and secret

`EMBEDDED_WORKER=1` is allowed in production (single-service hosting, e.g. the free Render layout) and logs a
warning. When the API has a public URL, also set `INTERNAL_PROXY_TOKEN` on the API and the web app: the API then
rejects every request except `/health/*` that lacks the token, and trusts the client IP reported by the web proxy for
rate limiting.

## Modes and budgets

Each research mode has explicit limits (`apps/api/app/research/modes.py`, also returned by `/public/config`):
searches, sources, tool calls, output tokens, estimated cost, duration, follow-up iterations, sub-questions and
results per query. The effective budget is `min(mode limit, global MAX_* setting, user override)`, so user overrides
can only lower limits. Plans (when billing is on) can restrict modes and set their own daily, concurrency and cost
limits.

| Mode | Searches | Sources | Duration | Follow-up rounds |
| --- | --- | --- | --- | --- |
| Quick | 8 | 8 | 5 min | 0 |
| Standard | 16 | 15 | 15 min | 1 |
| Deep | 25 | 30 | 30 min | 2 |
| Academic | 22 | 25 | 25 min | 1 |
| Competitive / Technology / Market | 20 | 22–24 | 20 min | 1 |
| Uploaded documents | 0 (no web) | 10 | 15 min | 0 |
| Verify a claim | 10 | 12 | 10 min | 0 |
| Counterarguments | 12 | 14 | ~12 min | 0 |

## Billing disabled

`BILLING_ENABLED=0` (the default) makes billing endpoints inert, hides the billing UI, and applies the configured
development limits (`DAILY_RESEARCH_JOBS_PER_USER`, `MAX_CONCURRENT_RESEARCH_JOBS_PER_USER`,
`MONTHLY_COST_LIMIT_USD_PER_USER`). Nothing else changes.

## Demo mode

`DEMO_MODE=1` swaps in deterministic, offline AI and search providers that generate synthetic content on reserved
`.invalid` domains. Every demo job, report and export is labelled as synthetic in the UI and in the data (`is_demo`).
Demo mode exists for development, screenshots and CI. It is refused in production and never presented as research.
`DEMO_STEP_DELAY_MS` slows demo calls so the live view can be watched.
