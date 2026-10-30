# Security and privacy

Defence in depth: the frontend is untrusted, retrieved content is untrusted, model output is untrusted. Authorization,
budgets and policy are deterministic Python on the server.

## Threat model (summary)

| Boundary | Threat | Controls |
| --- | --- | --- |
| Browser ↔ web/API | session theft, CSRF, XSS, clickjacking | HttpOnly `SameSite=Lax` cookies (`Secure` on https); no tokens in JS storage; double-submit CSRF token plus `Origin` check on unsafe methods; strict CSP and security headers on both web and API; React escaping; only `http(s)` links are rendered clickable (`safeHref`). |
| Accounts | credential stuffing, enumeration, token replay | Argon2id; per-IP and per-account rate limits (Redis); generic login and reset responses; single-use, hashed, short-lived reset and verification tokens; refresh-token rotation with reuse detection (reuse revokes the session family); per-request session check so revocation is immediate. |
| OAuth | CSRF, code injection, account takeover | Authorization code + PKCE (S256) + `state` + `nonce` in a signed, short-lived cookie; exact redirect URI; ID-token validation; **never** auto-merges into an unverified local account with the same email. |
| Tenancy | IDOR | Every repository query is scoped by the authenticated `user_id`. Objects of other users return 404, not 403. Covered by API and e2e tests. |
| Agent → web | SSRF, DNS rebinding, metadata theft | `security/ssrf.py`: http/https only; ports from `FETCH_ALLOWED_PORTS`; blocks loopback, private, link-local, CGNAT, multicast, reserved, ULA and `169.254.169.254`; blocks internal hostnames (`.internal`, `.local`, `metadata`, …); resolves DNS, rejects if *any* address is non-public, **connects to the pinned IP** with SNI and Host set (no second lookup); re-validates every redirect hop; size cap and timeouts; no proxy env, no cookies, no auth headers. |
| Retrieved content → LLM | indirect prompt injection | Content is wrapped in random per-call boundaries and labelled as data. A heuristic scanner flags instruction-like text (and the reading model reports it too). Flagged sources are shown in the UI. Tools are allow-listed and none can be invoked by content. Credentials never enter model context. Quotes must exist verbatim in the retrieved text, so injected "facts" cannot be cited unless the page really says them. |
| Model output | fabricated citations, malformed data | Pydantic validation of every structured output; citation IDs must resolve to stored, verified evidence or are removed and counted; chart points must come from verified datapoints; model-proposed domains, dates and authors are only accepted if present in the source text. |
| Uploads | malware, parser exploits, zip bombs | Size and count limits; extension *and* magic-byte checks; server-generated filenames outside the code tree; optional ClamAV (`CLAMAV_HOST`); parsing in a separate subprocess with CPU, memory, file-size and wall-clock limits and an empty environment; DOCX zip-bomb ratio checks; retention purge (`UPLOAD_RETENTION_DAYS`). |
| Secrets | leakage | Env-only or AES-GCM-encrypted at rest; never returned to the browser; log redaction by key name *and* value pattern (`sk-…`, `AIza…`, JWTs, bearer tokens, `?key=`); error tracking scrubs request bodies, cookies and headers. |
| Billing | forged webhooks, replay, premature entitlement | HMAC signature with timestamp tolerance; idempotent by event ID; entitlements only from verified webhook or API reconciliation, never from a redirect. |
| Abuse and cost | runaway jobs, cost attacks | Per-user concurrency, daily job and monthly cost limits; per-job budgets for searches, sources, tool calls, tokens, cost and duration, all enforced in the worker. |

`CONTENT_SAFETY_ENABLED=0` disables only the optional question-safety classification. Authentication, authorization,
tenant isolation, SSRF protection, injection handling and upload controls cannot be disabled by any flag.

## Privacy

- Data stored: account, research questions, plans, retrieved source text, evidence, reports, uploads, usage, and audit
  events for sensitive actions.
- Data sent to third parties: questions, plan prompts and **excerpts** of retrieved or uploaded text go to the
  configured AI provider; search queries go to the configured search provider. Uploaded documents are sent to the AI
  provider only as the passages needed for a job, and only when the user attaches them to that job. The privacy page
  in the app lists this.
- No training on user data by this application. Check each provider's API data-use terms; the major providers do not
  train on API traffic by default, but verify this for your account and region.
- Users can delete individual research (cascades to sources, evidence, reports, events and exports), delete uploads,
  export all their data as JSON (`GET /api/v1/account/export`), and delete their account, which revokes sessions and
  removes their content.
- Retention: uploads purge after `UPLOAD_RETENTION_DAYS`; generated export files expire (TTL); sessions and tokens
  expire (TTL). Audit logs are retained for security review. Set your own retention policy before launch.

## Production security checklist

- [ ] `APP_ENV=production`. Startup refuses missing `AUTH_SECRET` (≥ 32 chars), `MONGODB_URI`, `REDIS_URL`, an https
      `FRONTEND_URL`, `ENCRYPTION_KEYS`, SMTP (when verification or reset is on) and Paddle secrets (when billing is on),
      and refuses `DEMO_MODE=1`.
- [ ] Generate `AUTH_SECRET` and `ENCRYPTION_KEYS` with a CSPRNG; store them in your platform's secret manager; plan rotation
      (add a new encryption key first, keep the old one for decryption).
- [ ] MongoDB Atlas: dedicated database user with `readWrite` on one database only; IP access list or private
      endpoint; TLS (default); backups enabled. Redis: TLS (`rediss://`), password or ACL, not internet-exposed,
      `maxmemory-policy noeviction`.
- [ ] If the API has a public URL (e.g. the free Render layout), set `INTERNAL_PROXY_TOKEN` (≥ 32 random chars) on API
      and web so the API only answers the web proxy.
- [ ] Serve web and API over HTTPS only. Put the API on a private network reachable from web (`API_INTERNAL_URL`) and
      expose only the web origin publicly, *or* restrict API CORS to the frontend origin (the default).
- [ ] Set `TRUSTED_PROXY_HOPS` to the real number of proxies in front of the API, so rate limits key on the client IP.
- [ ] Run the worker on a network that can reach the public internet but **not** your internal networks (egress
      firewall) — defence in depth on top of the SSRF guard. Block 169.254.169.254 at the network layer too.
- [ ] Google OAuth: register exactly `{FRONTEND_URL}/api/v1/auth/google/callback`.
- [ ] Enable `CLAMAV_HOST` if users will upload files from untrusted sources.
- [ ] Configure `ERROR_TRACKING_DSN`, and log shipping for JSON logs (they already redact secrets).
- [ ] Have counsel review the legal pages (`/terms`, `/privacy`). Both display a "template — review before launch" notice.
- [ ] Run `pip-audit` / `npm audit` (CI does) and keep base images patched.
- [ ] Create the first admin with `ADMIN_BOOTSTRAP_EMAILS` (applies only once that email is verified, by email link or
      Google) or `python -m app.cli create-admin EMAIL`, then remove the bootstrap variable.

## Reporting vulnerabilities

Add a `SECURITY.md` with your disclosure contact before launch.
