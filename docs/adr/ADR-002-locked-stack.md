# ADR-002: Locked Phase 1 technology stack

**Status:** Accepted  
**Date:** 2026-05 (working session)  

## Context

Stack choices were debated across brainstorm and contract. Drift risk is real if each module picks differently.

## Decision

Phase 1 stack is locked:

| Layer | Choice |
|---|---|
| Backend | Python 3.13+, `uv`, FastAPI, Pydantic v2, SQLAlchemy 2.x (async), Alembic |
| Database | PostgreSQL 16 (local Docker image `postgres:16-alpine` — do not pull other tags without owner approval) |
| Frontend | TypeScript, React 19, Vite 6, pnpm |
| PWA storage | IndexedDB (`apps/web/src/lib/localStore.ts`) |
| Containers | Docker Compose under `infra/` |
| CI | GitHub Actions (`.github/workflows/ci.yml`) |
| Logging | structlog, JSON in non-dev |
| Tests | pytest, pytest-asyncio, httpx ASGITransport, Hypothesis, Testcontainers (same Postgres image) |

## Consequences

- No pip, no npm, no Poetry, no Yarn.
- Dev Postgres is compose service `db` with `pull_policy: never`.
- Dockerfile for API uses `python:3.13.7-slim-bookworm` and `ghcr.io/astral-sh/uv:0.11.18` — both already present locally; do not introduce new base images without updating this ADR.
