# Database Architecture & Core Models

This document details the core database architecture, models, constraints, and migration procedures for **PulseOps**.

---

## 1. Core Models

PulseOps is an AI-native control tower for small SaaS teams. All operational data is multi-tenant and strictly partitioned by Organization.

### A. Organization (`organizations`)

Represents a tenant in PulseOps.

| Column | Type | Constraints / Defaults | Description |
|---|---|---|---|
| `id` | `UUID` | Primary Key, `uuid.uuid4` | Unique organization identifier |
| `name` | `VARCHAR(255)` | Not Null | Display name of the organization |
| `created_at` | `TIMESTAMPTZ` | Not Null, Server Default `now()` | Timezone-aware creation timestamp |

**Relationships:**
- `memberships`: One-to-many relationship with `Membership`. Deleting an organization cascades to delete all associated memberships (`ON DELETE CASCADE`).
- `integrations`: One-to-many relationship with `Integration`. Deleting an organization cascades to delete all associated integrations (`ON DELETE CASCADE`).

---

### B. User (`users`)

Represents an individual principal who can access one or more organizations.

| Column | Type | Constraints / Defaults | Description |
|---|---|---|---|
| `id` | `UUID` | Primary Key, `uuid.uuid4` | Unique user identifier |
| `email` | `VARCHAR(255)` | Not Null, Unique, Indexed | User email address |
| `password_hash` | `VARCHAR(255)` | Not Null | Hashed password (never plaintext) |
| `created_at` | `TIMESTAMPTZ` | Not Null, Server Default `now()` | Timezone-aware creation timestamp |

**Invariants & Constraints:**
- **Case-Insensitive Email Uniqueness:** In addition to a unique constraint on `email`, the table defines a functional unique index: `ix_users_email_lower` on `lower(email::text)`. Furthermore, the SQLAlchemy model normalizes email inputs to lowercase before persistence.
- **Cascade Deletion:** Deleting a user cascades to remove all their memberships across organizations (`ON DELETE CASCADE`).

---

### C. Membership (`memberships`)

Associates a `User` with an `Organization` and assigns an authorization role.

| Column | Type | Constraints / Defaults | Description |
|---|---|---|---|
| `id` | `UUID` | Primary Key, `uuid.uuid4` | Unique membership identifier |
| `user_id` | `UUID` | Not Null, Foreign Key `users.id` (`CASCADE`), Indexed | Reference to user |
| `organization_id` | `UUID` | Not Null, Foreign Key `organizations.id` (`CASCADE`), Indexed | Reference to organization |
| `role` | `VARCHAR(50)` | Not Null, Default `member` | Role in organization |
| `created_at` | `TIMESTAMPTZ` | Not Null, Server Default `now()` | Timezone-aware creation timestamp |

**Invariants & Constraints:**
- **Single Membership per User-Org Pair:** Enforced by unique constraint `uq_memberships_user_org` on `(user_id, organization_id)`.
- **Database-Level Role Validation:** Enforced by check constraint `ck_memberships_role`: `CHECK (role IN ('owner', 'member', 'viewer'))`.

---

### D. Integration (`integrations`)

Stores external integration settings (e.g. GitHub, Razorpay, or future providers) and encrypted credentials belonging to an organization.

| Column | Type | Constraints / Defaults | Description |
|---|---|---|---|
| `id` | `UUID` | Primary Key, `uuid.uuid4` | Unique integration identifier |
| `organization_id` | `UUID` | Not Null, Foreign Key `organizations.id` (`CASCADE`), Indexed | Reference to owner organization |
| `provider` | `VARCHAR(50)` | Not Null | Provider identifier (e.g. `github`, `razorpay`) |
| `status` | `VARCHAR(50)` | Not Null, Default `pending` | Current integration lifecycle state |
| `credentials_encrypted` | `TEXT` | Not Null | Fernet ciphertext of credentials |
| `last_synced_at` | `TIMESTAMPTZ` | Nullable | Last successful data synchronization |
| `created_at` | `TIMESTAMPTZ` | Not Null, Server Default `now()` | Timezone-aware creation timestamp |

