# Environment Variable Inventory

This inventory lists **every** environment variable currently referenced across PulseOps backend code, frontend build configuration, Alembic, Docker Compose, and GitHub Actions CI.

> [!CAUTION]
> Never commit `.env` or paste real credentials into documentation, prompts, or CI YAML files. Keep `.env.example` populated strictly with dummy placeholder values.

---

## 1. Active Environment Variables (Referenced in Code & Infrastructure)

| Exact Name | Purpose | Required? | Secret? | Scope | Platform | How to Generate / Obtain | Impact of Changing or Rotating |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `DATABASE_URL` | Primary PostgreSQL connection URL for SQLAlchemy & Alembic (`postgresql+psycopg://...`) | **Required** | **Yes** *(contains DB password)* | Local, CI, Production | Render, GitHub CI, Local `.env` | Neon dashboard (`?sslmode=require`) or local Docker creds | Changing switches target DB; wrong URL fails `/health` (503) and blocks all auth/org calls |
| `REDIS_URL` | Redis connection URL (`redis://...` local/CI, `rediss://...` production TLS) | **Required** *(by `Settings`)* | **Yes** *(contains Redis password in prod)* | Local, CI, Production | Render, GitHub CI, Local `.env` | Upstash TLS endpoint or local Docker `redis://redis:6379/0` | Required for ARQ workers, SSE Pub/Sub, rate limiting, Copilot response caching, and `/readiness` |
| `JWT_SECRET_KEY` | HS256 HMAC signing key for user access JWTs (`app.core.auth`) | **Required in Prod** *(runtime required for auth)* | **Yes** | Local, CI, Production | Render, GitHub CI (ephemeral), Local `.env` | `python -c "import secrets; print(secrets.token_hex(32))"` | **Immediately invalidates all active 1-hour JWTs**; logged-in users receive `401` and must re-authenticate |
| `INTEGRATION_ENCRYPTION_KEY` | Fernet symmetric key (AES-128-CBC + HMAC-SHA256) encrypting `integrations.credentials_encrypted` (`app.core.security`) | **Required in Prod** *(runtime required for integration crypto)* | **Yes** *(critical)* | Local, CI, Production | Render, GitHub CI (ephemeral), Local `.env` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` | **Swapping in place makes all existing encrypted integration credentials unreadable**; requires re-encryption runbook |
| `TEST_DATABASE_URL` | Dedicated isolated test PostgreSQL URL (`tests/conftest.py`); never falls back to `DATABASE_URL` | **Required for pytest** | **Yes** *(local/CI DB password)* | Local, CI **only** *(never Prod)* | GitHub CI, Local `.env` | Local `pulseops_test` DB or CI ephemeral `pulseops_test` DB | Changing switches test target; setting equal to `DATABASE_URL` aborts pytest with `RuntimeError` |
| `ENVIRONMENT` | Runtime environment (`development`, `test`, `production`) | Optional *(default: `development`)* | No | Local, CI, Production | Render (`production`), Local `.env` | Literal string (`production` on Render) | Setting `production` enforces strict startup checks (`validate_production_settings`) and disables OpenAPI docs by default |
| `LOG_LEVEL` | Application log threshold (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | Optional *(default: `INFO`)* | No | Local, CI, Production | Render, Local `.env` | Standard Python log level name | Controls structured JSON log volume emitted to stdout |
| `CORS_ORIGINS` | Comma-separated allowed browser origins (`https://pulseops.vercel.app`) | **Required once frontend exists** *(default: `""`)* | No | Local, Production | Render | Exact HTTPS frontend origin(s) without trailing slash | Missing or mismatched origin blocks Vercel browser requests via CORS; `*` is rejected in production |
| `ENABLE_DOCS` | Override OpenAPI `/docs`, `/redoc`, `/openapi.json` visibility (`true`/`false`) | Optional *(default: `false` in prod, `true` otherwise)* | No | Local, Production | Render (`false`), Local `.env` | Boolean string (`false` recommended in prod) | Setting `true` in production exposes interactive API documentation publicly |
| `PYTHON_VERSION` | Pins Python interpreter version on Render native runtime | Recommended on Render | No | Production | Render (`3.12.8`) | Literal `3.12.8` | Changing changes container Python runtime; keep aligned with Python `3.12` in CI and Dockerfile |
| `PORT` | HTTP listening port injected dynamically by Render | Injected by Render *(default fallback `8000` in Dockerfile)* | No | Production | Render (automatic) | Provided automatically by Render | Changing manually breaks Render port health binding unless start command reads `$PORT` |
| `POSTGRES_USER` | Local Docker PostgreSQL superuser (`docker-compose.yml`) | Local Docker only | No | Local Docker | Local `.env` | Dummy local username (`pulseops`) | Must match `DATABASE_URL` username locally; unused in Render/Neon |
| `POSTGRES_PASSWORD` | Local Docker PostgreSQL password (`docker-compose.yml`) | Local Docker only | **Yes** *(local)* | Local Docker | Local `.env` | Local password | Must match `DATABASE_URL` locally; changing after volume init does not update existing DB password |
| `POSTGRES_DB` | Local Docker PostgreSQL initial database (`docker-compose.yml`) | Local Docker only | No | Local Docker | Local `.env` | `pulseops` | Controls initial DB created on fresh Postgres volume; unused in Render/Neon |
| `API_PORT` | Host port mapping for local Docker API (`docker-compose.yml`) | Optional *(default: `8000`)* | No | Local Docker | Local `.env` | Port integer (`8000`) | Changes host localhost port for local container access |
| `POSTGRES_PORT` | Host port mapping for local Docker Postgres (`docker-compose.yml`) | Optional *(default: `5432`)* | No | Local Docker | Local `.env` | Port integer (`5432`) | Changes host localhost port for local Postgres access |
| `REDIS_PORT` | Host port mapping for local Docker Redis (`docker-compose.yml`) | Optional *(default: `6379`)* | No | Local Docker | Local `.env` | Port integer (`6379`) | Changes host localhost port for local Redis access |
| `GITHUB_TOKEN` | Built-in GitHub Actions token passed to `gitleaks/gitleaks-action@v2` | Auto-provided in GitHub Actions | **Yes** *(CI ephemeral)* | CI | GitHub Actions | `${{ secrets.GITHUB_TOKEN }}` (automatic) | Used by Gitleaks to inspect PR commit ranges |

