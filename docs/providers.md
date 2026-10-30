# AI and search providers

The LLM and the search stack are configured independently. Changing the model never changes how the web is searched.

## AI providers

| Provider | Adapter | Structured output | Model discovery | Notes |
| --- | --- | --- | --- | --- |
| Google Gemini | `GeminiProvider` (REST `generativelanguage.googleapis.com`) | native JSON schema (`responseSchema`) | yes: lists models with token limits | Safety blocks map to `content_blocked`. `retryDelay` is honoured. |
| OpenAI | `OpenAIProvider` (Chat Completions) | `response_format: json_schema` | yes (IDs only) | Some reasoning models reject `temperature`: turn it off in the capability overrides. |
| Anthropic | `AnthropicProvider` (Messages API) | forced tool call with the schema as input | yes (IDs only) | `overloaded_error` → retryable `unavailable`. Credit errors → `billing` (never retried). |
| OpenAI-compatible | `OpenAIProvider` with `OPENAI_COMPATIBLE_BASE_URL` | prompt + validation + one repair | if the server implements `/models` | Conservative defaults. Uses `max_tokens`. Set real limits in the admin capability panel. |
| Demo | `DemoProvider` | n/a | n/a | Deterministic, offline, labelled synthetic. Refused in production. |

**No model names are hard-coded.** Administrators type the exact model ID, or pick from discovery, under
**Admin → AI providers**. A connection test sends a tiny real request to that exact model, and its result (latency or
normalized error) is stored as the provider's health. Nothing is reported healthy without a real call.

### Capability registry (`llm/capabilities.py`)

Each model has a resolved capability set: context window, max output tokens, native JSON schema, tool calling,
streaming, temperature, system prompt. Resolution order: conservative per-provider defaults (flagged as assumptions)
→ limits discovered from the provider → admin overrides. The pipeline sizes its passages, batches and ledgers from the
resolved context window, and picks the structured-output strategy from the flags.

### Per-task routing

`planning`, `extraction` (reading sources), `verification`, `synthesis` (writing), `charts` (comparison matrix) and
`routine` (question assessment). Each can point at its own model. An optional **cheaper model** handles `routine`, and
handles extraction and verification when no task model is set. Users may choose from an admin-approved list when
`ALLOW_USER_MODEL_SELECTION=1`.

### Errors (`llm/base.py: ErrorKind`)

| Kind | Retried? | Job outcome |
| --- | --- | --- |
| `rate_limited`, `timeout`, `provider_unavailable` | yes, bounded with jitter, honouring `Retry-After` | job-level retry, then dead-letter |
| `malformed_output` (unparseable after one repair) | no | step skipped with a warning where safe, or partial report |
| `invalid_credentials`, `quota_exhausted`, `billing_exhausted`, `not_configured`, `model_not_found`, `unsupported_capability`, `context_overflow` | **never** | job fails as *resumable* with an actionable message |
| `content_blocked` | no | the provider declined the content; the job fails with that message, and other errors in that batch are handled per step |
| `budget_exhausted` | no | job stops gracefully with a partial report |

### Fallback

Only when `AI_FALLBACK_ENABLED=1` **and** an admin configured a fallback model, and only when the primary cannot serve
the call: rate-limited, unavailable, timing out, out of quota or billing credit, rejecting its key, or the model is
missing or lacks a required capability (`FALLBACK_ELIGIBLE` in `llm/base.py`). The fallback still runs within the
job's token and cost budgets. Malformed output, content blocks and context overflow never trigger a fallback. Every
switch is appended to `job.fallbacks`, emitted as a warning event, and shown in the report's methodology. The system
never silently changes models.

### Credentials

Environment variables win and are shown read-only in the admin UI. Keys saved in the UI are encrypted with AES-256-GCM
(`ENCRYPTION_KEYS`, rotation supported; the provider name is bound as associated data) and stored in `app_settings`.
They are never returned to the browser: only "configured", the source and the last four characters. Bring-your-own-key
(`ALLOW_USER_API_KEYS=1`) stores per-user keys the same way in `user_api_credentials`, and they are used only for that
user's jobs.

### Cost accounting

Token usage comes from provider responses (estimated from text length when a provider omits it, and labelled as
estimated). Cost = tokens × the admin **pricing table**, where each entry carries an `as_of` date and a note. Costs are
shown as estimates and never as the provider's invoice. Budgets (`max_cost_usd` per job, `MONTHLY_COST_LIMIT_USD_PER_USER`)
are enforced server-side before and during execution.

## Search and extraction providers

Each provider does a different job. They are not interchangeable:

| Provider | Search | Extraction | Notes |
| --- | --- | --- | --- |
| **Firecrawl** | `/v1/search` | `/v1/scrape` (markdown) | Good general default: one key covers both. |
| **Tavily** | `/search` (optionally with raw content) | `/extract` | Strong for research-style queries. |
| **Brave Search** | Web Search API | — | Search only. Pages are fetched by the built-in fetcher. |
| **OpenAlex** | scholarly works (keyless) | abstracts only | Academic mode. Abstracts are labelled `abstract only`, never presented as full text. |
| **Built-in fetcher** | — | SSRF-guarded HTTP GET + trafilatura | Always last in the extraction chain. Respects size and time limits; no auth bypass. |

Search keys can be set as environment variables or saved in **Admin → AI providers → Search providers** (encrypted
in MongoDB like AI keys, so every worker sees them; environment values win). `SEARCH_PROVIDER` picks the primary. With `SEARCH_FALLBACK_ENABLED=1`, other *configured* providers are tried on
failure, and each result records the provider that produced it. Results and extractions are cached in Redis for
`SEARCH_CACHE_TTL_SECONDS`. Search calls count against the job's search budget, and extraction counts against tool calls.
Domain include/exclude and date filters are applied both in the provider request (where supported) and
deterministically in `rank`.

Retrieved content is **untrusted data**: it is scanned for instruction-like text, wrapped in per-call random
boundaries in prompts, and can never trigger tools or change configuration (see [security.md](security.md)).

The product respects site terms: there is no paywall or login bypass, no CAPTCHA solving, and inaccessible pages are
recorded as inaccessible.

## Adding a provider

1. Implement the protocol in `llm/providers.py` (`generate`, `stream`, `list_models`) or `search/providers.py`
   (`search` and/or `extract`), mapping every failure to `ErrorKind`/`SearchError`.
2. Add conservative defaults to `_PROVIDER_DEFAULTS` (LLM) and the provider name to the settings `Literal`s.
3. Add `respx`-mocked tests for success, schema handling and every error class (see `tests/test_providers.py`), and a
   `@pytest.mark.live` smoke test.
4. `make contracts` if public enums changed.
