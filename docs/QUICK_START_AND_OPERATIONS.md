# PulseOps — Quick Start and Operations Guide

> **Audience:** Maintainers already holding the repository (`v1.2`/`v1.3` state, Alembic head `9c4a12e8f3b1`) on **Windows 11 (PowerShell)**.  
> For full architectural explanations, see [Complete Product Documentation](./PRODUCT_DOCUMENTATION.md). For risk status, see [Production Readiness Audit](./PRODUCTION_READINESS_AUDIT.md).

---

## Table of Contents

- [1. Local Startup (Docker Stack + Local Frontend)](#1-local-startup-docker-stack--local-frontend)
- [2. Backend Startup (Host Python `.venv`)](#2-backend-startup-host-python-venv)
- [3. Frontend Startup & Production Build](#3-frontend-startup--production-build)
- [4. Running Tests & Linters](#4-running-tests--linters)
- [5. Running Database Migrations (Alembic)](#5-running-database-migrations-alembic)
- [6. Git Status, Hygiene & Pushing Changes](#6-git-status-hygiene--pushing-changes)
- [7. Checking Health, Readiness & Logs](#7-checking-health-readiness--logs)
- [8. Verifying Integrations & Copilot](#8-verifying-integrations--copilot)
- [9. Common Troubleshooting Commands](#9-common-troubleshooting-commands)

---

## 1. Local Startup (Docker Stack + Local Frontend)

Run from repository root (`C:\Users\Rudransh\Documents\pulseops`):

```powershell
# 1. Start PostgreSQL 16, Redis 7, FastAPI API (8000), and ARQ Worker
docker compose up -d --build

# 2. Apply latest Alembic migrations (9c4a12e8f3b1)
docker exec pulseops-api alembic upgrade head
docker exec pulseops-api alembic current

# 3. Verify API & worker health
Invoke-RestMethod http://127.0.0.1:8000/readiness
docker exec pulseops-worker arq app.worker.WorkerSettings --check
```

Optional first-time test database initialization + synthetic local demo seed:

```powershell
# Create pulseops_test once
docker exec pulseops-db psql -U pulseops -d pulseops -c "CREATE DATABASE pulseops_test;"
docker exec pulseops-api sh -c 'DATABASE_URL="$TEST_DATABASE_URL" alembic upgrade head'

# Seed local synthetic demo workspace (refuses pulseops_test & non-local DBs)
python scripts\seed_demo_data.py
```

---

## 2. Backend Startup (Host Python `.venv`)

Use when running Uvicorn/pytest directly on Windows against Docker Postgres & Redis:

```powershell
# Ensure db and redis containers are up from repo root
docker compose up -d db redis

# Start API from backend\ mapping Docker hostnames to 127.0.0.1
Set-Location C:\Users\Rudransh\Documents\pulseops\backend
.\.venv\Scripts\python.exe -c "import os, subprocess, sys; from app.config import settings; env=os.environ.copy(); env['DATABASE_URL']=settings.sqlalchemy_database_url.replace('@db:', '@127.0.0.1:'); env['REDIS_URL']='redis://127.0.0.1:6379/0'; sys.exit(subprocess.run([r'.\.venv\Scripts\uvicorn.exe', 'app.main:app', '--host', '127.0.0.1', '--port', '8000', '--reload'], env=env).returncode)"
```

Swagger UI is available locally at `http://127.0.0.1:8000/docs`.

---

## 3. Frontend Startup & Production Build

Run from `frontend\`:

```powershell
Set-Location C:\Users\Rudransh\Documents\pulseops\frontend

# Development server (http://localhost:5173)
npm run dev

# Typecheck + production Vite bundle (requires non-localhost VITE_API_URL for prod mode; default dev uses .env)
npm run build

# Local preview of dist/
npm run preview
```

---

## 4. Running Tests & Linters

```powershell
# Backend pytest inside Docker container
docker exec pulseops-api pytest -v

# Backend pytest from Windows host (.venv) with loopback Postgres + Redis
Set-Location C:\Users\Rudransh\Documents\pulseops\backend
.\.venv\Scripts\python.exe -c "import os, subprocess, sys; from app.config import settings; env=os.environ.copy(); env['DATABASE_URL']=settings.sqlalchemy_database_url.replace('@db:', '@127.0.0.1:'); env['REDIS_URL']='redis://127.0.0.1:6379/0'; sys.exit(subprocess.run([r'.\.venv\Scripts\pytest.exe', '-v'], env=env).returncode)"

# Frontend unit tests & security audit (from frontend\)
Set-Location C:\Users\Rudransh\Documents\pulseops\frontend
npm test
npm audit --omit=dev

# Python dependency integrity check (from backend\)
Set-Location C:\Users\Rudransh\Documents\pulseops\backend
.\.venv\Scripts\python.exe -m pip check

# Secret scan & Ruff lint (from repo root)
Set-Location C:\Users\Rudransh\Documents\pulseops
gitleaks detect --source . --no-banner
python -m ruff check .   # (Run inside CI or after installing ruff in .venv)
```

---

## 5. Running Database Migrations (Alembic)

> [!CAUTION]
> Always take a Neon Branch / backup snapshot before running migrations on production, and use Neon's **Direct** (non-pooled) connection string—never the `-pooler` URL.

```powershell
# Local Docker DB
docker exec pulseops-api alembic upgrade head
docker exec pulseops-api alembic current

# Local isolated test DB
docker exec pulseops-api sh -c 'DATABASE_URL="$TEST_DATABASE_URL" alembic upgrade head'

# Host Windows CLI (set DATABASE_URL BEFORE starting alembic.exe)
Set-Location C:\Users\Rudransh\Documents\pulseops\backend
$env:DATABASE_URL = "postgresql+psycopg://<user>:<pass>@127.0.0.1:5432/pulseops"
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe current   # Expected: 9c4a12e8f3b1 (head)
```

---

## 6. Git Status, Hygiene & Pushing Changes

```powershell
Set-Location C:\Users\Rudransh\Documents\pulseops

# Inspect working tree & trailing whitespace
git status -s
git diff --stat
git diff --check

# Stage explicit files (never stage .env or unrelated untracked files)
git add <file1> <file2>
git diff --cached --check
git commit -m "chore(scope): concise description"

# Push only after explicit approval & green checks
git push origin main
```

---

## 7. Checking Health, Readiness & Logs

```powershell
# Local API checks
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/readiness
Invoke-WebRequest http://127.0.0.1:8000/metrics | Select-Object StatusCode

# Production read-only smoke test (from repo root)
python scripts\smoke_test.py --base-url https://pulseops-api-8cp9.onrender.com

# Local Docker logs (single-line JSON)
docker logs pulseops-api --tail 100
docker logs pulseops-worker --tail 100
```

- **Production Logs:** View Render Web Service logs in **Render Dashboard -> `pulseops-api` -> Logs** (filter by `request_id` returned in `X-Request-ID` header or `ApiError` toast). View Vercel edge/build logs in **Vercel Dashboard -> `pulseops` -> Logs / Deployments**.

---

## 8. Verifying Integrations & Copilot

- **Razorpay / GitHub Connector Check:** In **Integrations & CSV**, verify connected row status is `active`, click **Sync Now**, and confirm **Recent Sync Runs** shows `completed` with `inserted`/`skipped` counts (never enter `rzp_live_*` keys).
- **CSV Import Check:** In **Integrations & CSV**, click **Import CSV Events** using the prefilled sample containing `amount_minor` + `currency` -> confirm `1 inserted` (and `1 skipped` on re-click for SHA-256 idempotency).
- **DeepSeek vs. Fallback Check:** Ask Copilot `"Summarize our MRR, churn, and open issues"`. Bubble metadata renders `· deepseek-chat` when `DEEPSEEK_API_KEY` is active on backend, or `· deterministic-fallback` otherwise.
- **MCP `stdio` Check:** Create a `pmcp_` key via `POST /me/api-keys` (Bearer JWT required), set `$env:PULSEOPS_MCP_API_KEY = "pmcp_..."`, and start `.\.venv\Scripts\python.exe -m app.mcp_server` inside `backend\`.

---

## 9. Common Troubleshooting Commands

```powershell
# Inspect database tables and Alembic revision inside Docker Postgres
docker exec pulseops-db psql -U pulseops -d pulseops -c "\dt"
docker exec pulseops-db psql -U pulseops -d pulseops -c "SELECT * FROM alembic_version;"

# Check Redis connectivity & clear stale local rate-limit / copilot cache keys
docker exec pulseops-redis redis-cli PING
docker exec pulseops-redis redis-cli KEYS "pulseops:*"

# Restart unresponsive local containers
docker compose restart api worker

# Reset local demo owner password interactively (refuses production always)
python scripts\reset_demo_owner_password.py
```
