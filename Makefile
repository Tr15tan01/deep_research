# Deep Research — common tasks. Run `make help`.
SHELL := /bin/bash
API := apps/api
WEB := apps/web
PY := $(API)/.venv/bin/python
ENV ?= .env

.PHONY: help setup env dev dev-api dev-worker dev-web demo up down logs test test-api test-web e2e eval lint typecheck contracts contracts-check build ci

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n",$$1,$$2}'

setup: ## Install Python (venv) and Node dependencies
	cd $(API) && (command -v uv >/dev/null && uv venv -q -p 3.13 .venv || python3.13 -m venv .venv)
	cd $(API) && (command -v uv >/dev/null && uv pip install --python .venv/bin/python -e '.[dev]' -e ../worker \
	  || .venv/bin/python -m pip install -e '.[dev]' -e ../worker)
	cd $(WEB) && npm ci
	cd $(WEB) && npx playwright install chromium || true

env: ## Create .env from .env.example (won't overwrite)
	@test -f .env && echo ".env exists — leaving it alone" || (cp .env.example .env && echo "created .env — fill in secrets")

dev-api: ## Run the API with reload (uses $(ENV))
	cd $(API) && ENV_FILE=../../$(ENV) .venv/bin/uvicorn app.main:app --reload --port 8000

dev-worker: ## Run a standalone worker (needs real MongoDB + Redis)
	cd $(API) && ENV_FILE=../../$(ENV) .venv/bin/python -m deep_research_worker

dev-web: ## Run Next.js in dev mode against the local API
	cd $(WEB) && API_INTERNAL_URL=http://localhost:8000 npm run dev

demo: ## Zero-dependency demo: in-memory DB and Redis, embedded worker, synthetic providers (no keys, no Docker)
	@printf 'APP_ENV=development\nMONGODB_URI=mongomock://\nDEMO_MODE=1\nAI_PROVIDER=demo\nSEARCH_PROVIDER=demo\nEMBEDDED_WORKER=1\nDEMO_STEP_DELAY_MS=700\nUPLOAD_DIR=/tmp/deep-research-uploads\nADMIN_BOOTSTRAP_EMAILS=admin@example.com\n' > .env.demo
	@echo "→ API on :8000, web on :3000. Register admin@example.com to get the admin console. Ctrl-C to stop."
	@trap 'kill 0' INT TERM; \
	  (cd $(API) && ENV_FILE=../../.env.demo .venv/bin/uvicorn app.main:app --port 8000) & \
	  (cd $(WEB) && API_INTERNAL_URL=http://localhost:8000 npm run dev) & wait

up: ## Start the full stack in Docker (MongoDB replica set, Redis, API, worker, web)
	docker compose -f infra/docker-compose.yml up --build -d
	@echo "→ http://localhost:3000"

down: ## Stop the Docker stack
	docker compose -f infra/docker-compose.yml down

logs: ## Follow Docker logs
	docker compose -f infra/docker-compose.yml logs -f --tail=100

test: test-api test-web ## Run backend and frontend unit/integration tests

test-api: ## Backend tests (pytest; Redis-dependent tests auto-skip without redis-server)
	cd $(API) && .venv/bin/python -m pytest -q

test-web: ## Frontend unit tests (Vitest)
	cd $(WEB) && npx vitest run

e2e: ## Playwright end-to-end tests (starts demo API + production web build)
	cd $(WEB) && npx playwright test

eval: ## Agent evaluation suite (deterministic metrics; LIVE=1 to run against configured providers)
	cd $(API) && .venv/bin/python ../../tests/eval/run_eval.py $(if $(LIVE),--live,)

lint: ## Ruff + ESLint
	cd $(API) && .venv/bin/ruff check app tests ../worker
	cd $(WEB) && npx eslint .

typecheck: ## mypy (advisory) + tsc
	cd $(API) && .venv/bin/mypy app || true
	cd $(WEB) && npx tsc --noEmit

contracts: ## Regenerate packages/shared (OpenAPI + enumerations)
	cd $(API) && ENV_FILE=/dev/null $(PY:$(API)/%=%) -m app.contracts

contracts-check: ## Fail if packages/shared is stale
	cd $(API) && ENV_FILE=/dev/null $(PY:$(API)/%=%) -m app.contracts --check

build: ## Production builds (web) and container images
	cd $(WEB) && npm run build
	docker build -f infra/docker/python.Dockerfile --target api -t deep-research-api .
	docker build -f infra/docker/python.Dockerfile --target worker -t deep-research-worker .
	docker build -f infra/docker/web.Dockerfile -t deep-research-web .

ci: lint contracts-check test ## What CI runs (minus e2e and image builds)
