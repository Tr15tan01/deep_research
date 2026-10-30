# Worker

Long-running research, section-regeneration and export jobs run here, never inside an HTTP request.

```bash
# local (after `make setup`)
cd apps/api && ENV_FILE=../../.env .venv/bin/python -m deep_research_worker
# container
docker compose -f infra/docker-compose.yml up worker
```

How it works (details in `docs/architecture.md#durable-execution`):

- **Delivery vs. truth** — Redis (`dr:queue:jobs`) only delivers job IDs. MongoDB `research_jobs` is the
  source of truth. Duplicate deliveries are harmless; lost deliveries are re-dispatched by the reconciler.
- **Leases** — a worker claims a job with an atomic `find_one_and_update` that sets `lease.{owner,token,expires_at}`.
  Heartbeats extend the lease every `WORKER_HEARTBEAT_SECONDS`. Every write is conditioned on the lease token.
- **Checkpoints** — the full LangGraph state is saved after every node and inside long nodes. A restarted or
  replacement worker resumes from `checkpoint.next`.
- **Recovery** — if a worker dies, its lease expires after `WORKER_LEASE_SECONDS`; the next claim picks the job up
  and emits a `recovery` event.
- **Retries** — transient failures back off exponentially with jitter (`MAX_JOB_ATTEMPTS`), then dead-letter to
  `dr:queue:dead` with a partial report preserved. Invalid credentials, quota and billing errors are never retried.
- **Shutdown** — `SIGTERM` stops claiming, waits up to 20 s for a checkpoint, then releases the lease.
- **Health** — `python -m deep_research_worker --healthcheck` checks that the reconcile loop touched
  `WORKER_HEALTH_FILE` recently.

The worker shares code with the API through the `app` package so job semantics can never drift between them.
