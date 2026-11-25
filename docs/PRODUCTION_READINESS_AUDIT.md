# PulseOps — Production Readiness Audit

> **Audit Date:** 2026-11-25  
> **Scope:** Read-only code, configuration, schema, test, and deployment-artifact audit covering the `v1.2` Meridian UI + `v1.3` Monetary Integrity & Copilot Grounding state (`main`, Alembic head `9c4a12e8f3b1`).  
> **Verdict:** **Portfolio / Pilot-Ready with Test Mode Safety Controls; Not Yet Ready for Real Paying Customers** until **P0** browser/session security hardening, privacy/compliance controls, external AI PII scrubbing, and live-billing integration policy decisions are resolved. *(Schema parity at Alembic `9c4a12e8f3b1` is confirmed in production Neon and is not a blocker.)*

---

## Table of Contents

- [Executive Summary](#executive-summary)
- [Audit Findings by Domain (1–18)](#audit-findings-by-domain-118)
  - [1. Application Security](#1-application-security)
  - [2. Authentication](#2-authentication)
  - [3. Authorization](#3-authorization)
  - [4. Multi-Tenancy](#4-multi-tenancy)
  - [5. Database Reliability](#5-database-reliability)
  - [6. API Reliability](#6-api-reliability)
  - [7. Frontend Resilience](#7-frontend-resilience)
  - [8. AI Safety](#8-ai-safety)
  - [9. Integration Reliability](#9-integration-reliability)
  - [10. Background Jobs](#10-background-jobs)
  - [11. Monitoring and Alerting](#11-monitoring-and-alerting)
  - [12. Performance](#12-performance)
  - [13. Scalability](#13-scalability)
  - [14. Disaster Recovery](#14-disaster-recovery)
  - [15. Privacy and Compliance](#15-privacy-and-compliance)
  - [16. Deployment and CI/CD](#16-deployment-and-cicd)
  - [17. Testing Coverage](#17-testing-coverage)
  - [18. Cost Management](#18-cost-management)
- [Prioritized Remediation Roadmap](#prioritized-remediation-roadmap)

---

## Executive Summary

PulseOps has strong core multi-tenant engineering foundations for an early-stage SaaS codebase: PostgreSQL tenant isolation with `404` anti-enumeration, Argon2id password hashing, Fernet encryption for connector secrets, fail-closed production startup checks (`validate_production_settings`), atomic webhook deduplication + HMAC verification, strict `extra="forbid"` AI tool schemas with human-in-the-loop proposals, and `v1.3` ISO-4217 multi-currency & synthetic-data separation (verified in code and tests during `v1.3`, with Alembic `9c4a12e8f3b1` applied to production Neon, `events.is_synthetic` and `events.minor_unit_exponent` verified, and post-migration Dashboard metrics confirmed working).

However, **deployability and passing unit suites are not full commercial production readiness**. Specifically:
1. **Auth, Browser Headers & Compliance Gaps (`P0`):** JWTs sit in `localStorage` without refresh/revocation or explicit CSP/`X-Frame-Options` headers, users cannot reset passwords, verify emails, or delete accounts/data, Privacy/Terms disclosures are absent, customer email `actor` values can reach DeepSeek prompts, and `RazorpayConnector` currently blocks `rzp_live_*` keys.
2. **Infrastructure & Product Limitations (`P1`/`P3`):** Background ARQ worker execution (`pulseops-worker`) is disabled on Render free tier (**known infrastructure limitation**), and cross-currency consolidated analytics / FX conversion remain unimplemented (`fx_conversion_applied=false`, **outstanding product limitation**).
3. **Zero-Downtime Operations & Alerting (`P1`):** Credential encryption uses single-key `Fernet`, external uptime/5xx alerting is missing, and database backup restoration has never been verified via a documented restore drill.

---

## Audit Findings by Domain (1–18)

### 1. Application Security
- **Current Implementation:** Single-line JSON logging with recursive secret redaction (`StructuredJsonFormatter`), `gitleaks` pre-commit & CI checks, CSV formula-injection neutralization (`'=` prefix), Markdown sanitizer blocking `javascript:` links, fail-closed CORS & key validation (`ENVIRONMENT=production`), Fernet encryption at rest.
- **Evidence:** `backend/app/core/logging.py`, `backend/app/core/security.py`, `backend/app/services/audit_service.py`, `backend/app/connectors/csv_import.py`, `frontend/src/components/MarkdownContent.tsx`, `.pre-commit-config.yaml`, `backend/tests/test_security_hardening.py`.
- **Current Status:** `Verified` in automated unit/integration tests (Fernet tamper/wrong-key rejection, CSV escaping, Markdown `javascript:` block, JSON/`AuditLog` redaction, `gitleaks` history scan) / `Not verified` or missing on live deployed HTTP headers & key rotation.
- **Risk Severity:** `High`
- **What Is Missing:**
  - HTTP security headers (`Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `X-Frame-Options: DENY`) in Vercel (`frontend/vercel.json`) and/or FastAPI responses.
  - `MultiFernet` zero-downtime key rotation (`backend/app/core/security.py`).
  - Live penetration / DAST testing and response-header verification against Render/Vercel endpoints.
- **Recommended Action:** Configure explicit security response headers in `frontend/vercel.json` (especially strict CSP + `frame-ancestors 'none'` since JWTs are in `localStorage`) and add `MultiFernet` rotation support before production customer onboarding.
- **Files to Modify:** `frontend/vercel.json`, `backend/app/main.py`, `backend/app/core/security.py`.
- **Verification:** `curl -I https://pulseops-two.vercel.app/` header assertions + `pytest tests/test_encryption.py` with dual-key `MultiFernet` cases.

### 2. Authentication
- **Current Implementation:** Argon2id password hashing (`pwdlib`), constant-time dummy hash check on unknown emails, normalized lowercase emails (`ix_users_email_lower`), HS256 JWT (`sub`, `iat`, `exp` = 1h), IP + normalized-email Redis rate limiting (`20`/`60s`), `pmcp_` SHA-256 hashed MCP keys.
- **Evidence:** `backend/app/core/auth.py`, `backend/app/routers/auth.py`, `backend/app/routers/me.py`, `backend/app/services/api_key_service.py`, `backend/tests/test_auth.py` (30 tests), `test_security_hardening.py`.
- **Current Status:** `Verified` in code & automated tests for registration/login/`/me`/`pmcp_` lifecycle / `Partially verified` operationally (Redis rate limiting fails open by design if Upstash errors; live concurrency throttling untested).
- **Risk Severity:** `High`
- **What Is Missing:**
  - Refresh tokens or active session/JWT revocation (`jti` blocklist / token version) — compromised JWT remains valid for up to 60 minutes.
  - Password reset / recovery flow, email verification on signup, and `POST /auth/change-password`.
  - Browser storage uses `localStorage` (`AuthContext.tsx`) rather than `HttpOnly; Secure; SameSite` cookies.
- **Recommended Action:** Implement `token_version` invalidation on password change/logout, email verification for real signups, and password reset; evaluate migrating web session tokens to `HttpOnly` cookies (or pairing strict CSP with `localStorage`).
- **Files to Modify:** `backend/app/models/user.py`, `backend/app/core/auth.py`, `backend/app/routers/auth.py`, `frontend/src/context/AuthContext.tsx`.
- **Verification:** New `pytest` suite covering revoked JWTs, expired tokens, password reset flow, and cookie/CSRF tests.

### 3. Authorization
- **Current Implementation:** `ROLE_HIERARCHY` (`owner`: 3, `member`: 2, `viewer`: 1) enforced via `require_role(...)` backend FastAPI dependencies; separate role enforcement on MCP stdio and AI proposal creation/decision (`_resolve_caller_role`).
- **Evidence:** `backend/app/core/auth.py:177-250`, `backend/app/routers/{members,integrations,audit,copilot}.py`, `backend/app/mcp_server.py`, `backend/tests/test_members.py` (19), `test_security_hardening.py` (10).
- **Current Status:** `Verified`
- **Risk Severity:** `Low`
- **What Is Missing:** Endpoints to demote/promote/remove existing organization members (`PATCH`/`DELETE /orgs/{org_id}/members/{member_id}`) and last-owner protection against orphan organizations.
- **Recommended Action:** Add owner-only member role update/removal endpoints with a strict guard preventing removal/demotion of the last `owner`.
- **Files to Modify:** `backend/app/routers/members.py`, `backend/app/schemas/member.py`, `frontend/src/pages/TeamPage.tsx`.
- **Verification:** `pytest` cases confirming `member`/`viewer` receive `403`, cross-tenant receives `404`, and last owner cannot be removed.

### 4. Multi-Tenancy
- **Current Implementation:** Every tenant table (`memberships`, `integrations`, `events`, `sync_runs`, `action_proposals`, `audit_logs`, `webhook_deliveries`) carries `organization_id` FK (`CASCADE`). Non-members receive HTTP `404` identically to nonexistent UUIDs. Cross-tenant checks span queries, ingestion, metrics, SSE Redis channels (`pulseops:org:{org_id}:events`), Copilot cache keys, and MCP.
- **Evidence:** `backend/app/models/*.py`, `backend/app/core/auth.py:184-215`, `backend/tests/test_tenant_isolation.py` (19 tests), `test_isolation.py` (4 tests), `test_monetary_and_copilot_integrity.py`.
- **Current Status:** `Verified`
- **Risk Severity:** `Low` *(Critical to preserve continuously)*
- **What Is Missing:** PostgreSQL Row-Level Security (RLS) defense-in-depth at the database layer (currently isolation is application-enforced via SQLAlchemy filters).
- **Recommended Action:** Retain mandatory regression gate on every PR and evaluate Postgres RLS policies keyed by session tenant variable for defense-in-depth before scaling engineering headcount.
- **Files to Modify:** Future Alembic migration + `backend/app/db/session.py` (`SET LOCAL`) if RLS is adopted.
- **Verification:** Existing 23+ cross-tenant isolation tests (`test_tenant_isolation.py`, `test_isolation.py`) plus RLS bypass tests if implemented.

### 5. Database Reliability
- **Current Implementation:** SQLAlchemy 2 engine with `pool_pre_ping=True`, `pool_recycle=300`, `pool_size=5`, `max_overflow=10` tailored for Neon idle suspends; psycopg 3 URL normalization (`config.py`); idempotent `ON CONFLICT DO NOTHING` ingestion; 7 sequential Alembic migrations through `9c4a12e8f3b1`.
- **Evidence:** `backend/app/db/session.py`, `backend/app/config.py:7-20`, `backend/alembic/versions/*.py`, `backend/tests/test_alembic.py` (2 tests). Historical pre-`9c4a12e8f3b1` schema drift risk is **resolved**: production Neon was verified at revision `9c4a12e8f3b1`, `events.is_synthetic` and `events.minor_unit_exponent` columns were confirmed, and post-migration Dashboard metrics & app behavior were confirmed working.
- **Current Status:** `Verified`
- **Risk Severity:** `Low`
- **What Is Missing:**
  - Automated migration hook (`preDeployCommand`) for *future* migrations in `render.yaml` (commented worker / free tier lacks Render `preDeployCommand`).
- **Recommended Action:** Maintain manual Neon branching + Direct URL `alembic upgrade head` discipline for future schema changes, or add `preDeployCommand` if Render Starter tier is adopted.
- **Files to Modify:** `render.yaml` (`preDeployCommand` if upgraded to Starter).
- **Verification:** `alembic current` == `9c4a12e8f3b1 (head)` and `scripts/smoke_test.py` returning HTTP `200`.

### 6. API Reliability
- **Current Implementation:** Consistent Pydantic validation (`422`), explicit `HTTPException` handling for `ConnectorError` (`502`), `EncryptionError` (`500`), ARQ enqueue failures (`503`), `X-Request-ID` UUID tracing across 500 JSON responses, and graceful global exception capture in `RequestLoggingMiddleware`.
- **Evidence:** `backend/app/main.py`, `backend/app/core/logging.py:272-368`, `backend/app/routers/*.py`, `backend/tests/test_logging.py`.
- **Current Status:** `Verified`
- **Risk Severity:** `Medium`
- **What Is Missing:**
  - `BaseHTTPMiddleware` (`RequestLoggingMiddleware` and `MonitoringMiddleware`) in Starlette can impact `StreamingResponse` cancellation/buffering overhead under high SSE concurrency.
  - Synchronous `POST /integrations/{id}/sync` hits external Razorpay/GitHub APIs inline inside request worker threads (up to 10 paginated HTTP calls per provider); slow upstream responses can block a Uvicorn worker or trigger Render HTTP timeouts.
  - Several list endpoints (`GET /integrations`, `GET /members`, `GET /me/api-keys`) lack pagination limits (low risk for small SaaS teams, risky at large scale).
- **Recommended Action:** Enforce `limit` caps consistently and enable `pulseops-worker` on paid Render tier so connector syncs execute out-of-band.
- **Files to Modify:** `backend/app/routers/{members,integrations,me}.py`, `render.yaml`.
- **Verification:** `pytest` + load/timeout tests simulating slow external connector responses.

### 7. Frontend Resilience
- **Current Implementation:** `45s` fetch timeout, automatic 1-retry (`1.5s` backoff) for idempotent `GET` requests returning `502`/`503`/`504`, `/health` warm-up ping on `AuthPage` mount + slow-wake notice (`3.5s`), session preservation with `Control Tower Reconnecting` Retry UI on transient startup failures (only logging out on `401`/`404`), and build-time `resolveApiBaseUrl` localhost guard.
- **Evidence:** `frontend/src/lib/api.ts`, `frontend/src/context/AuthContext.tsx`, `frontend/src/pages/AuthPage.tsx`, `frontend/src/lib/__tests__/api.test.ts` (5 tests).
- **Current Status:** `Verified` (unit tests & `AuthPage` browser check) / `Partially verified` (live authenticated flows across all 5 tabs).
- **Risk Severity:** `Medium`
- **What Is Missing:**
  - React ErrorBoundary (`componentDidCatch`) around `ControlTowerShell` / Recharts panels to catch unexpected runtime exceptions without blanking the viewport.
  - Unexposed UI screens for `/me/api-keys`, `/audit-logs`, GitHub OAuth callback (`/integrations/github/callback`), and SSE `/events/stream` live updates.
  - Ephemeral Copilot chat history lost on browser reload.
- **Recommended Action:** Add a top-level React ErrorBoundary, implement `/me/api-keys` & `/audit-logs` UI panels, and add the GitHub OAuth callback route if OAuth is kept enabled.
- **Files to Modify:** `frontend/src/App.tsx`, `frontend/src/pages/{IntegrationsPage,CopilotPage,TeamPage}.tsx`.
- **Verification:** Component tests with mocked failures + full Playwright E2E suite.

### 8. AI Safety
- **Current Implementation:** `COPILOT_SYSTEM_PROMPT` grounding rules, centralized `execute_tool_safely()`, `ConfigDict(extra="forbid")` on all 6 tools, explicit `RESERVED_TOOL_CONTEXT_KEYS` rejection, control-char stripping & 120-char truncation (`_sanitize_untrusted_text`), PG savepoint rollback on DeepSeek failures, strict `allow_mutating_execution=False` during chat, `ActionProposal` + RBAC re-check on `/decision`, bounded `max_tokens=800` & `max_tool_rounds=3`, and demo viewer `5/day` cap.
- **Evidence:** `backend/app/ai/tool_registry.py`, `backend/app/ai/deepseek_client.py`, `backend/app/services/copilot_service.py`, `backend/tests/test_ai_and_copilot.py` (10), `test_security_hardening.py`, `test_monetary_and_copilot_integrity.py`.
- **Current Status:** `Verified` (tool boundary, fallback, and mocked LLM loop).
- **Risk Severity:** `Medium`
- **What Is Missing:**
  - Automated red-team test suite against **live** DeepSeek responses for subtle prose prompt injection or fabricated numbers when external untrusted strings (`event.actor` / GitHub issue `title`) contain adversarial instructions.
  - PII stripping before sending `actor` emails to third-party DeepSeek APIs (`event.actor` may contain customer email addresses from Razorpay).
- **Recommended Action:** Hash or pseudonymize customer email `actor` values in LLM tool payloads (or document DeepSeek data processor terms clearly in privacy disclosures) and run scheduled adversarial evaluations.
- **Files to Modify:** `backend/app/ai/tool_registry.py` (`_tool_list_recent_events`), `docs/`.
- **Verification:** `pytest tests/test_monetary_and_copilot_integrity.py` + PII redaction unit tests.

### 9. Integration Reliability
- **Current Implementation:** Connector interface (`BaseConnector`) + idempotent `ON CONFLICT DO NOTHING`, `SyncRun` lifecycle (`events_received`/`inserted`/`skipped`/`error_message`), explicit HTTP `401`/`403`/`404`/`429` error mapping, webhook HMAC-SHA256 + timestamp checks + `webhook_deliveries` dedup, Razorpay `rzp_live_*` key rejection.
- **Evidence:** `backend/app/connectors/*.py`, `backend/app/services/{integration_service,webhook_service,event_service}.py`, `backend/tests/test_integrations_and_webhooks.py` (15 tests using mocked HTTP transports).
- **Current Status:** `Verified` (mocked HTTP transport unit/integration tests) / `Not verified` (automated live external connectivity against Razorpay Test Mode, GitHub REST, and DeepSeek API in CI).
- **Risk Severity:** `High`
- **What Is Missing:**
  - `RazorpayConnector` & `GitHubConnector` paginate only up to `max_pages=10` (500 Razorpay payments, 1,000 PRs/issues) without cursor continuation warning; high-volume teams silently truncate older history during `full_sync=true`.
  - No automatic HTTP retry/backoff on transient `5xx`/`429` from Razorpay or GitHub inside synchronous syncs (ARQ retries only apply when `background=true` + worker running).
  - Razorpay `/v1/payments` direct API polling mostly returns `payment` entities rather than `subscription` entities (`subscription.charged` typically relies on webhooks/mock fallback).
  - Live `rzp_live_*` keys are blocked in `RazorpayConnector`, preventing real customer live billing connections.
  - GitHub webhook verification does not mandate `X-Webhook-Timestamp` unless supplied (relies on `X-GitHub-Delivery` UUID deduplication).
- **Recommended Action:** Add pagination truncation warnings in `SyncRun`, add bounded retry on `429`/`5xx`, sync Razorpay `/v1/subscriptions` or document webhook dependency clearly, and wire optional external sandbox connectivity smoke checks.
- **Files to Modify:** `backend/app/connectors/{razorpay,github}.py`, `backend/app/services/integration_service.py`.
- **Verification:** Pagination boundary & retry tests using `httpx.MockTransport` plus verified live Test Mode / PAT connection smoke runs.

### 10. Background Jobs
- **Current Implementation:** `WorkerSettings` (`arq app.worker.WorkerSettings`) with `max_tries=3`, `job_timeout=120s`, `defer=job_try*5s`, deterministic `_job_id`, `rediss://` TLS parsing, final-retry failure recording in `SyncRun`, and HTTP `503` guard when Redis enqueue fails.
- **Evidence:** `backend/app/worker.py`, `docker-compose.yml:34-68`, `render.yaml:31-53`, `backend/tests/test_worker_and_metrics.py`.
- **Current Status:** `Verified` (Docker & pytest) / `Missing` in live Render production (**known infrastructure limitation:** `pulseops-worker` disabled on free tier in `render.yaml`).
- **Risk Severity:** `Medium`
- **What Is Missing:** Live always-on worker process in Render production (forcing synchronous `/sync` execution inside HTTP requests), plus dead-letter visibility or scheduled periodic sync cron (`cron_jobs` in ARQ `WorkerSettings`).
- **Recommended Action:** Enable `pulseops-worker` on Render Starter plan when upgrading from free tier, and configure scheduled incremental syncs per active integration.
- **Files to Modify:** `render.yaml`, `backend/app/worker.py`.
- **Verification:** `arq app.worker.WorkerSettings --check` in Render worker + end-to-end `?background=true` job completion.

### 11. Monitoring and Alerting
- **Current Implementation:** `/health` (DB), `/readiness` (DB + Redis), `/metrics` (Prometheus request counters/histograms, event ingestion counters, rate-limit counters), structured JSON logs with UUID `X-Request-ID`.
- **Evidence:** `backend/app/core/{monitoring,logging}.py`, `backend/app/main.py:106-136`, `backend/tests/test_s27_to_s38_gaps.py`.
- **Current Status:** `Partially verified` (endpoints exist & tested; external alerting missing).
- **Risk Severity:** `High`
- **What Is Missing:**
  - **No external alerting / uptime monitors** configured in repo (no Slack/Email/PagerDuty alerts for `/readiness` `503`, `5xx` spikes, or failed syncs).
  - **`GET /metrics` is unauthenticated**, exposing operational endpoint labels and request volume publicly unless restricted by network/IP or bearer auth.
  - No Prometheus server/Grafana Cloud scraper configured to retain `/metrics` history across Render free-tier container restarts (in-memory Prometheus counters reset on every cold start!).
- **Recommended Action:** Add external uptime monitoring on `/readiness`, ship Render JSON logs + scrape `/metrics` externally (restrict `/metrics` via internal secret header or bearer token if sensitive), and define 5xx/latency alert thresholds.
- **Files to Modify:** `backend/app/main.py` (`/metrics` guard) + external monitoring setup.
- **Verification:** Deliberate `/readiness` failure test triggering alert notification + authenticated `/metrics` scrape check.

### 12. Performance
- **Current Implementation:** Indexed queries (`ix_events_org_occurred`, `ix_events_org_currency_synthetic`, `ix_sync_runs_org_started`, `ix_audit_logs_org_created`), SQLAlchemy connection pool tuning, Vite manual chunking (`recharts`/`d3-`), Redis Copilot caching (`120s`).
- **Evidence:** `backend/app/models/*.py`, `backend/app/db/session.py`, `frontend/vite.config.ts`.
- **Current Status:** `Not verified` (under load).
- **Risk Severity:** `Medium`
- **What Is Missing:**
  - `compute_metrics_summary` & `compute_metrics_timeseries` load **all** matching `Event` ORM objects in `[since, now]` (plus all historical `issue.opened`/`issue.closed` events) into Python memory rather than aggregating in SQL (`GROUP BY`), which will degrade memory/latency for high-event tenants.
  - No load testing benchmarks (p95/p99 API latency under concurrency).
- **Recommended Action:** Refactor `metrics_service` aggregations to push filtering/grouping/timeseries bucketing into PostgreSQL SQL queries (`func.sum`, `date_trunc`) or materialized rollups for high-volume organizations, and run k6/Locust benchmarks.
- **Files to Modify:** `backend/app/services/metrics_service.py`.
- **Verification:** Load test simulating 50k+ events/org verifying sub-200ms p95 summary response time.

### 13. Scalability
- **Current Implementation:** Stateless FastAPI JWT auth allows horizontal web scaling; Redis handles shared rate limits, SSE Pub/Sub, and cache invalidation; Postgres enforces unique ingestion constraints.
- **Evidence:** `backend/app/core/{auth,rate_limit}.py`, `backend/app/services/{event_service,realtime_service}.py`.
- **Current Status:** `Partially verified`
- **Risk Severity:** `Medium`
- **What Is Missing:**
  - Single Render free-tier instance (`512 MB` RAM, sleeps after idle); `rate_limit.py` caches sync Redis clients in `_REDIS_CLIENTS`, while `realtime_service.subscribe_org_events` opens a new `aioredis.from_url(...)` client per SSE subscriber.
  - No Redis fail-closed toggle / fallback rate limiter (`rate_limit.py` disables all rate limiting if Upstash quota exhausts or disconnects).
- **Recommended Action:** Share an async Redis connection pool for SSE subscriptions, upgrade hosting plans when scaling concurrent users, and alert on rate-limit Redis bypass warnings.
- **Files to Modify:** `backend/app/services/realtime_service.py`, `backend/app/core/rate_limit.py`.
- **Verification:** Concurrent SSE connection test confirming bounded Redis connection usage.

### 14. Disaster Recovery
- **Current Implementation:** Neon PITR branching & `pg_dump`/`pg_restore` steps documented in `docs/deployment/README.md`, single `Fernet` key rotation snippet documented in `docs/deployment/secrets-and-encryption.md`.
- **Evidence:** `docs/deployment/README.md`, `docs/deployment/secrets-and-encryption.md`.
- **Current Status:** `Not verified` (procedures documented; execution untested).
- **Risk Severity:** `High`
- **What Is Missing:**
  - **No tested restore drill** proving a backup dump / Neon branch plus backed-up `INTEGRATION_ENCRYPTION_KEY` restores cleanly and decrypts `integrations.credentials_encrypted`.
  - No `MultiFernet` automated key rotation support.
- **Recommended Action:** Execute a non-destructive Neon branch restore drill, document RPO/RTO targets, verify `INTEGRATION_ENCRYPTION_KEY` is vaulted offsite, and implement `MultiFernet` rotation.
- **Files to Modify:** `backend/app/core/security.py`, `docs/deployment/secrets-and-encryption.md`.
- **Verification:** Executed restore test log confirming row counts and successful `decrypt_credentials` check on a temporary branch.

### 15. Privacy and Compliance
- **Current Implementation:** Strict tenant separation, audit trail of mutations/logins (`AuditLog`), log/audit secret redaction, no real customer payment keys (`rzp_live_*` blocked).
- **Evidence:** `backend/app/services/audit_service.py`, `backend/app/connectors/razorpay.py`, `backend/app/models/`.
- **Current Status:** `Missing`
- **Risk Severity:** `High` *(P0 before accepting real external customers/PII)*
- **What Is Missing:**
  - No Privacy Policy or Terms of Service pages or links in `AuthPage` / footer.
  - No GDPR/CPRA user/organization self-serve data export or deletion (`DELETE /me`, `DELETE /orgs/{org_id}`).
  - No automated retention policy / TTL cleanup for `audit_logs`, `events`, `webhook_deliveries`, or expired `api_keys`.
  - Customer PII (`actor` emails from Razorpay) can be forwarded to third-party DeepSeek prompts inside Copilot tool results.
- **Recommended Action:** Publish Privacy Policy & Terms of Service before public signups, build workspace/account deletion + retention cleanup jobs, and anonymize PII passed to external LLM APIs.
- **Files to Modify:** `backend/app/routers/{me,members}.py`, `backend/app/ai/tool_registry.py`, `frontend/src/pages/AuthPage.tsx`.
- **Verification:** Deletion & retention tests confirming cascading removal and LLM payload PII scrubbing.

### 16. Deployment and CI/CD
- **Current Implementation:** `.github/workflows/ci.yml` runs on push/PR to `main`: Postgres 16 & Redis 7 services, full-history `gitleaks`, `ruff check .`, `alembic upgrade head` on `pulseops` and `pulseops_test`, full `pytest -v`, `npm ci`, `npm test`, and `npm run build` (`tsc -b && vite build`). `render.yaml` & `frontend/vercel.json` manage CD. Production Neon database is verified at Alembic revision `9c4a12e8f3b1`, `events.is_synthetic` and `events.minor_unit_exponent` columns are confirmed, and Dashboard metrics & app operation were confirmed post-migration.
- **Evidence:** `.github/workflows/ci.yml`, `render.yaml`, `frontend/vercel.json`, `backend/Dockerfile`.
- **Current Status:** `Verified` (workflow config & production DB migration `9c4a12e8f3b1`).
- **Risk Severity:** `Low`
- **What Is Missing:**
  - Automatic migration step before Render deploy for *future* schema changes (free tier lacks `preDeployCommand`).
  - Upper-bound version pinning in `backend/requirements.txt` (e.g. `fastapi`, `alembic`, `httpx` lack `<major` caps) risking unexpected upstream changes across rebuilds.
- **Recommended Action:** Pin tested Python dependency ranges (`requirements.lock` / constrained upper bounds) and enable `preDeployCommand` if moving to a paid Render plan.
- **Files to Modify:** `backend/requirements.txt`, `render.yaml`.
- **Verification:** GitHub Actions run green on `main` + `python scripts/smoke_test.py --base-url https://pulseops-api-8cp9.onrender.com`.

### 17. Testing Coverage
- **Current Implementation:**
  - **Executed During `v1.3` Code Verification:** `202` backend `pytest` tests passed (`44.50s` across `18` files against PostgreSQL `pulseops_test` with transaction rollback), `11` frontend `vitest` tests passed (`3` files), `tsc -b && vite build` passed, `npm audit --omit=dev` reported `0` vulnerabilities, and `pip check` succeeded. *(External HTTP calls for Razorpay, GitHub, and DeepSeek were tested via mocks, not live third-party endpoints.)*
  - **Executed During This Documentation Pass:** `pytest --collect-only -q` collected `202` backend tests (without re-executing the full DB suite since zero code changed), `gitleaks detect` scanned `18` commits (`0` leaks), `openapi()` schema verification confirmed `32` routes, and doc link/path checks executed cleanly.
- **Evidence:** `backend/tests/`, `frontend/src/lib/__tests__/`, `PROGRESS.md` (`v1.3` recorded test run), documentation validation checks.
- **Current Status:** `Verified` (unit/API & mocked connector suites) / `Partially verified` (frontend UI/E2E & live external integration connectivity).
- **Risk Severity:** `Medium`
- **What Is Missing:**
  - React component unit tests for page states (`DashboardPage`, `CopilotPage`, `IntegrationsPage`, `EventsPage`, `TeamPage`).
  - Automated Playwright E2E browser suite exercising real login -> multi-currency dashboard -> Copilot proposal approval -> CSV upload against live stack.
  - Local `ruff` CLI installation in developer `.venv` (`ruff check` currently executes cleanly only in CI).
- **Recommended Action:** Add React Testing Library page tests + headless Playwright smoke E2E job in CI and include `ruff` in dev dependencies.
- **Files to Modify:** `frontend/src/pages/__tests__/`, `.github/workflows/ci.yml`, `backend/requirements-dev.txt`.
- **Verification:** All unit, component, and Playwright E2E suites green in CI.

### 18. Cost Management
- **Current Implementation:** Zero-cost free tiers (Vercel Hobby, Render Free Web with worker commented out, Neon free, Upstash free); Razorpay Test Mode & mock fallback (`rzp_live_*` rejected); DeepSeek disabled when key unset (`deterministic-fallback`) + capped `max_tokens=800`, `max_tool_rounds=3`, Redis response caching (`120s`), and demo viewer `5/day` Copilot limit.
- **Evidence:** `render.yaml`, `backend/app/config.py`, `backend/app/core/rate_limit.py`, `backend/app/connectors/razorpay.py`.
- **Current Status:** `Verified`
- **Risk Severity:** `Low`
- **What Is Missing:** Global daily/monthly DeepSeek token budget alarm or tenant-level LLM quota across normal (non-demo) users if many customers query Copilot simultaneously.
- **Recommended Action:** Add per-organization daily/monthly DeepSeek token usage tracking (`AuditLog` or Redis counter) and billing/budget alerts on DeepSeek Platform before opening public signups.
- **Files to Modify:** `backend/app/core/rate_limit.py`, `backend/app/ai/deepseek_client.py`.
- **Verification:** `pytest` token-budget tests + DeepSeek usage header logging verification.

---

## Prioritized Remediation Roadmap

### P0 — Must Fix Before Accepting Real Customers
*(Note: Production Neon Alembic migration `9c4a12e8f3b1` is already verified complete and is not a P0 blocker.)*
1. **Enforce Browser Security Headers & CSP:** Add `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and `Referrer-Policy` headers in `frontend/vercel.json` / backend middleware to protect `localStorage` JWTs against XSS token theft. *(Files: `frontend/vercel.json`, `backend/app/main.py`)*
2. **Add Account Lifecycle & Token Revocation Controls:** Implement refresh/revocation mechanism (`token_version` or `HttpOnly` cookie sessions), password change/reset, email verification, and org/user self-serve deletion (`DELETE /me`, `DELETE /orgs/{org_id}`) so compromised sessions can be invalidated and customers control account access. *(Files: `backend/app/models/user.py`, `backend/app/core/auth.py`, `backend/app/routers/{auth,me}.py`)*
3. **Publish Legal & Privacy Disclosures + Anonymize PII in External AI Prompts:** Add Terms/Privacy links to `AuthPage` and scrub customer emails (`actor`) before sending event payloads to DeepSeek API. *(Files: `frontend/src/pages/AuthPage.tsx`, `backend/app/ai/tool_registry.py`)*
4. **Live Billing Connector Policy (`rzp_live_*` Guard):** `RazorpayConnector` strictly rejects `rzp_live_*` credentials by design; real paying customers expecting live Razorpay account ingestion cannot onboard until a dedicated audited live-mode policy replaces Test/Mock enforcement. *(Files: `backend/app/connectors/razorpay.py`)*

### P1 — Required for Dependable Production Operations
1. **Upgrade Hosting Off Sleepy Free Tier & Enable Worker (Known Infra Limitation):** Move Render API to always-on Starter plan (eliminating 30–50s cold starts), enable `pulseops-worker` in `render.yaml`, and add `preDeployCommand: alembic upgrade head`.
2. **Configure External Monitoring & Restrict `/metrics`:** Add uptime checks + failure alerts on `/readiness` and 5xx rates, centralize log retention, and protect `/metrics` with bearer/scraper auth. *(Files: `backend/app/main.py`)*
3. **Implement `MultiFernet` Key Rotation & Test Backup Recovery:** Support dual-key `INTEGRATION_ENCRYPTION_KEY` rotation cleanly in `backend/app/core/security.py` and verify a full Neon branch / `pg_dump` restore drill including credential decryption.
4. **Fix Integration Pagination Truncation & Upstream Retries:** Add cursor continuation or explicit `truncated` warning in `SyncRun` when Razorpay (`>500`) or GitHub (`>1,000`) items exceed 10 pages, and add bounded retry on upstream `429`/`5xx`. *(Files: `backend/app/connectors/{razorpay,github}.py`, `backend/app/services/integration_service.py`)*

### P2 — Important for Scaling
1. **Push Metrics Aggregations to PostgreSQL SQL:** Replace in-memory event scans in `backend/app/services/metrics_service.py` with SQL `GROUP BY` / `date_trunc` queries and time-windowed open-issue snapshots.
2. **Add Frontend Test Suite & Playwright E2E:** Cover all 5 workspace pages with component tests and automated full-stack E2E tests in `.github/workflows/ci.yml`.
3. **Pin Deterministic Dependencies & Add Shared Async Redis Pool:** Pin exact tested Python packages, pool SSE `redis.asyncio` connections (`realtime_service.py`), and enforce fallback/alerting when Redis rate limiting degrades.
4. **Data Retention Jobs:** Add ARQ/scheduled cleanup for aged `webhook_deliveries` and expired `api_keys`.

### P3 — Future Enhancements & Product Limitations
1. **Multi-Currency Consolidated Analytics / FX Conversion (Outstanding Product Limitation):** Currencies remain isolated per `by_currency` (`fx_conversion_applied=false`); add optional historical FX snapshot rates so multi-currency SaaS teams can view consolidated single-currency executive totals alongside native currency metrics.
2. **Expose Unwired Backend Capabilities in Frontend:** Add UI management panels for `/me/api-keys`, `/orgs/{org_id}/audit-logs`, GitHub OAuth callback route (`/integrations/github/callback`), Copilot SSE token streaming, and live SSE dashboard event updates.
3. **Multi-Workspace & Member Administration UI:** Add `POST /orgs` post-login workspace creation plus member role-edit and removal endpoints (`TeamPage`).
4. **Persisted Copilot Conversations & PostgreSQL RLS:** Store chat sessions in Postgres across reloads and add DB-level Row-Level Security policies as tenant defense-in-depth.
