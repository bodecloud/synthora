---
title: Compose smoke failed without asyncpg and bloated build context
date: 2026-07-17
problem_type: runtime-error
component: synthora
tags: [docker, compose, asyncpg, dockerignore, smoke]
---

# Compose smoke: missing asyncpg + huge build context

## Symptoms

`scripts/smoke.sh` failed with `ModuleNotFoundError: No module named 'asyncpg'`
in the API/worker containers. An earlier attempt also transferred a multi‑MB
build context (`.venv` / `node_modules` included).

## Root cause

1. `asyncpg` was only an *optional* extra on `synthora-persistence`, so
   `uv sync --frozen --no-dev` in Docker did not install it while
   `SYNTHORA_DATABASE_URL` used `postgresql+asyncpg://`.
2. No `.dockerignore`, so local `.venv` and `node_modules` were sent to the
   builder.

## Fix

- Make `asyncpg` and `aiosqlite` hard dependencies of `synthora-persistence`.
- Add `synthora/.dockerignore` excluding `.venv`, `node_modules`, caches.
- Prefer a slim context (~310KB) and re-run `scripts/smoke.sh`.

## Follow-up (2026-07-17): Postgres checkpointer needs psycopg-binary

With `SYNTHORA_CHECKPOINT_BACKEND=postgres`, smoke failed importing
`langgraph.checkpoint.postgres` inside the worker:

`ImportError: no pq wrapper available` / `libpq library not found`.

Slim bookworm images have no system `libpq`, and `langgraph-checkpoint-postgres`
only pulls pure `psycopg` (no binary extra). Fix: add
`psycopg[binary]>=3.2` to `synthora-orchestration` so the wheel bundles libpq.

Smoke now also runs a minimal `PostgresSaver.setup()` and asserts checkpoint
tables exist.

## Verification

`SYNTHORA_CHECKPOINT_BACKEND=postgres bash scripts/smoke.sh` → health/ready/
pipelines + web + postgres checkpointer tables.
