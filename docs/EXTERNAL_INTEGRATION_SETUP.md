# External Integration & AI Copilot Setup Guide

This guide documents **every exact environment variable** and per-organization credential used by **PulseOps v1.1** (verified directly against `backend/app/config.py`, `backend/app/connectors/`, `backend/app/ai/`, and `backend/app/mcp_server.py`).

> [!CAUTION]
> - Never commit `.env` or paste real keys/secrets into code, documentation, frontend `VITE_*` variables, or prompts.
> - Keep Razorpay strictly in **Test Mode** (`rzp_test_*`). Live keys (`rzp_live_*`) are explicitly rejected by `RazorpayConnector`.
> - Changing environment variables in Render (`pulseops-api`) requires a service restart / manual redeploy for updated values to take effect.

---

## 1. Exact Environment Variable Reference (Code-Verified)

| Service | Exact Variable Name | Purpose | Required? | Environments | Sensitive? | Restart / Redeploy Needed? | How to Obtain |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Encryption** | `INTEGRATION_ENCRYPTION_KEY` | Fernet key encrypting per-org Razorpay & GitHub secrets at rest in PostgreSQL | **Required** | Local, CI, Production (Render) | **Yes** | Yes | Generated locally (`Fernet.generate_key().decode()`) |
| **Razorpay** | `RAZORPAY_MOCK_FALLBACK` | Enables synthetic fallback when Test Mode keys are omitted (`true` / `false`) | Optional *(default: `true`)* | Local, CI, Production (Render) | No | Yes | Set `true` for demo/fallback or `false` to require `rzp_test_*` keys |
| **DeepSeek** | `DEEPSEEK_API_KEY` | Bearer key enabling live `deepseek-chat` tool-calling & streaming Copilot | Optional *(fallback if unset)* | Local, Production (Render) | **Yes** | Yes | DeepSeek Platform (`https://platform.deepseek.com`) |
| **DeepSeek** | `DEEPSEEK_BASE_URL` | OpenAI-compatible DeepSeek endpoint base URL | Optional *(default: `https://api.deepseek.com`)* | Local, Production (Render) | No | Yes | DeepSeek API docs |
| **DeepSeek** | `DEEPSEEK_MODEL` | Chat completion model identifier | Optional *(default: `deepseek-chat`)* | Local, Production (Render) | No | Yes | DeepSeek API docs |
| **DeepSeek** | `DEEPSEEK_MAX_TOKENS` | Max completion tokens per LLM call (cost cap) | Optional *(default: `800`)* | Local, Production (Render) | No | Yes | Configured per budget |
| **DeepSeek** | `DEEPSEEK_MAX_TOOL_ROUNDS` | Bounded tool-calling loop iterations per prompt | Optional *(default: `3`)* | Local, Production (Render) | No | Yes | Configured per budget |
| **DeepSeek** | `COPILOT_CACHE_TTL_SECONDS` | Redis response cache TTL for read-only Copilot replies | Optional *(default: `120`)* | Local, Production (Render) | No | Yes | Configured per freshness needs |
| **GitHub OAuth** | `GITHUB_CLIENT_ID` | OAuth App client ID for `GET /orgs/{org_id}/integrations/github/oauth/url` | Optional *(if using PAT)* | Local, Production (Render) | No | Yes | GitHub Developer Settings -> OAuth Apps |
| **GitHub OAuth** | `GITHUB_CLIENT_SECRET` | OAuth App secret for code exchange (`/oauth/callback`) | Optional *(if using PAT)* | Local, Production (Render) | **Yes** | Yes | GitHub Developer Settings -> OAuth Apps |
| **GitHub OAuth** | `GITHUB_OAUTH_REDIRECT_URI` | OAuth callback URL (`https://<vercel-app>/integrations/github/callback`) | Optional *(if using PAT)* | Local, Production (Render) | No | Yes | Matches GitHub OAuth App callback setting |
| **MCP (`stdio`)** | `PULSEOPS_MCP_API_KEY` | Per-user `pmcp_...` key for local stdio MCP clients (or passed via `api_key` arg) | Optional *(MCP client only)* | Local MCP host process | **Yes** | Restart MCP client | Issued via authenticated `POST /me/api-keys` |

