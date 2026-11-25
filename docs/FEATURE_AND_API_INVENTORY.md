# PulseOps — Feature and API Inventory

> **Purpose:** Complete structured technical map of implemented modules, routes, models, background jobs, AI tools, connectors, environment variables, migrations, and tests verified directly against repository source files (`v1.2` Meridian UI + `v1.3` Monetary Integrity state; production Neon verified at Alembic head `9c4a12e8f3b1`).

---

## Table of Contents

- [1. Frontend Pages & Navigation Tabs](#1-frontend-pages--navigation-tabs)
- [2. Backend API Routers & Endpoints](#2-backend-api-routers--endpoints)
- [3. Database Models (`backend/app/models/`)](#3-database-models-backendappmodels)
- [4. Background Jobs (`backend/app/worker.py`)](#4-background-jobs-backendappworkerpy)
- [5. AI Tools (`backend/app/ai/tool_registry.py`) & MCP Server (`backend/app/mcp_server.py`)](#5-ai-tools-backendappaitool_registrypy--mcp-server-backendappmcp_serverpy)
- [6. External & Synthetic Integrations](#6-external--synthetic-integrations)
- [7. Environment Variables Inventory](#7-environment-variables-inventory)
- [8. Alembic Migrations (`backend/alembic/versions/`)](#8-alembic-migrations-backendalembicversions)
- [9. Test Suites Inventory](#9-test-suites-inventory)

---

## 1. Frontend Pages & Navigation Tabs

PulseOps uses tab-based SPA navigation in `frontend/src/App.tsx` + `frontend/src/components/Layout.tsx` rather than `react-router` URL paths (`frontend/vercel.json` rewrites `/(.*) -> /index.html`).

| UI Screen / Tab ID | Source File | Auth State | Features & Status |
| :--- | :--- | :--- | :--- |
| Login / Register View | `frontend/src/pages/AuthPage.tsx` | Unauthenticated (`!token`) | Sign In / Create Organization (`owner`), Render cold-start notice & `/health` ping (**Implemented**) |
| Reconnecting Recovery View | `frontend/src/App.tsx` | `token && sessionError` | Preserves JWT during Render `502`/`503`/`504` wake-ups with Retry / Sign Out (**Implemented**) |
| `dashboard` ("Overview") | `frontend/src/pages/DashboardPage.tsx` | Authenticated | Multi-currency selector & cards, `7D`/`30D`/`90D` window, recurring MRR vs one-time volume, Recharts Area/Bar charts, synthetic toggle (**Implemented**) |
| `events` ("Events Stream") | `frontend/src/pages/EventsPage.tsx` | Authenticated | Source/event-type filters, page search, 50/page pagination, JSON payload inspector, synthetic badge, RFC 4180 CSV export (**Implemented**) |
| `integrations` ("Integrations & CSV") | `frontend/src/pages/IntegrationsPage.tsx` | Authenticated (`owner` writes, `member` sync/CSV) | Connect Razorpay/GitHub/Fake, Sync Now, 2-step Remove confirm, SyncRuns table, webhook URL hint, CSV file/editor (**Implemented**) |
| `copilot` ("AI Copilot") | `frontend/src/pages/CopilotPage.tsx` | Authenticated (`member`+ / `owner` decisions) | Prompt chips, Markdown briefing thread, tool badges, ActionProposal queue w/ RBAC decision buttons (**Implemented**; chat non-streaming & ephemeral) |
| `team` ("Team & RBAC") | `frontend/src/pages/TeamPage.tsx` | Authenticated (`owner` invites) | Members directory, invite existing user by email, Role Capability Matrix (**Implemented**) |
| GitHub OAuth Callback Route (`/integrations/github/callback`) | `.env.example` ref only | N/A | Configured in `.env.example`, **no React route handler implemented in `App.tsx`** (**Partial / Missing Frontend**) |
| API Keys & Audit Logs UI | None | N/A | `/me/api-keys` & `/orgs/{org_id}/audit-logs` exist on backend only (**Not Implemented in Frontend**) |

---

## 2. Backend API Routers & Endpoints

Total: **9** `APIRouter` modules + **4** core routes mounted in `backend/app/main.py` = **32 HTTP API endpoints** (plus `/docs`, `/redoc`, `/openapi.json` when `docs_enabled`).

| Router Module | Method & Path | Auth / Min Role | Status |
| :--- | :--- | :--- | :--- |
| `app/main.py` | `GET /` | Public | Implemented |
| `app/main.py` | `GET /health` | Public | Implemented |
| `app/main.py` | `GET /readiness` | Public | Implemented |
| `app/main.py` | `GET /metrics` | Public | Implemented (Prometheus exposition) |
| `app/main.py` | `GET /docs`, `/redoc`, `/openapi.json` | Public (`docs_enabled`) | Disabled in prod unless `ENABLE_DOCS=true` |
| `app/routers/auth.py` | `POST /auth/register` | Public (RL) | Implemented |
| `app/routers/auth.py` | `POST /auth/login` | Public (RL) | Implemented |
| `app/routers/me.py` | `GET /me` | Bearer JWT | Implemented |
| `app/routers/me.py` | `GET /me/organizations` | Bearer JWT | Implemented |
| `app/routers/me.py` | `POST /me/api-keys` | Bearer JWT | Implemented (API-only; no UI) |
| `app/routers/me.py` | `GET /me/api-keys` | Bearer JWT | Implemented (API-only; no UI) |
| `app/routers/me.py` | `DELETE /me/api-keys/{key_id}` | Bearer JWT (self) | Implemented (API-only; no UI) |
| `app/routers/members.py` | `POST /orgs/{org_id}/members` | `owner` (RL) | Implemented |
| `app/routers/members.py` | `GET /orgs/{org_id}/members` | `viewer` | Implemented |
| `app/routers/integrations.py` | `POST /orgs/{org_id}/integrations` | `owner` (RL) | Implemented |
| `app/routers/integrations.py` | `GET /orgs/{org_id}/integrations` | `viewer` | Implemented |
| `app/routers/integrations.py` | `DELETE /orgs/{org_id}/integrations/{integration_id}` | `owner` (RL) | Implemented |
| `app/routers/integrations.py` | `POST /orgs/{org_id}/integrations/{integration_id}/sync` | `member` (RL) | Implemented (`background=true` requires worker) |
| `app/routers/integrations.py` | `GET /orgs/{org_id}/integrations/github/oauth/url` | `owner` | Partial (no frontend callback route) |
| `app/routers/integrations.py` | `POST /orgs/{org_id}/integrations/github/oauth/callback` | `owner` | Partial (no frontend callback route) |
| `app/routers/integrations.py` | `POST /orgs/{org_id}/imports/csv` | `member` (RL) | Implemented |
| `app/routers/metrics.py` | `GET /orgs/{org_id}/metrics/summary` | `viewer` | Implemented |
| `app/routers/metrics.py` | `GET /orgs/{org_id}/metrics/timeseries` | `viewer` | Implemented |
| `app/routers/metrics.py` | `GET /orgs/{org_id}/events` | `viewer` | Implemented |
| `app/routers/metrics.py` | `GET /orgs/{org_id}/events/export` | `viewer` | Implemented |
| `app/routers/metrics.py` | `GET /orgs/{org_id}/sync-runs` | `viewer` | Implemented |
| `app/routers/sse.py` | `GET /orgs/{org_id}/events/stream` | `viewer` | Implemented on backend (unwired in React UI) |
| `app/routers/audit.py` | `GET /orgs/{org_id}/audit-logs` | `owner` | Implemented (API-only; no UI) |
| `app/routers/copilot.py` | `POST /orgs/{org_id}/copilot/chat` | `viewer` (RL + demo cap) | Implemented (SSE `stream=true` unwired in React UI) |
| `app/routers/copilot.py` | `GET /orgs/{org_id}/copilot/proposals` | `viewer` | Implemented |
| `app/routers/copilot.py` | `POST /orgs/{org_id}/copilot/proposals/{proposal_id}/decision` | `member` (`owner` for disconnect) | Implemented |
| `app/routers/webhooks.py` | `POST /webhooks/razorpay/{org_id}` | HMAC Signature | Implemented |
| `app/routers/webhooks.py` | `POST /webhooks/github/{org_id}` | HMAC Signature | Implemented |

*(RL = Redis fixed-window rate limited.)*

---

## 3. Database Models (`backend/app/models/`)

| Model | Table | File | Tenant Key | Key Purpose & Security Notes |
| :--- | :--- | :--- | :--- | :--- |
| `Organization` | `organizations` | `organization.py` | `id` (root) | Tenant workspace root (`CASCADE` deletes child rows) |
| `User` | `users` | `user.py` | Global principal | Email (case-insensitive unique index) & Argon2id `password_hash` |
| `Membership` | `memberships` | `membership.py` | `organization_id` | Binds `user_id` + `organization_id` + `role` (`owner`/`member`/`viewer`) |
| `Integration` | `integrations` | `integration.py` | `organization_id` | Provider (`razorpay`/`github`/`fake`), status, Fernet `credentials_encrypted` |
| `Event` | `events` | `event.py` | `organization_id` | Idempotent event ledger (`amount_cents` minor units, `minor_unit_exponent`, `currency`, `is_synthetic`, `payload`) |
| `SyncRun` | `sync_runs` | `sync_run.py` | `organization_id` | Audit lifecycle (`pending`/`running`/`completed`/`failed`) + row counts |
| `ActionProposal` | `action_proposals` | `action_proposal.py` | `organization_id` | Human-in-the-loop Copilot mutation queue (`pending`/`approved`/`rejected`/`executed`/`failed`) |
| `AuditLog` | `audit_logs` | `audit_log.py` | `organization_id` (nullable for login/keys) | Immutable audit events with redacted `details` JSONB |
| `ApiKey` | `api_keys` | `api_key.py` | Scoped to `user_id` | SHA-256 hashed `pmcp_` MCP keys, prefix, expiry, `revoked_at` |
| `WebhookDelivery` | `webhook_deliveries` | `webhook_delivery.py` | `organization_id` | Replay deduplication (`organization_id`, `provider`, `delivery_id`) |

---

## 4. Background Jobs (`backend/app/worker.py`)

| Symbol | Queue / Config | Trigger | Production Status |
| :--- | :--- | :--- | :--- |
| `sync_integration_job` | ARQ `WorkerSettings` (`max_tries=3`, `job_timeout=120`, `health_check_interval=15`) | `enqueue_sync_job` (`?background=true`) | Active in local `docker-compose.yml`; worker service commented out in `render.yaml` |
| `enqueue_sync_job` | Redis ARQ pool (`_job_id="sync:{org}:{integ}:{run}"`) | `POST /integrations/{id}/sync?background=true` | Marks `SyncRun` `failed` & returns HTTP `503` if Redis unavailable |

---

## 5. AI Tools (`backend/app/ai/tool_registry.py`) & MCP Server (`backend/app/mcp_server.py`)

### Registered Copilot AI Tools (`ai_tool_registry`)
| Tool Name | Approval Required | `min_role` | Schema Model (`extra="forbid"`) |
| :--- | :---: | :---: | :--- |
| `get_metrics_summary` | No | `viewer` | `GetMetricsSummaryArgs` |
| `get_metrics_timeseries` | No | `viewer` | `GetMetricsTimeseriesArgs` |
| `list_recent_events` | No | `viewer` | `ListRecentEventsArgs` |
| `list_integrations_status` | No | `viewer` | `ListIntegrationsStatusArgs` |
| `sync_organization_integration` | **Yes** | `member` | `SyncIntegrationArgs` |
| `disconnect_integration` | **Yes** | `owner` | `DisconnectIntegrationArgs` |

### Exposed MCP Server Tools (`stdio` transport only)
| MCP Tool Name | Underlying Registry Tool | Auth & Guard |
| :--- | :--- | :--- |
| `pulseops_list_my_organizations` | Direct DB `Membership` query | Valid `pmcp_` key (`authenticate_api_key`) |
| `pulseops_metrics_summary` | `get_metrics_summary` | `pmcp_` key + Org `Membership` + `execute_tool_safely` |
| `pulseops_recent_events` | `list_recent_events` | `pmcp_` key + Org `Membership` + `execute_tool_safely` |
| `pulseops_list_integrations` | `list_integrations_status` | `pmcp_` key + Org `Membership` + `execute_tool_safely` |

---

## 6. External & Synthetic Integrations

| Provider / Component | Source Files | Connection Modes | Status |
| :--- | :--- | :--- | :--- |
| `razorpay` | `backend/app/connectors/razorpay.py` | Test Mode (`rzp_test_*` + Basic Auth) & Mock fallback (`mode: "mock"`) | Implemented; `rzp_live_*` strictly blocked |
| `github` | `backend/app/connectors/github.py` | Fine-Grained PAT, OAuth backend helpers, Mock mode (`mode: "mock"`) | Implemented; frontend OAuth callback missing |
| `csv` | `backend/app/connectors/csv_import.py` | Upload via `/imports/csv` (JSON or `text/csv`, max 2 MB / 10k rows) | Implemented & verified |
| `fake` | `backend/app/connectors/fake.py` | Deterministic synthetic events (`is_synthetic=True`) | Implemented (dev/testing) |
| `deepseek` (LLM Client) | `backend/app/ai/deepseek_client.py` | Bearer `DEEPSEEK_API_KEY` -> `/chat/completions`, or local deterministic fallback | Implemented; mocked in CI tests |

---

## 7. Environment Variables Inventory

- **Core Runtime & DB/Redis (`backend/app/config.py`, `tests/conftest.py`):** `ENVIRONMENT`, `LOG_LEVEL`, `ENABLE_DOCS`, `CORS_ORIGINS`, `DATABASE_URL`, `TEST_DATABASE_URL`, `REDIS_URL`, `JWT_SECRET_KEY`, `INTEGRATION_ENCRYPTION_KEY`.
- **Integrations, Webhooks & AI (`backend/app/config.py`):** `RAZORPAY_MOCK_FALLBACK`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_OAUTH_REDIRECT_URI`, `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`, `DEEPSEEK_MAX_TOKENS`, `DEEPSEEK_MAX_TOOL_ROUNDS`, `COPILOT_CACHE_TTL_SECONDS`, `WEBHOOK_REPLAY_TOLERANCE_SECONDS`, `WEBHOOK_FUTURE_SKEW_SECONDS`.
- **Rate Limits & Demo (`backend/app/config.py`):** `RATE_LIMIT_ENABLED`, `RATE_LIMIT_WINDOW_SECONDS`, `RATE_LIMIT_AUTH_MAX_REQUESTS`, `RATE_LIMIT_COPILOT_MAX_REQUESTS`, `RATE_LIMIT_ORG_WRITE_MAX_REQUESTS`, `DEMO_ACCOUNT_EMAIL`, `DEMO_COPILOT_DAILY_LIMIT`.
- **Docker / Render / MCP / Scripts:** `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `API_PORT`, `POSTGRES_PORT`, `REDIS_PORT`, `PYTHON_VERSION`, `PORT`, `PULSEOPS_MCP_API_KEY`, `PULSEOPS_API_URL`, `PULSEOPS_SMOKE_TOKEN`.
- **Frontend (`frontend/src/lib/api.ts`, `frontend/.env.example`):** `VITE_API_URL`.

*(See [PRODUCT_DOCUMENTATION.md Section I](./PRODUCT_DOCUMENTATION.md#i-environment-variables) for defaults, sensitivity, and exact placeholder formats.)*

---

## 8. Alembic Migrations (`backend/alembic/versions/`)

1. `b8066bd7d2cb` — `create core tables` (`organizations`, `users`, `memberships`, `integrations`)
2. `e2d5e1b78a2a` — `create events table`
3. `0bf59f714d0c` — `create sync_runs table`
4. `d3eb48b5de85` — `create action_proposals table`
5. `c1490b55d429` — `create audit_logs table`
6. `849f79e737c6` — `create api_keys and webhook_deliveries tables`
7. **`9c4a12e8f3b1` (head)** — `add event minor unit exponent and is_synthetic flag`

---

## 9. Test Suites Inventory

### Backend (`backend/tests/` — 18 test files; 202 collected & executed in `v1.3` run)
*(Note: All 202 backend tests executed and passed in the `v1.3` code-verification run prior to doc authoring; during the documentation pass only `pytest --collect-only -q` ran since source code was untouched. External HTTP connectors/LLM APIs use mocks.)*
| Test File | Tests | Primary Scope Verified |
| :--- | :---: | :--- |
| `test_ai_and_copilot.py` | 10 | Tool registry, MCP exposure, DeepSeek fallback/errors, proposal RBAC |
| `test_alembic.py` | 2 | Alembic head parity & schema inspection on `pulseops_test` |
| `test_auth.py` | 30 | Registration, login, `/me`, Argon2id, HS256 JWT validation |
| `test_connectors_and_events.py` | 13 | Connector ABC/Registry, Fake connector, unique ingestion idempotency |
| `test_e2e_phase2_to_end.py` | 1 | Full Phase 2 tenant onboarding -> sync -> CSV -> metrics journey |
| `test_encryption.py` | 9 | Fernet roundtrips, tamper rejection, missing/invalid key guards |
| `test_health.py` | 2 | `/` and `/health` endpoint responses |
| `test_integrations_and_webhooks.py` | 15 | Razorpay/GitHub connectors, CSV import, HMAC webhook validation |
| `test_isolation.py` | 4 | Core cross-tenant DB isolation checks |
| `test_logging.py` | 13 | JSON log schema, `X-Request-ID` validation, secret redaction |
| `test_members.py` | 19 | Organization member invites, role validation, hierarchy enforcement |
| `test_models.py` | 13 | SQLAlchemy constraints, cascades, lowercase email uniqueness |
| `test_monetary_and_copilot_integrity.py` | 14 | ISO-4217 currency utility, INR/JPY/KWD precision, multi-currency metrics, Copilot grounding |
| `test_production_config.py` | 11 | Production fail-closed startup checks, CORS, docs guard |
| `test_s27_to_s38_gaps.py` | 8 | SSE Pub/Sub, CSV formula export, `/readiness`, `/metrics`, Redis rate limits, demo guard |
| `test_security_hardening.py` | 10 | Hashed `pmcp_` MCP keys, LLM arg injection, webhook replay/dedup, JWT claim checks |
| `test_tenant_isolation.py` | 19 | Exhaustive 404 anti-enumeration & cross-tenant isolation proofs |
| `test_worker_and_metrics.py` | 9 | ARQ retries/failure recording, recurring vs one-time metrics, timeseries |

### Frontend (`frontend/src/lib/__tests__/` — 3 files, 11 passing tests)
| Test File | Tests | Primary Scope Verified |
| :--- | :---: | :--- |
| `api.test.ts` | 5 | `resolveApiBaseUrl`, Bearer headers, `X-Request-ID`, CSV import, `503` GET retry & CSV export |
| `format.test.ts` | 3 | INR/USD/JPY/KWD `formatMoneyMinor`, missing/`UNKNOWN` currency safety, UTC dates |
| `markdown.test.ts` | 3 | Safe Markdown unescaping, pipe tables/code blocks, `javascript:` link blocking |
