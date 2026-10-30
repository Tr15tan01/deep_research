# Operations runbook

## Observability

- **Logs** are structured (JSON in production) with `correlation_id` on every line. The API returns it as
  `X-Request-ID`, and every error body includes it as `reference_id`, so a user's "error reference" finds the exact log
  lines. Secrets are redacted by key and by value pattern before logging.
- **Error tracking**: set `ERROR_TRACKING_DSN` and install the extra (`pip install 'deep-research-api[tracking]'`).
  Unhandled API errors and unexpected worker failures are reported with their reference or job ID.
- **Admin console** (`/admin`): users, provider health (last real call, latency, normalized error), usage and estimated
  cost per user and model, jobs (filter by status, retry, cancel, reconcile), system health (workers, queue depth,
  expired leases, config warnings), audit log.

Suggested alerts:

| Signal | Source | Threshold |
| --- | --- | --- |
| API not ready | `/health/ready` | 2 consecutive failures |
| No live workers | `/api/v1/admin/system-health` `.workers` empty | > 2 min |
| Queue depth growing | `queue_depth` | > 5 × total worker concurrency for 10 min |
| Expired leases | `jobs_with_expired_leases` | > 0 for 5 min (workers dying) |
| Dead letters | Redis `LLEN dr:queue:dead`, jobs with `dead_lettered: true` | any new |
| Provider errors | provider health `last_error` of `invalid_credentials`/`quota_exhausted`/`billing_exhausted` | any |
| Unusual spend | `/admin/usage` per-user estimated cost | > 3× trailing 7-day mean |

## Common procedures

**A provider key expired or ran out of credit.** Jobs fail as *resumable* with an actionable message (no retry
storm). Fix the key or quota in **Admin → AI providers** (or the env var plus a restart), press **Test connection**,
then users (or admins under **Admin → Jobs**) press **Resume**. The job continues from its checkpoint.

**Search provider outage.** With `SEARCH_FALLBACK_ENABLED=1` and a second provider configured, jobs switch
automatically and record which provider produced each result. Otherwise jobs back off and retry; partial state is
kept.

**Jobs stuck in `queued`.** Check that workers are running (system health). Then `python -m app.cli reconcile` (or
**Admin → Jobs → Reconcile**) re-pushes runnable jobs from Mongo to Redis. Duplicates are harmless.

**Worker crashed mid-job.** Nothing to do: the lease expires after `WORKER_LEASE_SECONDS`, another worker claims the
job and resumes from its checkpoint (a `recovery` event is visible in the run's activity log).

**Dead-lettered jobs.** Inspect `last_error` and `error_history` on the job. After fixing the cause, **Admin → Jobs →
Retry** resets attempts and re-dispatches. The partial report remains available meanwhile.

**Redis down.** New research is refused with `queue_unavailable` (nothing is falsely accepted). Running jobs keep
working against Mongo, and SSE degrades to polling. When Redis returns, the reconciler re-dispatches.

**Mongo down.** Readiness fails; the API returns `503` with a reference ID and never claims a save that didn't
happen. Workers back off. Leases and checkpoints guarantee no double execution after recovery.

**Rotate `ENCRYPTION_KEYS`.** Prepend the new key (`NEW,OLD`), deploy, re-save stored provider keys in the admin UI (or
leave them: old ones still decrypt), and remove `OLD` once nothing uses it.

**Rotate `AUTH_SECRET`.** It signs access tokens and keys the hashes of stored refresh, reset and verification tokens,
so rotating it signs everyone out and voids outstanding email links. Rotate in a low-traffic window, or after a
suspected compromise (when signing everyone out is exactly what you want).

**Revoke a user.** **Admin → Users → Disable** revokes all sessions immediately.

## Capacity notes

Research is I/O-bound (LLM and search latency). One worker slot runs one job. Deep runs take minutes. Start with
`WORKER_CONCURRENCY=4` on a 1 vCPU / 1 GB worker and scale workers horizontally. Each API instance holds one Redis pub/sub
connection per open SSE stream.

## Maintenance CLI

```bash
python -m app.cli init-db             # indexes, TTLs, validators
python -m app.cli create-admin EMAIL  # promote an existing account
python -m app.cli reconcile           # re-dispatch runnable jobs
python -m app.cli purge-uploads       # delete uploads past retention (also runs hourly in the API)
python -m app.contracts --check       # shared contract drift check
```