> [!NOTE]
> **Multi-Tenant Connector Secrets Are Stored Per-Organization in PostgreSQL:**
> Razorpay `key_id`, `key_secret`, `webhook_secret` and GitHub `access_token`, `repo`, `webhook_secret` are **not** global backend environment variables. Instead, an organization `owner` saves them per workspace in **Integrations & CSV**, where the backend encrypts them with `INTEGRATION_ENCRYPTION_KEY` in `integrations.credentials_encrypted`.

### Safe Verification (Without Printing Secrets)

- **Render Backend Environment Check:** Run `GET https://<render-api>/readiness` -> confirms `{"status": "ready", "checks": {"database": "ok", "redis": "ok"}}`.
- **DeepSeek Activation Check:** Ask a read-only question in **AI Copilot** (e.g., `"Summarize our MRR and open issues"`). The assistant message metadata displays `deepseek-chat` instead of `deterministic-fallback` when `DEEPSEEK_API_KEY` is active.
- **Razorpay / GitHub Connection Check:** Connect the integration in **Integrations & CSV** and click **Sync Now** -> **Recent Sync Runs** records `completed` (or clear `failed` `error_message` if credentials were rejected).

---

## 2. Razorpay Test Mode — Manual Dashboard Setup

PulseOps uses Razorpay REST API (`/v1/payments`) with HTTP Basic Auth and signed webhooks (`/webhooks/razorpay/{org_id}`). Live keys (`rzp_live_*`) are strictly blocked.

### Step-by-Step Razorpay Setup
1. Sign in to the **Razorpay Dashboard** (`https://dashboard.razorpay.com/`) and ensure the top toggle is set to **Test Mode**.
2. Go to **Account & Settings** -> **API Keys** (under Website and app settings) -> **Generate Test Key**.
3. Copy:
   - **Key ID** (`rzp_test_...`)
   - **Key Secret** (shown once — download/store safely)
4. Configure **Webhooks** (optional, for real-time webhook updates):
   - Go to **Account & Settings** -> **Webhooks** -> **+ Add New Webhook**.
   - **Webhook URL:** `https://<your-render-api>.onrender.com/webhooks/razorpay/<your-org-uuid>` *(shown directly inside the PulseOps **Integrations & CSV** form)*.
   - **Secret:** Choose a strong random string (only used for Razorpay HMAC-SHA256 verification).
   - **Active Events:** Select `payment.captured`, `payment.failed`, `payment.refunded`, `subscription.charged`, and `subscription.cancelled`.
5. In PulseOps (**Integrations & CSV** as organization `owner`):
   - **Connector Provider:** `Razorpay (Billing & Churn)`
   - **Connection Mode:** `Test Mode Keys / Access Token`
   - Paste **Razorpay Test Key ID** (`rzp_test_...`), **Razorpay Key Secret**, and optional **Webhook Secret**, then submit and click **Sync Now**.

---

## 3. DeepSeek AI — Manual Platform Setup

PulseOps calls `POST {DEEPSEEK_BASE_URL}/chat/completions` (`deepseek-chat`) strictly from the FastAPI backend (`backend/app/ai/deepseek_client.py`). The API key is never exposed to the browser or frontend build.

### Step-by-Step DeepSeek Setup
1. Sign in to the **DeepSeek Platform** (`https://platform.deepseek.com/`).
2. Navigate to **API Keys** -> **Create new API key**, name it (e.g. `pulseops-render`), and copy the `sk-...` key once.
3. In **Render Dashboard** -> `pulseops-api` -> **Environment**:
   - Add `DEEPSEEK_API_KEY` with your key.
   - *(Optional)* Set `DEEPSEEK_MODEL=deepseek-chat`, `DEEPSEEK_MAX_TOKENS=800`, `DEEPSEEK_MAX_TOOL_ROUNDS=3`.
4. Save and allow `pulseops-api` to redeploy/restart.
5. Verify in PulseOps **AI Copilot** tab: ask `"Summarize our MRR, churn, and failed payments"` and confirm the metadata shows `· deepseek-chat`.

