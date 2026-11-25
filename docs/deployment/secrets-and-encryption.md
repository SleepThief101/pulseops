# Encryption and Secret Management Runbook

PulseOps relies on two distinct, fail-closed cryptographic secrets in production:
1. **`JWT_SECRET_KEY`** (`backend/app/core/auth.py`): HS256 HMAC secret signing short-lived (1-hour) user authentication tokens.
2. **`INTEGRATION_ENCRYPTION_KEY`** (`backend/app/core/security.py`): Fernet symmetric key (AES-128-CBC + HMAC-SHA256) encrypting tenant API tokens and webhook secrets stored in `integrations.credentials_encrypted`.

> [!CAUTION]
> **Never generate or store real production secrets inside Git, `.env.example`, CI workflow YAML, or chat logs.** Generate production secrets only in a secure local terminal immediately before pasting them into Render.

---

## 1. Generating Production Keys

Generate **two separate keys** using Python's standard `secrets` and `cryptography.fernet` modules:

### A. JWT Signing Key (`JWT_SECRET_KEY`)

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

- Output: 64-character hexadecimal string (256 bits of cryptographic entropy).
- Minimum enforced length in production (`validate_production_settings`): 32 characters.

### B. Integration Encryption Key (`INTEGRATION_ENCRYPTION_KEY`)

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

- Output: 44-character URL-safe base64-encoded 32-byte key.
- Tested directly by `Fernet(...)` on startup in production; malformed keys fail fast.

---

## 2. Keeping Keys Separate

- **Mandatory Separation:** `JWT_SECRET_KEY` and `INTEGRATION_ENCRYPTION_KEY` must NEVER share the same value. `backend/app/config.py` (`validate_production_settings`) explicitly rejects identical keys in production.
- **Environment Isolation:** Never reuse local development or CI keys in production. Each environment (Local, CI, Production) must have distinct keys so compromising local dev data cannot forge production JWTs or decrypt production integration credentials.

---

## 3. Storing Keys in Render

1. Open **Render Dashboard -> `pulseops-api` -> Environment**.
2. Click **Add Environment Variable**:
   - Key: `JWT_SECRET_KEY` -> Paste generated 64-char hex value.
   - Key: `INTEGRATION_ENCRYPTION_KEY` -> Paste generated 44-char base64 Fernet value.
3. Click **Save Changes**. Render encrypts environment variables at rest and injects them only into the runtime container/process.
4. Confirm `ENVIRONMENT=production` is also set so startup validation verifies both keys automatically before accepting traffic.

---

## 4. Backing Up `INTEGRATION_ENCRYPTION_KEY` Securely

Unlike `JWT_SECRET_KEY` (where users can simply log in again after rotation), **`INTEGRATION_ENCRYPTION_KEY` protects persistent ciphertext in PostgreSQL (`integrations.credentials_encrypted`)**.

- Store a copy of `INTEGRATION_ENCRYPTION_KEY` (labeled clearly with the service name, environment, and creation date) in an encrypted enterprise password manager or offline secret vault (e.g., 1Password, Bitwarden Vault, AWS Secrets Manager).
- **Never** store `INTEGRATION_ENCRYPTION_KEY` inside the same Neon PostgreSQL database or database backup archive. Storing key and ciphertext together defeats encryption at rest.

---

## 5. Recovering from Accidental Key Loss

If `INTEGRATION_ENCRYPTION_KEY` is lost and no vault backup exists:

1. **Expectation:** Fernet uses authenticated AES-128-CBC + HMAC-SHA256. Existing rows in `integrations.credentials_encrypted` **cannot** be decrypted or brute-forced without the key.
2. **Immediate Containment:**
   - Generate a brand-new `INTEGRATION_ENCRYPTION_KEY` and set it in Render.
   - Mark all existing `integrations` rows encrypted under the lost key as `status = 'disconnected'` (using a controlled SQL maintenance update) so sync workers fail cleanly instead of raising `EncryptionError` loops.
3. **Tenant Recovery:**
   - Notify affected organization owners to re-enter or re-authorize their GitHub/Razorpay credentials via the UI/API, which will encrypt fresh ciphertext under the new key.
4. **If `JWT_SECRET_KEY` is lost/compromised:**
   - Immediately generate a new `JWT_SECRET_KEY` and update Render.
   - All existing JWTs (max lifetime 1 hour) are immediately invalidated with HTTP `401`, forcing all users to log in again safely.

---

## 6. Rotating Keys Safely

### A. Rotating `JWT_SECRET_KEY`

1. Generate a fresh key via `secrets.token_hex(32)`.
2. Update `JWT_SECRET_KEY` in Render Environment settings and redeploy.
3. Impact: Active sessions expire immediately (next request returns `401`), and users re-authenticate cleanly. No database records are affected.

### B. Rotating `INTEGRATION_ENCRYPTION_KEY` Without Data Loss

> [!WARNING]
> **Current Code Limitation:** `backend/app/core/security.py` currently instantiates a single `Fernet` cipher (`Fernet(raw_key)`). Replacing `INTEGRATION_ENCRYPTION_KEY` directly in Render while encrypted rows exist will immediately cause `EncryptionError` when reading existing `integrations.credentials_encrypted` rows!

Until `MultiFernet` dual-key rotation support is added to `backend/app/core/security.py`, perform rotation during a brief maintenance window using a one-time atomic re-encryption script:

1. **Take a Database Snapshot:** Create a Neon Branch or `pg_dump` backup first.
2. **Generate the New Key:**
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
3. **Re-encrypt Existing Rows Atomically** (run securely from a trusted shell with access to Neon direct URL, without printing keys or plaintext):
   ```python
   # Maintenance snippet — run carefully with OLD_KEY, NEW_KEY, and DATABASE_URL env vars
   import os
   from sqlalchemy import create_engine, select
   from sqlalchemy.orm import Session
   from app.core.security import decrypt_credentials, encrypt_credentials
   from app.models.integration import Integration

   old_key = os.environ["OLD_INTEGRATION_ENCRYPTION_KEY"]
   new_key = os.environ["NEW_INTEGRATION_ENCRYPTION_KEY"]
   engine = create_engine(os.environ["DATABASE_URL"])

   with Session(engine) as session:
       integrations = session.scalars(select(Integration)).all()
       for item in integrations:
           plaintext = decrypt_credentials(item.credentials_encrypted, key=old_key)
           item.credentials_encrypted = encrypt_credentials(plaintext, key=new_key)
       session.commit()
   ```
4. **Update Render Immediately:** Replace `INTEGRATION_ENCRYPTION_KEY` in Render with `NEW_INTEGRATION_ENCRYPTION_KEY` and redeploy.
5. **Back Up New Key:** Save `NEW_INTEGRATION_ENCRYPTION_KEY` in your secret vault before discarding `OLD_INTEGRATION_ENCRYPTION_KEY`.

**Recommended Future Enhancement (Zero-Downtime Rotation):** Update `app/core/security.py` to support `cryptography.fernet.MultiFernet` fed by a primary key plus optional comma-separated legacy key(s) (`INTEGRATION_ENCRYPTION_KEYS`), allowing new writes with the primary key while seamlessly decrypting legacy rows prior to background re-encryption.