---

## 2. Integration, AI, Rate Limiting, Demo & Frontend Variables (Implemented)

| Exact Name | Purpose | Platform | Secret? | Default / Notes |
| :--- | :--- | :--- | :--- | :--- |
| `VITE_API_URL` | Base URL of the Render FastAPI API for the React/Vite SPA (`frontend/src/lib/api.ts`) | Vercel (`frontend/`) | No *(public build-time)* | Must be non-localhost HTTPS URL in production builds |
| `RAZORPAY_MOCK_FALLBACK` | Enables conditional synthetic mock-billing mode (`true` / `false`) | Render, Local `.env` | No | Default `true`; live `rzp_live_*` keys are blocked in non-live modes |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` / `GITHUB_OAUTH_REDIRECT_URI` | GitHub OAuth app credentials for PR & issue cycle-time ingestion | Render, Local `.env` | **Yes** *(secret)* | Optional unless completing live GitHub OAuth exchange; per-org PATs are encrypted in `integrations.credentials_encrypted` |
| `DEEPSEEK_API_KEY` | DeepSeek LLM API credential for AI operational insights | Render, Local `.env` | **Yes** | Optional; deterministic local fallback applies automatically when unset |
| `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | DeepSeek API base URL and model name | Render, Local `.env` | No | Defaults: `https://api.deepseek.com`, `deepseek-chat` |
| `DEEPSEEK_MAX_TOKENS` / `DEEPSEEK_MAX_TOOL_ROUNDS` | Cost & recursion bounds for LLM calls (`app.ai`) | Render, Local `.env` | No | Defaults: `800` tokens, `3` tool rounds |
| `COPILOT_CACHE_TTL_SECONDS` | Redis TTL for cached read-only Copilot responses | Render, Local `.env` | No | Default `120` seconds (auto-invalidated on new event ingestion) |
| `RATE_LIMIT_ENABLED` / `RATE_LIMIT_WINDOW_SECONDS` | Master toggle and sliding/fixed window duration for Redis rate limiting | Render, Local `.env` | No | Defaults: `true`, `60` seconds |
| `RATE_LIMIT_AUTH_MAX_REQUESTS` / `RATE_LIMIT_COPILOT_MAX_REQUESTS` / `RATE_LIMIT_ORG_WRITE_MAX_REQUESTS` | Per-IP (`/auth/*`) and per-`org_id:user_id` (`/copilot/chat`, sync/CSV) quotas | Render, Local `.env` | No | Defaults: `20`, `20`, `60` requests per window (`429` + `Retry-After`) |
| `DEMO_ACCOUNT_EMAIL` / `DEMO_COPILOT_DAILY_LIMIT` | Synthetic read-only demo viewer email and daily Copilot cap | Render, Local `.env` | No | Defaults: `demo@pulseops.example.com`, `5` requests/day |

---

## 3. Audit Notes

1. **Exact Encryption Key Name Verified:** Code in [`backend/app/core/security.py`](../../backend/app/core/security.py) uses `INTEGRATION_ENCRYPTION_KEY` (singular `INTEGRATION`, matching `.env.example` and `.github/workflows/ci.yml`).
2. **Production Guards Active:** `ENVIRONMENT`, `LOG_LEVEL`, `CORS_ORIGINS`, and `ENABLE_DOCS` are wired into `backend/app/config.py`, `backend/app/main.py`, and `.env.example`.
3. **Zero-Downtime Key Rotation Backlog:** See [`secrets-and-encryption.md`](./secrets-and-encryption.md) and [`docs/security-backlog.md`](../security-backlog.md).
