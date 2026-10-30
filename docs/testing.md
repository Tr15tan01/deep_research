# Testing

| Layer | Location | Runs against | Command |
| --- | --- | --- | --- |
| Backend unit + integration | `apps/api/tests` | in-memory Mongo (mongomock), fakeredis, `respx`-mocked provider HTTP | `make test-api` |
| Real-Redis worker tests | `apps/api/tests/test_worker_redis.py` | a real `redis-server` subprocess (skipped if the binary is missing) | included in `make test-api` |
| Live provider smoke tests | `@pytest.mark.live` in `test_providers.py` | real provider APIs | `LIVE_TESTS=1 make test-api` (needs keys) |
| Frontend unit | `apps/web/tests/unit` (Vitest + Testing Library, jsdom) | components and client logic | `make test-web` |
| End-to-end | `apps/web/tests/e2e` (Playwright, desktop + Pixel 7) | real FastAPI (demo providers, embedded worker) behind the production Next.js build | `make e2e` |
| Agent evaluation | `tests/eval` | full pipeline, scored | `make eval` / `make eval LIVE=1` |
| Contracts | `apps/api/tests/test_contracts.py`, `apps/web/tests/unit/contracts.test.ts` | generated `packages/shared` | `make contracts-check` |

**Mocked vs live.** Everything in CI uses mocked HTTP or the deterministic demo providers. Those tests prove the
system's behaviour (retries, budgets, citations, recovery), *not* that a given provider or model currently works.
Live checks are separate, opt-in, and reported separately. Do not read a green CI run as a live integration result.

## What is covered

**Auth and accounts**: registration, login, logout, generic errors (no enumeration), weak passwords, CSRF on unsafe
methods, refresh rotation and reuse detection, immediate session revocation, email-verification enforcement (both
flags), password reset (single use, expiry), Google disabled / misconfigured / never merging unverified accounts, rate
limits, signup disabled, data export and account deletion, security headers.

**Providers**: OpenAI, OpenAI-compatible, Anthropic and Gemini request shapes; structured output (native schema,
forced tool, prompt and repair); error mapping for every status class; bounded retries honouring `Retry-After`;
timeouts; model discovery; explicit, recorded fallback; task routing; Tavily, Brave, Firecrawl and OpenAlex mapping;
search fallback.

**Pipeline and jobs**: full demo pipeline with citation resolution; prompt-injection source flagged; plan
review and edit; crash recovery from checkpoint; expired-lease recovery; transient errors retried while auth errors are
not; quota exhaustion not retried, dead-letter after max attempts; cancellation (running and queued) keeps partial
results; budget exhaustion yields labelled partial reports; tenant isolation; SSE streaming and resume from
`Last-Event-ID`; actionable not-configured errors; queue-unavailable refusal; idempotent creation; concurrency limits;
section regeneration and versions; follow-ups reusing sources; background exports; uploads and documents mode;
cascade deletes; usage tracking; worker consuming from real Redis; lost deliveries reconciled.

**Security units**: SSRF (blocked ranges, DNS rebinding, redirect to internal, size cap), injection detection and
wrapping, quote verification, number-in-quote, strength labels, freshness, URL canonicalization, citation resolver
(including untrusted stray markers), charts only from verified points, sandboxed parsers and zip bombs, log
redaction, encryption key rotation, JWT tamper, config flag parsing and production refusals.

**Admin and billing**: admin-only endpoints, bootstrap admin, encrypted key storage (never echoed), env keys
read-only, connection test reporting missing keys, model-selection policy, self-demotion guard, billing disabled is
inert, webhook signature and idempotency, plan limits.

**Frontend unit**: API client (CSRF, error envelope, single refresh retry, no loops, network errors, field errors);
`safeHref` / `safeNext`; live-run derivation from events (no invented progress); citation chips open the exact
evidence; unsupported and uncited statements visibly marked; Google flag states; timeline stages match backend
contracts.

**End-to-end**: register, sign out, sign in; generic login errors; Google absent when disabled; protected-route
redirects; no tokens readable by JS; live run with real events → cited report → source panel → chart table →
Markdown export → sources page; leaving and returning to a running job; going offline mid-run and recovering;
cancellation; cross-user access denied (UI and API); admin-only APIs; provider page shows no secrets; mobile layout
without horizontal overflow.

## Running e2e locally

```bash
cd apps/web
npx playwright install chromium     # once
npx playwright test                 # builds the web app and starts both servers on :3100 / :8100
E2E_SKIP_BUILD=1 npx playwright test   # reuse an existing .next build
```
