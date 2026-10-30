# syntax=docker/dockerfile:1.7
# One image, two targets — the API and the worker run identical engine code.
#   docker build -f infra/docker/python.Dockerfile --target api    -t deep-research-api .
#   docker build -f infra/docker/python.Dockerfile --target worker -t deep-research-worker .
# Build context: repository root.

ARG PYTHON_VERSION=3.13

FROM python:${PYTHON_VERSION}-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/api/app apps/api/app
COPY apps/worker apps/worker
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install ./apps/api ./apps/worker \
 && /opt/venv/bin/python -c "import app.main, deep_research_worker"

FROM python:${PYTHON_VERSION}-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/opt/venv/bin:$PATH \
    APP_ENV=production UPLOAD_DIR=/var/lib/deep-research/uploads WORKER_HEALTH_FILE=/tmp/worker.alive
RUN groupadd --system app && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app \
 && mkdir -p /var/lib/deep-research/uploads /app && chown -R app:app /var/lib/deep-research /app
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
USER app
# Uploads live outside the code tree on a non-executable volume.
VOLUME ["/var/lib/deep-research/uploads"]

FROM runtime AS api
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=4s --start-period=20s --retries=3 \
  CMD python -c "import sys,urllib.request as u; sys.exit(0 if u.urlopen('http://127.0.0.1:8000/health/live', timeout=3).status == 200 else 1)"
# --timeout-graceful-shutdown lets open SSE streams close cleanly during rolling deploys.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", \
     "--forwarded-allow-ips", "*", "--timeout-graceful-shutdown", "20", "--no-server-header"]

FROM runtime AS worker
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -m deep_research_worker --healthcheck
# SIGTERM → stop claiming, checkpoint, release leases. Give it time before SIGKILL (stop_grace_period).
STOPSIGNAL SIGTERM
CMD ["python", "-m", "deep_research_worker"]
