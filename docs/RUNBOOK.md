# Elio — Operations runbook (dev / pilot)

## Start / stop

| Service | Start | Stop |
|---------|--------|------|
| Postgres | `docker compose -f infra/docker-compose.yml up -d db` | `docker compose -f infra/docker-compose.yml stop db` |
| API | `uv run uvicorn elio_api.main:app --host 127.0.0.1 --port 8000` from `apps/api` | Ctrl+C |
| Web | `pnpm dev --host 127.0.0.1 --port 5173` from `apps/web` | Ctrl+C |

**Do not** `docker compose pull` Postgres. Use the local `postgres:16-alpine` image only.

## JWT keys (first run)

```powershell
Set-Location apps\api
Copy-Item .env.example .env
uv run python scripts/gen_dev_keys.py
```

Restart API after generating keys. If login returns `LOGIN_NOT_CONFIGURED`, keys are missing or API started without `.env`.

## Data

| Action | Command |
|--------|---------|
| Migrate | `uv run alembic upgrade head` |
| New demo tenant | `uv run python scripts/seed_local_demo.py` |
| Add missing templates to existing tenants | `uv run python scripts/backfill_templates.py` |

Demo passwords (dev only): `SupervisorDev123!` / `WorkerDev123!`.

## Health checks

- API: `GET /api/v1/health/live` and `/api/v1/health/ready`
- Web: `http://127.0.0.1:5173`
- Login: `POST /api/v1/auth/login` with supervisor email/password

## Common failures

| Symptom | Fix |
|---------|-----|
| Compose tries to pull | Stop; confirm image exists: `docker images postgres` |
| Login 503 `LOGIN_NOT_CONFIGURED` | Run `gen_dev_keys.py`, restart API from `apps/api` |
| Web cannot reach API | API not on `:8000`; Vite proxies to `http://localhost:8000` |
| No marketing/collections templates | `backfill_templates.py` |
| Submit `EXECUTION_TOO_FAST` | Expected in prod settings; set `ELIO_MIN_EXECUTION_SECONDS=0` for local tests only |
| Submit `EXCEPTION_REQUIRED` | Worker must **Report blocked** before exception outcome |
| Photo `EVIDENCE_REUSED` | New photo required; same checksum on another job is rejected |

## Test commands

```powershell
# API
cd apps\api
uv run ruff check src tests
uv run mypy src
uv run pytest -q

# Browser E2E (API + web must be running)
cd apps\web
pnpm test:e2e
```

## What “green” means

- API: ruff + mypy clean; pytest suites pass (auth, isolation, state machine, templates, journeys, anti-abuse, ops offline, evidence, sync)
- Web: `pnpm typecheck` and `pnpm build`; Playwright 4/4

## Security notes (dev)

- `.env` is gitignored; never commit JWT private keys
- Password login is for pilot/dev; production must use OIDC and `ELIO_ALLOW_PASSWORD_LOGIN=false`
- Evidence is local disk under `var/evidence` (or `ELIO_EVIDENCE_ROOT`); not multi-host safe without a shared store
