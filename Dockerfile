# syntax=docker/dockerfile:1.7
# NOTE: prod runs fb-worker as a HOST systemd service (see PLAN.md §8, deploy.sh),
# not via compose. This Dockerfile exists for parity/local-dev and the mcp target.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Build deps for cryptography + asyncpg + psycopg.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic

RUN pip install --no-cache-dir -e .

# ─── worker target (the only prod process) ───────────────────────
FROM base AS worker
CMD ["python", "-m", "meta_ads.worker.main"]

# ─── mcp target (usually run locally from .venv, not a container) ─
FROM base AS mcp
CMD ["python", "-m", "meta_ads.mcp"]
