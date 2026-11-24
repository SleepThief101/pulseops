# Structured Logging and Request IDs

PulseOps uses structured JSON logging with asynchronous request context tracking to ensure observable, audit-ready, and secure operation across all services and endpoints.

---

## Architecture Overview

Structured logging in PulseOps provides:
1. **Single-line JSON Output**: Standardized log format compatible with modern log collectors (Datadog, CloudWatch, Google Cloud Logging, ELK).
2. **Deterministic Request Tracking**: Unique UUID request identifiers generated for every HTTP transaction and carried across the application stack.
3. **Context Variable Propagation**: `contextvars` store the active `request_id`, `user_id`, and `org_id` so any log call inside the call tree inherits request metadata without manual parameter threading.
4. **Zero-Secret Leakage Guarantee**: Automatic redaction of database passwords, Bearer tokens, JWTs, and credential payloads from all log records and exception stack traces.

---

## Log Format and Fields

Every log event formatted by `StructuredJsonFormatter` outputs a single JSON line containing:

| Field | Type | Description | Example |
| :--- | :--- | :--- | :--- |
| `timestamp` | string (ISO-8601 UTC) | Exact UTC timestamp with millisecond resolution ending in `Z`. | `"2026-11-24T15:45:00.123Z"` |
| `level` | string | Log level severity (`INFO`, `WARNING`, `ERROR`, `DEBUG`). | `"INFO"` |
| `log_level` | string | Alias for `level` for wide aggregator compatibility. | `"INFO"` |
| `logger` | string | Emitting Python logger name. | `"app.request"` |
| `message` | string | Sanitized log message text. | `"GET /health 200 (1.24ms)"` |
| `request_id` | string \| null | Canonical UUID identifier of the active HTTP request. | `"550e8400-e29b-41d4-a716-446655440000"` |
| `http_method` | string (optional) | HTTP verb (`GET`, `POST`, `PUT`, `DELETE`). | `"GET"` |
| `path` | string (optional) | HTTP request path. | `"/orgs/055131af-faa1-49aa-9898-98377797f9d5/members"` |
| `status_code` | integer (optional) | HTTP response status code. | `200` |
| `duration_ms` | float (optional) | Request execution duration in milliseconds. | `18.42` |
| `user_id` | string (optional) | Authenticated user UUID when available. | `"d8ecf070-860d-4ff3-83f2-fbc4dc6c274e"` |
| `org_id` | string (optional) | Associated organization UUID when available. | `"055131af-faa1-49aa-9898-98377797f9d5"` |
| `exception` | string (optional) | Sanitized traceback string when an exception occurs. | `"Traceback (most recent call last)..."` |

### Example Log Output

```json
{"timestamp": "2026-11-24T15:45:00.123Z", "level": "INFO", "log_level": "INFO", "logger": "app.request", "message": "GET /me 200 (12.45ms)", "request_id": "550e8400-e29b-41d4-a716-446655440000", "http_method": "GET", "path": "/me", "status_code": 200, "duration_ms": 12.45, "user_id": "d8ecf070-860d-4ff3-83f2-fbc4dc6c274e"}
```

---

## Request ID Middleware

`RequestLoggingMiddleware` manages request lifecycle and ID propagation:

1. **Incoming Header Inspection**:
   - The middleware inspects the incoming `X-Request-ID` header.
   - If present, it validates that the value is a valid, canonical UUID string.
   - **Security Rule**: Arbitrary client-provided strings, SQL fragments, script tags, or newline injection attempts are strictly rejected and replaced with a newly generated `uuid.uuid4()`.
2. **Context Binding**:
   - The validated request ID is bound to `request.state.request_id` and the async context variable `_request_id_ctx`.
   - Any log call made inside route handlers, dependencies, or services automatically inherits this ID.
3. **Response Header**:
   - The validated request ID is returned in the `X-Request-ID` HTTP response header for client correlation.

---

## Security and Secret Redaction

1. **No Sensitive Request Bodies**:
   - The logging middleware never reads, parses, or logs HTTP request bodies. Endpoint payloads containing plain-text passwords or secret keys are completely excluded from log output.
2. **No Sensitive Headers**:
   - `Authorization`, `Cookie`, and `X-API-Key` headers are never logged.
3. **Automatic Content Sanitization (`sanitize_log_message`)**:
   - All log messages and exception tracebacks pass through `sanitize_log_message`:
     - Database connection strings (`postgresql://user:password@host`) are redacted to `postgresql://user:***@host`.
     - Bearer tokens (`Bearer eyJ...`) are redacted to `Bearer [REDACTED]`.
     - Raw JWT tokens are replaced with `[REDACTED_JWT]`.
     - Key-value credentials (`password=...`, `jwt_secret_key=...`) are redacted to `[REDACTED]`.

---

## Exception Handling and Resilience

If an unhandled exception occurs during request execution:
- The exception is safely caught by `RequestLoggingMiddleware`.
- An error log is emitted with `level: "ERROR"`, sanitized exception details, and the active `request_id`.
- The client receives a clean HTTP 500 JSON response:
  ```json
  {"detail": "Internal server error"}
  ```
  with the `X-Request-ID` response header preserved, ensuring client-facing errors can be cited and correlated in logs.
