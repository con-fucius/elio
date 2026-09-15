# Elio — Field-work execution platform

**Baseline release (development).** Modular monolith for supervised field work: assignment, checklist execution, evidence, review, offline queue, and anti-abuse controls for hospital, marketing, and collections workflows.

**Status:** Development baseline — not production. OIDC IdP, multi-host evidence store, and live DPIA/ODPC work are out of scope until partners and legal gates clear.

---

## Architecture (locked)

| Layer | Choice |
|--------|--------|
| Backend | Python 3.13, FastAPI, SQLAlchemy 2 async, Alembic, Postgres |
| Frontend | React 19, Vite, TypeScript, PWA (IndexedDB + service worker), Figtree |
| Auth | RS256 JWT verify; local password login for pilot/dev only |
| Evidence | Content-addressed local disk (SHA-256); S3 later behind same interface |
| Sync | Command batch + change-feed cursor; idempotency keys |

Authority stack: `docs/canonical_baseline.md` → ADRs → state machines / glossary → contract (reference only).

---

## Quick start

### Prerequisites

- Docker (local image **only**: `postgres:16-alpine` — do not pull other Postgres tags)
- `uv`, Node 24+, `pnpm`
- Chromium for Playwright (once: `pnpm exec playwright install chromium`)

### 1. Database

```powershell
Set-Location D:\Projects\Elio\infra
docker compose up -d db
```

Expected: `infra-db-1` **Up (healthy)**. Image is local; `pull_policy: never`.

### 2. Backend

```powershell
Set-Location D:\Projects\Elio\apps\api

# First time only: copy env template and generate JWT keys
Copy-Item .env.example .env
uv run python scripts/gen_dev_keys.py   # writes ELIO_JWT_* into .env

uv run alembic upgrade head
uv run python scripts/seed_local_demo.py   # optional: new tenant + demo users + templates
uv run uvicorn elio_api.main:app --host 127.0.0.1 --port 8000
```

Smoke: `Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/live`

### 3. Frontend

```powershell
Set-Location D:\Projects\Elio\apps\web
pnpm install
pnpm dev --host 127.0.0.1 --port 5173
```

Open: **http://127.0.0.1:5173**

### Demo accounts (after seed / provision)

| Role | Email | Password |
|------|--------|----------|
| Supervisor | `supervisor@alpha-hospital.test` | `SupervisorDev123!` |
| Field worker | `worker@alpha-hospital.test` | `WorkerDev123!` |

Templates on a new/backfilled tenant: facility inspection, equipment service, outlet visit, collection contact.

```powershell
# Backfill marketing/collections templates on existing tenants
uv run python scripts/backfill_templates.py
```

### Stop

Ctrl+C on API and web, then:

```powershell
Set-Location D:\Projects\Elio\infra
docker compose stop db
```

---

## User journeys (reality-tested)

### Field worker (hospital etc.)

1. Sign in → **My work** (only your assignments)
2. **Refresh** pulls server work + checklist into the device
3. **Accept job** → **Start work**
4. Step through checklist (fields, notes) → **Add photo** on steps that require it
5. **Submit** only when required steps are done (or report **I cannot continue** first)
6. Offline: work stays on device; **Send** when online

### Supervisor / ops

1. Sign in → create work from template → **Send pending** / **Refresh**
2. **Operations** → assign, review, unblock, cancel
3. Blocked jobs show exception category + detail
4. Ops decisions use the same durable command queue when offline

### Anti-abuse (server-enforced)

| Pattern | Control |
|---------|---------|
| Jump to “unable to access” without reporting | Must `RaiseException` first |
| Same photo reused on another job (72h) | Reject `EVIDENCE_REUSED` |
| Tiny “photo” | Min size (`ELIO_MIN_EVIDENCE_BYTES`) |
| Instant complete after start | Min duration (`ELIO_MIN_EXECUTION_SECONDS`, 0 in tests) |

Env knobs: `ELIO_MIN_EXECUTION_SECONDS`, `ELIO_MIN_EVIDENCE_BYTES`, `ELIO_EVIDENCE_REUSE_WINDOW_HOURS`.

---

## Tests

### API (pytest)

```powershell
Set-Location D:\Projects\Elio\apps\api
uv run ruff check src tests
uv run mypy src
uv run pytest -q
```

### Browser (Playwright) — stack must be running

```powershell
Set-Location D:\Projects\Elio\apps\web
pnpm test:e2e
```

Covers: bad login, supervisor→assign→worker accept/start, exception block path, sign-out.

---

## Configuration

- **`.env.example`** — settings template, **no secrets** (commit-safe)
- **`.env`** — local secrets (gitignored). Generate keys: `uv run python scripts/gen_dev_keys.py`
- Never commit `.env` or private keys

---

## Repository layout

```
apps/api     FastAPI backend, Alembic, tests
apps/web     React PWA, Playwright e2e
infra/       docker-compose (Postgres)
docs/        baseline, ADRs, glossary, state machines, field reality notes
docs/history/  superseded brainstorm / contract (do not implement from)
```

Superseded planning material is under `docs/history/`. Use `docs/canonical_baseline.md` and ADRs as authority.

---

## Discoveries (why the system is shaped this way)

1. **Work card is a view, not the domain.** Real objects: WorkItem → Assignment → Authority → Tasks/Execution → Evidence → Outcome → Review.
2. **Command/event sync, not CRUD merge.** Offline clients must not invent authority; idempotency + conflict classes prevent double effects.
3. **PWA over native** for Phase 1: background sync is not guaranteed; protocol must be correct without it.
4. **Hospital first as modeling vehicle** (not commercial ranking): denser privacy/authority constraints expose model gaps early.
5. **Exception outcomes without a report are a fraud loophole** — closed: must raise exception before UNABLE_TO_ACCESS-style submit.
6. **Photo reuse and too-fast completion** are common field cheats — server rejects them.
7. **Supervisors can clear blocks** (not only the assignee); otherwise ops is stuck when the worker is blocked.
8. **Role decides UI:** field workers get guided “My work”; supervisors get create + operations. Same backend.
9. **Local evidence disk** is intentional (no AWS budget); domain model is storage-agnostic for a later S3/R2 adapter.
10. **Password login is pilot/dev only.** Production: OIDC IdP + `ELIO_ALLOW_PASSWORD_LOGIN=false`; demo users remain tenant actors, not a replacement for IdP.

---

## Explicitly out of scope (for now)

- Real OIDC IdP / Keycloak  
- AWS S3 / multi-host evidence store  
- Native Android  
- GPS anti-spoof / continuous tracking  
- Live DPIA and ODPC production filing  
- Commercial packaging / multi-country  

See `docs/adr/` and `docs/canonical_baseline.md` for decision records.
