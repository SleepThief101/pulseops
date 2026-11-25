# CI/CD Readiness and Production Audit Notes

This document summarizes the verification of `.github/workflows/ci.yml`, instructions for verifying the first remote GitHub Actions run, and deferred architectural items identified during the Phase 2 readiness audit.

---

## 1. GitHub Actions CI Audit (`.github/workflows/ci.yml`)

Verified line-by-line against requirements:

| Check | Status | Verified Implementation |
| :--- | :---: | :--- |
| Push & PR triggers | Verified | `"on": push: branches: [ main ], pull_request: branches: [ main ]` |
| PostgreSQL 16 service | Verified | `postgres:16` on `5432:5432` with `--health-cmd "pg_isready -U pulseops -d pulseops"` |
| Redis 7 service | Verified | `redis:7` on `6379:6379` with `--health-cmd "redis-cli ping"` |
| Full history checkout | Verified | `actions/checkout@v4` with `fetch-depth: 0` (required by Gitleaks) |
| Dedicated test DB isolation | Verified | Explicitly creates `pulseops_test`, runs `alembic upgrade head` on both `pulseops` and `pulseops_test`, sets `TEST_DATABASE_URL` separately from `DATABASE_URL` |
| No hardcoded secrets | Verified | `JWT_SECRET_KEY` and `INTEGRATION_ENCRYPTION_KEY` generated dynamically at runtime in the pytest step |
| Gitleaks & Ruff | Verified | Runs `gitleaks/gitleaks-action@v2` (`GITHUB_TOKEN`) and `ruff check .` |

> [!NOTE]
> **GitHub Organization Repositories:** If the repository is moved under a GitHub Organization (rather than a personal account), `gitleaks/gitleaks-action@v2` requires a `GITLEAKS_LICENSE` repository/org secret. For personal repositories (`SleepThief101/pulseops`), `GITHUB_TOKEN` works directly.

---

## 2. Verifying the First Remote GitHub Actions Run

Once you explicitly approve pushing local commits to GitHub:

1. Push `main` (or open a pull request targeting `main`):
   ```bash
   git push origin main
   ```
2. Open `https://github.com/SleepThief101/pulseops/actions`.
3. Select the **CI** workflow run triggered by your commit.
4. Expand the **`Lint, Scan, and Test`** job and confirm every step succeeds:
   - `Initialize containers`: Postgres 16 and Redis 7 pass health checks.
   - `Run Gitleaks secret scanning`: Exits `0` with no leaks detected.
   - `Run Ruff checks`: Exits `0` (`All checks passed!`).
   - `Run database migrations`: Applies migrations cleanly up to head (`849f79e737c6`) on both `pulseops` and `pulseops_test`.
   - `Run pytest suite`: Reports all tests passing (`122 passed` including production config tests) against `TEST_DATABASE_URL`.
5. Confirm the CI badge on `README.md` turns green (**passing**).

---

## 3. Production Improvements Implemented vs. Deferred Architectural Items

### Implemented Safe Improvements

- **Psycopg 3 URL Normalization (`backend/app/config.py`, `db/session.py`, `alembic/env.py`):** Automatically converts `postgres://` and `postgresql://` schemes to `postgresql+psycopg://` so Neon/Render connection strings work out-of-the-box without needing `psycopg2`.
- **Neon-Friendly Pool Tuning (`backend/app/db/session.py`):** Added `pool_recycle=300`, `pool_size=5`, `max_overflow=10` alongside `pool_pre_ping=True`.
- **CORS Support (`backend/app/main.py`, `backend/app/config.py`):** Configured `CORSMiddleware` from `CORS_ORIGINS` (default empty = fail-closed cross-origin; rejects `*` in production) and exposes `X-Request-ID`.
- **Production Startup Validation & Graceful Shutdown (`backend/app/main.py`):** Added FastAPI `lifespan` calling `settings.validate_production_settings()` when `ENVIRONMENT=production` (verifying `JWT_SECRET_KEY >= 32` chars, valid `INTEGRATION_ENCRYPTION_KEY`, key separation, and non-wildcard `CORS_ORIGINS`), warning on non-TLS remote DB/Redis URLs, and running `engine.dispose()` on shutdown.
- **API Docs Protection (`backend/app/main.py`):** Automatically disables `/docs`, `/redoc`, and `/openapi.json` when `ENVIRONMENT=production` unless overridden via `ENABLE_DOCS=true`.
- **Production Dockerfile & Render Blueprint (`backend/Dockerfile`, `docker-compose.yml`, `render.yaml`):** Removed `--reload` from production `Dockerfile`, added `alembic.ini` & `alembic/` to the image, bound `${PORT:-8000}` with `--proxy-headers --forwarded-allow-ips=*`, preserved `--reload` in `docker-compose.yml`, and added `render.yaml`.

- **Implemented Stack Coverage:** `.github/workflows/ci.yml` validates both the Python backend (`Gitleaks`, `Ruff`, Alembic migrations on `pulseops` and `pulseops_test`, full `pytest` suite) and the React/Vite/TypeScript frontend (`npm test`, `npm run build`).
- **Monitoring & Readiness:** `/health`, `/readiness` (PostgreSQL + Redis), and `/metrics` (Prometheus exposition) are active in [`backend/app/main.py`](../../backend/app/main.py).
- **Deferred Security Hardening Items:** Tracked in [`docs/security-backlog.md`](../security-backlog.md) (S32 MCP per-user hashed API keys + network transport auth, Copilot tool argument schema validation, viewer proposal restriction, and webhook replay window).
- **Zero-Downtime Key Rotation (`MultiFernet`):** `backend/app/core/security.py` uses single-key `Fernet`; upgrade to `MultiFernet` before performing zero-downtime key rotations in production.
