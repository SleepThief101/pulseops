# Worker Operations, Monitoring, and Recovery Runbook

This runbook documents operating, monitoring, and recovering the PulseOps **Redis 7 + ARQ** background worker, PostgreSQL migrations, SSE/rate-limit Redis dependencies, and Prometheus/readiness endpoints.

---

## 1. Background Worker Architecture (`app.worker.WorkerSettings`)

- **Entrypoint:** `arq app.worker.WorkerSettings` (defined in [`backend/app/worker.py`](../../backend/app/worker.py))
- **Job Function:** `sync_integration_job(ctx, org_id, integration_id, sync_run_id=None, full_sync=False)`
- **Retry Policy:** `max_tries = 3`, exponential/linear defer `job_try * 5` seconds (`5s`, `10s`) on transient exceptions
- **Job Timeout:** `job_timeout = 120` seconds
- **Health Check Interval:** `health_check_interval = 15` seconds
- **Audit Trail:** Every job updates a tenant-scoped `SyncRun` row (`pending` -> `running` -> `completed` or `failed`) with `events_received`, `events_inserted`, `events_skipped`, `error_message`, `started_at`, and `finished_at`.

---

## 2. Starting & Checking Worker Health

### Local Docker Compose
```bash
docker compose up -d --build api worker db redis
docker exec pulseops-worker arq app.worker.WorkerSettings --check
```
Expected exit code `0` and `"Health check successful"`.

### Production (Render Optional Worker + Upstash Redis)
1. Ensure `REDIS_URL` uses TLS (`rediss://default:<password>@<host>:6379`).
2. `WorkerSettings.get_redis_settings()` parses `rediss://` automatically via `RedisSettings.from_dsn`.
3. On Render free-tier deployments where background workers are disabled in [`render.yaml`](../../render.yaml) to control costs, keep `POST /orgs/{org_id}/integrations/{id}/sync` in default synchronous mode (`background=false`).

---

## 3. Monitoring & Readiness Endpoints (S36)

| Endpoint | Purpose | Expected Healthy Output |
| :--- | :--- | :--- |
| `GET /health` | API + PostgreSQL liveness (`render.yaml` health check) | `200 {"status": "ok"}` |
| `GET /readiness` | Full dependency readiness (PostgreSQL `SELECT 1` + Redis `PING`) | `200 {"status": "ready", "checks": {"database": "ok", "redis": "ok"}}` |
| `GET /metrics` | Prometheus text exposition (`pulseops_http_requests_total`, `pulseops_http_request_duration_seconds`, `pulseops_events_ingested_total`, `pulseops_rate_limit_hits_total`) | `200 text/plain; version=0.0.4` |

---

## 4. Database Migration Operations

1. **Apply Migrations Safely:**
   ```bash
   cd backend
   alembic upgrade head
   alembic current
   ```
2. **Neon Direct vs. Pooled:** Always run `alembic upgrade head` against Neon's **direct** (non-pooler) endpoint to avoid PgBouncer DDL locking issues.
3. **Never Run Against Production:** Keep `TEST_DATABASE_URL` strictly separate from `DATABASE_URL`.
4. **Creating New Migrations:**
   ```bash
   docker exec pulseops-api alembic revision --autogenerate -m "describe_change"
   ```
   Inspect the generated file under `backend/alembic/versions/` before applying it to both `DATABASE_URL` and `TEST_DATABASE_URL`.

---

## 5. Worker Recovery Procedures

### Symptom: Jobs stay in `pending`
- **Verify worker process:** `docker exec pulseops-worker arq app.worker.WorkerSettings --check`
- **Verify Redis connectivity:** `GET /readiness` should show `"redis": "ok"`.
- **Action:** Restart the worker container (`docker compose restart worker`) or check Upstash command quota / TLS scheme (`rediss://`).

### Symptom: `SyncRun` stuck in `failed` after 3 retries
- **Inspect error details:** Call `GET /orgs/{org_id}/sync-runs` to read `error_message`, and inspect structured JSON logs in `pulseops-worker` (`docker logs pulseops-worker --tail 100`).
- **Common causes:** Expired/revoked provider token (`401`/`403` from Razorpay/GitHub), wrong `webhook_secret`, or network outage.
- **Recovery:** Reconnect/update the integration credentials and trigger a clean backfill:
  ```text
  POST /orgs/{org_id}/integrations/{integration_id}/sync?full_sync=true&background=true
  ```
- **Idempotency guarantee:** Re-running `full_sync=true` is safe; PostgreSQL `ON CONFLICT DO NOTHING` on `uq_events_org_source_external_id` skips previously ingested events without duplicating metrics.

### Symptom: Rate limits (`429`) or stale Copilot responses
- Rate-limit keys use `pulseops:ratelimit:*` with automatic TTL expiry (`RATE_LIMIT_WINDOW_SECONDS`, default `60s`). Responses include `Retry-After`.
- Copilot read cache auto-invalidates via `pulseops:copilot:version:{org_id}` whenever new events are ingested (`POST /sync`, `/imports/csv`, or webhooks) and expires after `COPILOT_CACHE_TTL_SECONDS` (default `120s`).
