# Authentication

PulseOps uses stateless JWT authentication backed by Argon2id password hashing.

## Registration

**Endpoint:** `POST /auth/register`

Creates a new user, a new organization, and an owner membership in a single atomic transaction.

**Request body:**
```json
{
  "email": "alice@example.com",
  "password": "StrongPassword1!",
  "organization_name": "Alice's Team"
}
```

**Validation rules:**
- `email` — valid RFC-5321 email address; stored and compared case-insensitively
- `password` — 8–128 characters
- `organization_name` — 1–255 characters (whitespace-only is rejected)

**Success (201):**
```json
{
  "user_id": "...",
  "email": "alice@example.com",
  "created_at": "2024-01-01T00:00:00Z",
  "organization_id": "...",
  "organization_name": "Alice's Team",
  "role": "owner"
}
```

**Errors:**
- `409 Conflict` — email is already registered
- `422 Unprocessable Entity` — validation failure

> [!IMPORTANT]
> `password_hash` is never returned in any response body.

---

## Login

**Endpoint:** `POST /auth/login`

Verifies credentials and returns a signed JWT.

**Request body:**
```json
{
  "email": "alice@example.com",
  "password": "StrongPassword1!"
}
```

**Success (200):**
```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "expires_in": 3600
}
```

**Errors:**
- `401 Unauthorized` — wrong email or password (identical message for both to prevent user enumeration)

---

## Authenticated requests

Include the JWT as a Bearer token in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

---

## Current user profile

**Endpoint:** `GET /me`

Returns the authenticated user's profile.

**Success (200):**
```json
{
  "id": "...",
  "email": "alice@example.com",
  "created_at": "2024-01-01T00:00:00Z"
}
```

**Errors:**
- `401 Unauthorized` — missing, invalid, or expired Bearer token

---

## JWT structure

| Claim | Value |
|-------|-------|
| `sub` | User UUID (string) |
| `iat` | Issued-at timestamp (UTC) |
| `exp` | Expiry timestamp (`iat + 3600 s`) |

- **Algorithm:** HS256
- **Expiry:** 1 hour
- **Library:** PyJWT 2.x

---

## Password hashing

Passwords are hashed with **Argon2id** using the `pwdlib[argon2]` library. Argon2id is the OWASP-recommended password hashing algorithm, resistant to both side-channel and GPU attacks.

---

## Configuration

| Environment variable | Required | Description |
|---------------------|----------|-------------|
| `JWT_SECRET_KEY`     | **Yes**  | HMAC signing secret. Must be a long random string. |

Generate a secret:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

> [!CAUTION]
> Never hardcode `JWT_SECRET_KEY`. Never commit it to version control. Never share it across environments.

Add to `.env`:
```
JWT_SECRET_KEY=<output of the command above>
```

---

## Security considerations

- Passwords are compared using Argon2id's constant-time verify function to prevent timing attacks.
- Login returns the same 401 message for wrong email and wrong password to prevent user enumeration.
- The `password_hash` field is never serialized in any API response.
- JWTs are short-lived (1 hour). There is no refresh-token mechanism at this stage.
- `JWT_SECRET_KEY` must be set; the application fails closed (raises `RuntimeError`) if the key is absent or empty.
