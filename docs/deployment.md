# Deployment

Three processes, two managed services:

```
            ┌──────────── public ────────────┐   ┌──────────── private network ─────────────┐
 browser ─▶ │ web  (Next.js standalone, :3000)│──▶│ api  (uvicorn, :8000)   worker × N        │
            └─────────────────────────────────┘   │        │   │                │  │         │
                                                  │        ▼   ▼                ▼  ▼         │
                                                  │   MongoDB Atlas          Redis (TLS)     │
                                                  └───────────────────────────────────────────┘
                                                     worker egress → AI / search APIs, public web
```

The web tier can run on any Node host, including Vercel. **The API and worker must run on a container platform
that supports long-lived processes** (Fly.io, Render, Railway, Google Cloud Run with min-instances for the API plus a
worker service, AWS ECS/Fargate, Azure Container Apps, Kubernetes). Do not try to run the worker in serverless functions.

## 1. MongoDB Atlas

1. Create a cluster (M10+ recommended for production; M0/M2 work for trials but have operation limits).
2. **Database Access** → add a user with `readWrite` on a single database (e.g. `deep_research`).
3. **Network Access** → add your API and worker egress IPs, or use a private endpoint or VPC peering.
4. Copy the SRV string → `MONGODB_URI=mongodb+srv://USER:PASS@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority`
   and `MONGODB_DATABASE=deep_research`.
5. Indexes, TTL indexes and `$jsonSchema` validators are created idempotently at API and worker startup. To run them
   ahead of a deploy: `python -m app.cli init-db`.
6. Enable **Cloud Backup** (continuous or snapshot) and test a restore (see [Backup and restore](#backup-and-restore)).

The application does not rely on multi-document transactions for correctness. Job ownership uses single-document atomic
updates (leases), so Atlas tiers and replica-set topologies are all fine.

## 2. Redis

Any Redis 6.2+ (Upstash, Redis Cloud, ElastiCache, Memorystore). Use `rediss://` (TLS) with auth. Set
`maxmemory-policy noeviction`: the queue list must not be evicted (the reconciler would recover it, but with a delay).
Redis holds no durable state; losing it delays queued jobs until the reconciler re-dispatches them from Mongo.

## 3. Images

```bash
docker build -f infra/docker/python.Dockerfile --target api    -t REGISTRY/deep-research-api:VERSION .
docker build -f infra/docker/python.Dockerfile --target worker -t REGISTRY/deep-research-worker:VERSION .
docker build -f infra/docker/web.Dockerfile                     -t REGISTRY/deep-research-web:VERSION .
```

All images run as non-root and include health checks. The API and worker share the engine code. Deploy them from the
**same commit**.

## 4. Configuration

Use your platform's secret store for every secret in `.env.example`. Minimum production set:

| Service | Variables |
| --- | --- |
| api + worker | `APP_ENV=production`, `FRONTEND_URL=https://…`, `MONGODB_URI`, `MONGODB_DATABASE`, `REDIS_URL`, `AUTH_SECRET`, `ENCRYPTION_KEYS`, `AI_PROVIDER`, `AI_MODEL`, one AI key, `SEARCH_PROVIDER`, one search key, `SMTP_*` + `EMAIL_FROM` (if verification or reset is on), `TRUSTED_PROXY_HOPS` |
| worker only | `WORKER_CONCURRENCY` (start with 2–4 per vCPU; jobs are I/O-bound) |
| web | `API_INTERNAL_URL=https://api.internal…` (server-side only; never exposed to browsers) |

Startup fails fast on an invalid production configuration (`core/config.py`). That is intentional.

Serve the web app and the API callback under the same site. The browser only ever talks to the web origin, so cookies
are first-party. If you use the Google callback, register `https://YOUR_WEB_ORIGIN/api/v1/auth/google/callback`.

## 5. Platform recipes

**Fly.io**: one app per process (`deep-research-web`, `-api`, `-worker`). API `[http_service]` on 8000 with
`/health/ready` checks. The worker has no services. Set `kill_timeout = 40` on the worker so SIGTERM can checkpoint.
Give the API a private address and use `API_INTERNAL_URL=http://deep-research-api.internal:8000` from web.

**Render**: [`render.yaml`](../render.yaml) runs everything on free instances (worker embedded in the API, which is
locked to the web proxy by `INTERNAL_PROXY_TOKEN`); [`render.standard.yaml`](../render.standard.yaml) is the paid layout
with a private API and a separate worker. Native runtimes, no Docker. Full guide: [deploy-render.md](deploy-render.md).

**Railway**: web service (web image), private service (api image), worker service (worker image). Health check path
`/health/ready` for the API.

**Google Cloud Run**: web and api as services (API with `--min-instances=1` and a request timeout ≥ 3600 s for SSE).
Run the worker as a separate service with `--no-cpu-throttling --min-instances=1`, or on GKE or Compute Engine.
Use Serverless VPC Access or Private Service Connect for Atlas and Memorystore.

**Kubernetes**: Deployments for all three; the worker with `terminationGracePeriodSeconds: 45`; readiness
`/health/ready`, liveness `/health/live` (api) and `python -m deep_research_worker --healthcheck` (worker); an
egress NetworkPolicy denying cluster-internal and metadata ranges from worker pods.

## 6. Rolling deploys and shutdown

- **API**: uvicorn drains with `--timeout-graceful-shutdown 20`. SSE clients reconnect automatically with
  `Last-Event-ID` and miss nothing.
- **Worker**: on SIGTERM it stops claiming, lets in-flight steps reach a checkpoint (up to 20 s), releases leases and
  re-enqueues. Another worker resumes from the checkpoint. If a worker is SIGKILLed, its lease expires after
  `WORKER_LEASE_SECONDS` and the job is recovered the same way.
- Backwards-compatible changes only between adjacent versions (old workers may briefly coexist with new APIs).
  Checkpoints are validated with Pydantic, so add new state fields with defaults.

## 7. Health endpoints

| Path | Auth | Purpose |
| --- | --- | --- |
| `GET /health/live` | none | process is up (liveness) |
| `GET /health/ready` | none | Mongo and Redis reachable (readiness); returns booleans only |
| `GET /health/dependencies`, `GET /api/v1/admin/dependencies` | admin | AI, search, SMTP, Google configuration status, without secrets or hostnames |
| `GET /api/v1/admin/system-health` | admin | workers, queue depth, expired leases, flags, config warnings |

## Backup and restore

- **Atlas**: enable Cloud Backup. Restore to a *new* cluster, point a staging stack at it, verify, then switch
  `MONGODB_URI`. For point-in-time recovery, enable continuous backup.
- **Self-managed**: `mongodump --uri "$MONGODB_URI" --db deep_research --gzip --archive=backup.gz`, then restore with
  `mongorestore --uri … --gzip --archive=backup.gz --nsInclude 'deep_research.*'`. Run `python -m app.cli init-db`
  after restoring to recreate any missing indexes.
- **Uploads**: the upload volume (`UPLOAD_DIR`) holds the original files. Back it up with your volume snapshots, or treat
  uploads as transient (parsed text lives in Mongo `upload_chunks`, and originals purge after `UPLOAD_RETENTION_DAYS`).
- **Redis**: no backup needed.
- **After a restore**: start the workers and run `python -m app.cli reconcile` to re-dispatch runnable jobs. Jobs that
  were mid-run resume from their last checkpoint once their (restored) leases expire.

## Local stack

`make up` (Docker Compose: MongoDB 8 single-node replica set, Redis 7, api, worker, web) or `make demo`
(no Docker: in-memory DB, embedded worker, synthetic providers). See the [README](../README.md).
