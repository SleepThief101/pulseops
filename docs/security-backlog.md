# Security Hardening Status & Remaining Open Items

Phase 3 Security Hardening resolved the critical/high items identified during prior audits. Remaining low/medium operational enhancements are documented transparently below.

---

## 1. Remediated in Phase 3

1. **MCP Per-User Hashed API Keys & Tenant Authorization (`backend/app/mcp_server.py`, `backend/app/models/api_key.py`, `backend/app/services/api_key_service.py`, `backend/app/routers/me.py`):**
   - Added per-user SHA-256 hashed `api_keys` (`pmcp_...`) with `POST /me/api-keys` (plaintext returned once), `GET /me/api-keys` (metadata only), and `DELETE /me/api-keys/{key_id}` revocation with strict owner isolation (`404`).
   - Every MCP tool requires an active, non-revoked, non-expired per-user API key, resolves `Membership` in PostgreSQL, enforces `tool.min_role`, blocks mutating tools, and runs strictly over local `stdio` transport (network HTTP/SSE/Streamable HTTP transports remain disabled).
2. **AI Tool Argument Validation & RBAC (`backend/app/ai/tool_registry.py`, `backend/app/services/copilot_service.py`, `backend/app/routers/copilot.py`):**
   - Added strict Pydantic `extra="forbid"` parameter schemas on every tool, explicit rejection of reserved execution context keys (`db`, `organization_id`, `user_id`, `membership`, `role`, `caller_role`), and centralized `execute_tool_safely(...)`.
   - Enforced tool-level `min_role` before execution or `ActionProposal` persistence (preventing `viewer` accounts from creating sync proposals and `member` accounts from proposing `owner`-only disconnects), plus re-validation at `/decision` execution time.
3. **Webhook Replay & Delivery Deduplication (`backend/app/services/webhook_service.py`, `backend/app/models/webhook_delivery.py`, `backend/app/routers/webhooks.py`):**
   - Enforced replay timestamp windows (`WEBHOOK_REPLAY_TOLERANCE_SECONDS=300`, `WEBHOOK_FUTURE_SKEW_SECONDS=60`) on Razorpay `created_at` and optional `X-Webhook-Timestamp` headers.
   - Added persisted `webhook_deliveries` deduplication (`uq_webhook_deliveries_org_provider_delivery`) for `X-Razorpay-Event-Id` and `X-GitHub-Delivery` returning `409 Conflict` on replayed/duplicate deliveries, strictly verified *after* constant-time HMAC-SHA256 validation.
4. **Auth, Logging, AuditLog & Rate-Limit Hardening (`backend/app/core/auth.py`, `backend/app/core/logging.py`, `backend/app/services/audit_service.py`, `backend/app/routers/auth.py`):**
   - Enforced required JWT claims (`sub`, `exp`, `iat`), expanded log sanitization (`pmcp_`, `rzp_`, `ghp_`, `sk-`, nested dict extras), added recursive `AuditLog` detail redaction, recorded `auth.login_failed`, and added normalized-email rate limiting alongside IP throttling.

---

## 2. Open / Accepted Items (Severity & Rationale)

1. **[MEDIUM] Zero-Downtime Encryption Key Rotation (`MultiFernet` in `backend/app/core/security.py`):**
   - Single-key `Fernet` is active; swapping `INTEGRATION_ENCRYPTION_KEY` requires running the maintenance re-encryption runbook in [`docs/deployment/secrets-and-encryption.md`](./deployment/secrets-and-encryption.md) until `MultiFernet` dual-key support is added.
2. **[LOW] Network MCP Transports (`sse` / `streamable-http`):**
   - Intentionally not enabled (`mcp_server.py` runs `stdio` only). Enabling remote MCP in the future requires wiring HTTP `Authorization: Bearer` middleware to `api_key_service.authenticate_api_key`.
3. **[LOW] GitHub Webhooks Without `X-Webhook-Timestamp` Header:**
   - GitHub's native webhook protocol signs payload bytes + `X-Hub-Signature-256` and provides unique `X-GitHub-Delivery` UUIDs rather than a mandatory envelope epoch header. Replay protection enforces `X-Webhook-Timestamp` when present and `X-GitHub-Delivery` uniqueness via `webhook_deliveries`.
4. **[LOW] `rate_limit` Fail-Open Behavior on Redis Outage (`backend/app/core/rate_limit.py`):**
   - If Redis becomes unreachable, rate limiting fails open with a warning log to avoid locking out legitimate logins; `/readiness` explicitly surfaces Redis unavailability (`503`).
