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

- [ ] Remote CI verification & cloud provisioning (GitHub push, Neon, Upstash, Render, Vercel — manual production deployment completed; awaiting commit/push approval for v1.0 polish changes)

## v1.0 Recruiter-Ready Polish Pass

- [x] Phase 1–3 Audit & Journey Verification — Verified git state (`ea77be1`), backend/frontend tests, RBAC, tenant isolation, Ruff/Gitleaks hygiene, dependency audits, and read-only deployed Vercel UI inspection (`https://pulseops-two.vercel.app/`).
- [x] Frontend v1.0 Polish — Added Render free-tier cold-start resilience (request timeout, transient `502`/`503`/`504` GET retry, session preservation with Retry UI instead of logout, `/health` wake ping, slow-wake banner), wired `EventsPage` pagination + RFC 4180 CSV export + `pr.closed`/`payment.failed` filters, added org-switch state resets across tabs, two-step remove confirmation and inline failed `SyncRun` error visibility in `IntegrationsPage`, strict `disconnect_integration` owner-only decision gating and tool execution badges in `CopilotPage`, mobile `.segmented` alignment fix, `--bg-surface-subtle` token definition, and Vite `recharts`/`react` chunk splitting.
- [x] Backend & Hygiene Fixes — Fixed `TestProductionSettingsValidation` `.env` isolation failure, cleared PyJWT short-key & Starlette `HTTP_422_UNPROCESSABLE_CONTENT` warnings, handled background ARQ queue failures gracefully (`SyncRun` marked `failed` + HTTP `503`), caught `EncryptionError` cleanly during sync, added `disconnect` intent RBAC support to Copilot fallback, exposed `Content-Disposition` via CORS, trimmed metrics open-issue query columns, guarded demo scripts (`seed_demo_data.py`, `reset_demo_owner_password.py`) against accidental remote/production/test execution, added `*.tsbuildinfo` to `.gitignore`, and updated `README.md` with full v1.0 deployment architecture, Mermaid diagram, limitations, and demo role table.

## v1.1 External Integrations & AI Copilot Activation

- [x] Razorpay, GitHub, DeepSeek, ARQ Worker & MCP Hardening — Hardened Razorpay Test Mode error/rate-limit/refund-envelope handling, GitHub 403/404/OAuth error handling and PR `sort=updated` sync, DeepSeek HTTP `401`/`429`/timeout/malformed JSON handling and session rollback on fallback, added `event_type` filtering to `list_recent_events` & MCP for failed-payment summaries, exposed webhook secret input & endpoint URLs in `IntegrationsPage`, enforced ARQ `_job_id` deduplication and final-retry `SyncRun` failure recording, verified MCP SDK client-session protocol execution, added mocked tests for all error paths, and created `docs/EXTERNAL_INTEGRATION_SETUP.md`.

## v1.2 Frontend Redesign — Meridian Visual Identity

- [x] Design Discovery Phase — Completed impeccable audit of existing frontend (`DashboardPage`, `CopilotPage`, `IntegrationsPage`, `EventsPage`, `TeamPage`, `AuthPage`, `Layout`, `styles.css`) and documented three visual directions and the Meridian design system in `DESIGN.md`.
- [x] Complete Frontend Redesign (Meridian v2.0) — Implemented Meridian design tokens in `frontend/src/styles.css` (`#0d0d0f` warm-dark canvas, Sky `#0ea5e9` action/nav accent, Emerald `#10b981` restricted to positive/success semantics, `tabular-nums`, comfortable typography scale, responsive breakpoints across 1440px/1024px/768px/375px, and `prefers-reduced-motion` gating). Extracted reusable components (`KpiCard`, `ChartPanel`, `StatusBadge`, `EmptyState`, `MarkdownContent`). Redesigned `Layout`, `PulseOpsLogo`, `favicon.svg`, `index.html`, `DashboardPage` (KPI grid, financial & cycle-time/connector health row, side-by-side responsive Recharts panels with 13px axis labels), `CopilotPage` (safe Markdown rendering for headings, bold, lists, pipe tables, fenced/inline code, and escaped-markdown unescaping), `IntegrationsPage`, `EventsPage`, `TeamPage` (semantic Role Capability Matrix table), and `AuthPage`. Verified `vitest run` (3 suites, 10 tests passing), `tsc -b`, `vite build`, `git diff --check`, and browser visual inspection of `AuthPage` at 1440x900, 768x1024, and 375x812 (0 horizontal overflow, 0 uncaught JS errors).

## v1.3 Monetary Integrity, Multi-Currency Reporting & Copilot Grounding

- [x] Canonical Monetary Architecture & Connectors — Added ISO-4217 currency registry and pure `Decimal` minor/major unit helpers in `backend/app/core/currency.py` (handling 0-, 2-, 3-, and 4-decimal currencies plus currency-specific minor-unit names such as paise, cents, fils, and yen). Preserved `events.amount_cents` for compatibility while adding `events.minor_unit_exponent` and `events.is_synthetic` via non-destructive Alembic migration `9c4a12e8f3b1` (`minor_unit_exponent`, `is_synthetic`, `ix_events_org_currency_synthetic`, safe backfill). Exposed `amount_minor`, `minor_unit_exponent`, `minor_unit_name`, `amount_major`, `formatted_amount`, and `is_synthetic` across `NormalizedEvent`, `EventResponse`, and CSV exports; fixed Razorpay/CSV/fake/demo connectors and correlation field extraction.
- [x] Multi-Currency Metrics & Synthetic Provenance Separation — Refactored `metrics_service` and `/metrics/*` schemas/routers to aggregate revenue, recurring MRR/ARR (deduplicated `subscription.charged` minus linked refunds, excluding cancelled subscriptions), one-time `payment.captured` volume, refunds, and failed payments strictly per currency (`by_currency`, `currencies`, `primary_currency`, `multi_currency`) without cross-currency addition. Suppressed legacy scalar `*_cents` fields (`null`) when `multi_currency=True` and excluded `is_synthetic=True` events by default (`include_synthetic=False`) while exposing provenance counts (`synthetic_events_in_window`, `synthetic_events_excluded`).
- [x] Copilot Grounding & Frontend Multi-Currency UI — Hardened `ai_tool_registry` (`list_recent_events`, `list_integrations_status`), `mcp_server`, `COPILOT_SYSTEM_PROMPT`, and deterministic Copilot fallback against minor/major-unit confusion, unverified retry/double-billing speculation without matching correlation IDs, cross-currency totals, synthetic data conflation, and prompt injection. Updated frontend formatting (`formatMoneyMinor` without USD fallback), multi-currency Dashboard selector & breakdown cards, Events synthetic badges & currency formatting, and CSV helper templates. Verified locally: `pytest` (202 passed in 44.50s), `pip check` (0 broken requirements), `vitest run` (3 suites, 11 passed), `tsc -b && vite build`, `npm audit --omit=dev` (0 vulnerabilities), and `gitleaks` (16 commits scanned, 0 leaks).