---

## 4. GitHub Integration — Manual Credential Setup

PulseOps supports **Fine-Grained Personal Access Tokens** (recommended for connecting individual team repositories with minimal read-only permissions) and optional **OAuth Apps**.

### Option A: Fine-Grained Personal Access Token (Recommended — Least Privilege)
1. Go to **GitHub** -> **Settings** -> **Developer settings** -> **Personal access tokens** -> **Fine-grained tokens** -> **Generate new token**.
2. Set **Repository access** to **Only select repositories** and choose your target repo (`owner/name`).
3. Under **Repository permissions**, grant **Read-only** access strictly to:
   - **Issues:** `Read-only`
   - **Pull requests:** `Read-only`
   - **Metadata:** `Read-only` (selected automatically)
4. Generate and copy the token (`github_pat_...` or `ghp_...`).
5. *(Optional Webhook)* In your GitHub repo -> **Settings** -> **Webhooks** -> **Add webhook**:
   - **Payload URL:** `https://<your-render-api>.onrender.com/webhooks/github/<your-org-uuid>`
   - **Content type:** `application/json`
   - **Secret:** Strong random string matching what you enter in PulseOps.
   - **Events:** Let me select individual events -> **Issues** and **Pull requests**.
6. In PulseOps (**Integrations & CSV** as `owner`):
   - **Connector Provider:** `GitHub (PRs & Issues)`
   - **Connection Mode:** `Test Mode Keys / Access Token`
   - Enter **Repository (`owner/name`)**, **GitHub Personal Access Token**, and optional **Webhook Secret**, then submit and click **Sync Now**.

### Option B: GitHub OAuth App (Optional Backend Config)
1. In **GitHub** -> **Settings** -> **Developer settings** -> **OAuth Apps** -> **New OAuth App**, set Authorization callback URL to `https://pulseops-two.vercel.app/integrations/github/callback`.
2. Add `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, and `GITHUB_OAUTH_REDIRECT_URI` to Render `pulseops-api` Environment and redeploy.

---

## 5. Worker Mode vs Synchronous Mode (Render Free Tier)

| Mode | Where Active | Behavior |
| :--- | :--- | :--- |
| **Synchronous (`background=false`, default)** | Render Free Web (`pulseops-api`) & Local Docker | Executes connector sync immediately inside the API request (`SyncRun` transitions `running` -> `completed`/`failed`), requiring **no paid worker**. |
| **Asynchronous ARQ Worker (`background=true`)** | Local Docker (`pulseops-worker`) or Paid Render Worker | Enqueues `sync_integration_job` onto Redis with `max_tries=3` and `_job_id` deduplication. Disabled in `render.yaml` to remain on free tier; if Redis queueing fails, `pulseops-api` marks the `SyncRun` `failed` and returns HTTP `503`. |

---

## 6. MCP Client Setup (`stdio` Transport Only)

PulseOps runs a tenant-scoped MCP server over local `stdio` (`python -m app.mcp_server` inside `backend/`). Network HTTP/SSE MCP endpoints remain intentionally disabled.

1. Log in to PulseOps and create a per-user key via `POST /me/api-keys` (`{"name": "Local MCP Client", "expires_in_days": 30}`). Copy the `pmcp_...` plaintext key once.
2. Configure your local MCP host (e.g. Claude Desktop `claude_desktop_config.json`) using placeholders only (never commit real keys):
   ```json
   {
     "mcpServers": {
       "pulseops": {
         "command": "C:\\Users\\Rudransh\\Documents\\pulseops\\backend\\.venv\\Scripts\\python.exe",
         "args": ["-m", "app.mcp_server"],
         "cwd": "C:\\Users\\Rudransh\\Documents\\pulseops\\backend",
         "env": {
           "PULSEOPS_MCP_API_KEY": "<paste-your-pmcp-key-locally>"
         }
       }
     }
   }
   ```
3. Available read-only MCP tools: `pulseops_list_my_organizations`, `pulseops_metrics_summary`, `pulseops_recent_events`, and `pulseops_list_integrations`. Mutating tools remain strictly blocked over MCP.
