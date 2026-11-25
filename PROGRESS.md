# PulseOps Development Progress

## Phase 0: Setup

- [x] S01 - Accounts and tools
- [x] S02 - Repository and folder layout
- [x] S03 - Docker Compose
- [x] S04 - FastAPI hello world and database health check

## Phase 1: Core Foundation

- [x] S05 - Database models and first migration (Core models, Alembic initial migration, credential encryption, and isolated test database)
- [x] S06 - Authentication and JWT (Argon2id password hashing, HS256 JWT, register/login/me endpoints, 30 tests)
- [x] S07 - Organization membership and role checks (RBAC hierarchy, get_current_membership, require_role, add/list member endpoints, 19 tests)
- [x] S08 - Tenant isolation tests (Multi-tenant cross-org boundary proofs, 404 obscurity, RBAC enforcement, model query isolation, 19 tests)
- [x] S09 - GitHub Actions CI (Automated workflow for push and PR to main: PostgreSQL 16 & Redis 7 services, Gitleaks scan, Ruff lint checks, dedicated CI test database migrations, full pytest suite with 98 passing tests)
- [x] S10 - Structured logging and request IDs (StructuredJsonFormatter, RequestLoggingMiddleware with UUID X-Request-ID propagation, duration metrics, user/org context tracking, secret redaction, 13 new tests, 111 total tests passing)

## Phase 2: Connectors, Ingestion, Workers & Metrics (S11–S21)

- [x] S11 - Event & Connector Architecture (Abstract `BaseConnector`, `ConnectorRegistry`, `FakeConnector`, normalized `Event` model + `e2d5e1b78a2a` migration, `uq_events_org_source_external_id`, idempotent ingestion, 13 tests)
- [x] S12 - Integration Management API (Tenant-scoped CRUD + encrypted credentials + `/sync` + RBAC)
- [x] S13 - Razorpay Connector (Test Mode API normalization, live-key guard, conditional mock-billing fallback)
- [x] S14 - GitHub Connector & OAuth (REST PR/issue sync, cycle-time calculation, mock mode, HMAC-signed OAuth state)
- [x] S15 - CSV Import Connector & Endpoint (`POST /orgs/{org_id}/imports/csv` JSON & `text/csv`, SHA-256 deterministic idempotency)
- [x] S16 - Inbound Webhooks (`POST /webhooks/razorpay/{org_id}` & `/webhooks/github/{org_id}`, constant-time HMAC-SHA256 verification)
- [x] S17 - Redis + ARQ Background Worker (`app.worker.WorkerSettings`, `sync_integration_job`, `rediss://` TLS DSN support)
- [x] S18 - SyncRun Audit Model (`SyncRun` + `0bf59f714d0c` migration, `GET /orgs/{org_id}/sync-runs`)
- [x] S19–S21 - Metrics Engine, Events/Metrics REST API & Cross-Tenant Acceptance Tests (MRR, ARR, churn, PRs, open issues, cycle time, daily timeseries)

## Phase 3: Frontend Control Tower (S22–S29)

- [x] S22–S29 - React + Vite + TypeScript + Recharts Dashboard (`frontend/`: Auth & Org switcher, KPI overview, Revenue/Churn & Engineering Recharts charts, Integrations & CSV hub, Events stream, Team RBAC, Copilot & Approvals UI, `vercel.json`, Vitest unit tests + Vite production build), plus S27 SSE Redis Pub/Sub real-time updates (`/orgs/{org_id}/events/stream`) and S28 tenant-scoped CSV export (`/orgs/{org_id}/events/export`)

## Phase 4: AI Layer, MCP Server & Human-in-the-Loop Approvals (S30–S39)

- [x] S30–S35 - AI Tool Registry, `AuditLog` (`c1490b55d429` migration, `GET /orgs/{org_id}/audit-logs` owner-only), MCP Python SDK Server (`MCPServer` in `app.mcp_server`, `stdio` transport; per-user hashed API keys documented in `docs/security-backlog.md`), & DeepSeek Client (tool calling, bounded rounds, SSE streaming, Redis caching, deterministic local fallback)
- [x] S36–S39 - `ActionProposal` model (`d3eb48b5de85` migration), Copilot Chat & Approval Workflow, Prometheus `/metrics` & `/readiness`, Redis rate limiting (`429` + `Retry-After`), Synthetic Demo Environment (`scripts/seed_demo_data.py`, read-only viewer + 5/day Copilot cap), and Operations Runbooks (`docs/deployment/`)

## Phase 5: End-to-End Verification & Deployment Readiness (S40–S47)

- [x] S40–S47 - End-to-end journey & isolation test suite, production configuration hardening (`render.yaml`, `Dockerfile`, CORS, Neon pooling), CI pipeline (`test` + `frontend` jobs), smoke tests (`scripts/smoke_test.py`), demo storyboard (`docs/demo-storyboard.md`), and pilot onboarding guide (`docs/pilot-onboarding.md`)

## Phase 3: Security Hardening & Remediation

- [x] Security Hardening Pass - Per-user hashed MCP API keys (`api_keys` + `/me/api-keys` + `849f79e737c6` migration) & tenant-scoped `stdio` MCP authorization, strict Pydantic `extra="forbid"` AI tool arg validation + RBAC proposal guards, webhook timestamp replay window + `webhook_deliveries` deduplication, normalized-email brute-force throttling, JWT required claims, and expanded log/`AuditLog` credential redaction

## Pending External Execution

- [ ] Remote CI verification & cloud provisioning (GitHub push, Neon, Upstash, Render, Vercel — requires explicit user approval/execution)