**Invariants & Constraints:**
- **Multi-Tenant Scoping:** Every integration is strictly bound to an `organization_id`.
- **Compound Index:** `ix_integrations_org_provider` on `(organization_id, provider)` accelerates provider lookups per tenant.
- **Status Check Constraint:** Enforced by `ck_integrations_status`: `CHECK (status IN ('active', 'inactive', 'pending', 'error', 'disconnected'))`.
- **Extensible Providers:** Provider is stored as a string to accommodate future third-party integrations without schema migrations.
- **Credential Safety:** Credentials must never be stored in plaintext. They are encrypted at the application level before being written to `credentials_encrypted`.

---

## 2. Integration Credential Encryption

Integration credentials (tokens, secrets, API keys) are encrypted and decrypted using authenticated symmetric encryption via `cryptography.fernet.Fernet`.

### Configuration

The encryption key is read from the `INTEGRATION_ENCRYPTION_KEY` environment variable via Pydantic Settings (`app.config.settings`).

- Never hardcode the encryption key.
- Never commit `.env` containing keys.
- Encryption/decryption fails safely with `EncryptionConfigurationError` if the key is missing or malformed (it never silently falls back to plaintext).

### Generating a Key Locally

Run the following command in Python to generate a fresh Fernet key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Add the resulting key to your local `.env`:

```env
INTEGRATION_ENCRYPTION_KEY=<generated_base64_fernet_key>
```

---

## 3. Database Migrations with Alembic

Alembic manages all database schema migrations. The migration environment is located in `backend/alembic/`.

### Migration Commands

Run migrations using the Docker Compose environment:

```bash
# Apply all pending migrations
docker exec pulseops-api alembic upgrade head

# Inspect current revision
docker exec pulseops-api alembic current

# Generate a new autogenerated migration after model changes
docker exec pulseops-api alembic revision --autogenerate -m "description_of_change"
```

Or from the local backend directory (with access to PostgreSQL):

```bash
cd backend
alembic upgrade head
```

### Initial Migration

- **Revision ID:** `b8066bd7d2cb`
- **Description:** `create core tables`
- **Created Tables:** `organizations`, `users`, `memberships`, `integrations`

---

## 4. Test Database Isolation & Setup

To protect development and production environments from test pollution or destructive actions, all tests that require database access are strictly isolated to a dedicated test database (`pulseops_test`).

### Isolation Architecture

1. **Explicit Configuration (`TEST_DATABASE_URL`):**
   - The test suite requires `TEST_DATABASE_URL` to be explicitly provided.
   - It **never** silently falls back to `DATABASE_URL`.
   - If `TEST_DATABASE_URL` is missing, or if it accidentally matches `DATABASE_URL`, the test suite fails immediately with a descriptive `RuntimeError`.
2. **Dedicated Test Engine:**
   - Pytest fixtures instantiate an isolated `test_engine` and `TestSessionLocal` bound exclusively to `TEST_DATABASE_URL`.
   - The application's runtime engine (`app.db.session.engine`) is never used for test data writes or Alembic schema inspection.
3. **Transaction Rollback:**
   - Every test using `db_session` executes inside an uncommitted database transaction.
   - A `try ... finally` block guarantees that the transaction is rolled back upon test completion, even if the test fails or raises an error.

### Local Setup Instructions

#### Step 1: Create the Test Database

In your local PostgreSQL container (or native instance), create the `pulseops_test` database:

```bash
docker exec pulseops-db psql -U pulseops -d pulseops -c "CREATE DATABASE pulseops_test;"
```

#### Step 2: Configure Environment Variables

Add `TEST_DATABASE_URL` to your local `.env`:

```env
TEST_DATABASE_URL=postgresql+psycopg://pulseops:change_this_local_password@db:5432/pulseops_test
```

#### Step 3: Apply Migrations to the Test Database

Run Alembic against the dedicated test database to prepare the schema:

```bash
docker exec -e DATABASE_URL=postgresql+psycopg://pulseops:change_this_local_password@db:5432/pulseops_test pulseops-api alembic upgrade head
```

#### Step 4: Run the Test Suite

Execute pytest:

```bash
# Inside Docker
docker exec -e TEST_DATABASE_URL=postgresql+psycopg://pulseops:change_this_local_password@db:5432/pulseops_test pulseops-api pytest -v

# Or on host (with localhost port forwarding):
# $env:TEST_DATABASE_URL="postgresql+psycopg://pulseops:change_this_local_password@localhost:5432/pulseops_test"
# pytest -v
```

