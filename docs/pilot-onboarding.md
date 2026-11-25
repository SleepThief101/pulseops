# PulseOps Pilot-User Onboarding Guide & Checklist

Use this guide when onboarding an early design-partner / pilot SaaS team to PulseOps.

> [!NOTE]
> Pilot onboarding requires explicit user/team participation and provisioned cloud services. Never import live production payment keys (`rzp_live_*`) during development or pilot Test Mode trials.

---

## 1. Pre-Onboarding Verification (Operator)

- [ ] Backend deployed on Render with `ENVIRONMENT=production`, `ENABLE_DOCS=false`, and `CORS_ORIGINS` set to the exact Vercel frontend URL.
- [ ] Neon PostgreSQL migrated cleanly (`alembic upgrade head` -> `849f79e737c6`).
- [ ] Upstash Redis TLS (`rediss://`) connected (`REDIS_URL`).
- [ ] Smoke test passes: `python scripts/smoke_test.py --base-url https://<api-url>`.

---

## 2. Pilot Team Setup Steps

### Step 1: Workspace Creation
1. Pilot founder visits the Vercel URL and selects **Create Organization**.
2. Enters organization name, work email, and password (minimum 8 characters).
3. Founder automatically receives the **`owner`** role.

### Step 2: Team Member Invitations (RBAC)
1. Teammates register their individual accounts first (or are provisioned by the team).
2. Founder navigates to **Team & RBAC** and adds teammates by email with appropriate roles:
   - `owner`: Full integration credentials, member management, and destructive approvals.
   - `member`: Can trigger syncs, upload CSV imports, and approve sync proposals.
   - `viewer`: Read-only access to dashboards, events, and read-only Copilot briefings.

### Step 3: Connect Data Sources
Choose one or more data paths:
- **Razorpay Test Mode:** Enter `rzp_test_*` Key ID + Key Secret (or select **Mock / Synthetic Fallback** for trial walkthroughs). Optionally configure webhook URL `https://<api-url>/webhooks/razorpay/<org_id>` with `X-Razorpay-Signature`.
- **GitHub:** Connect via Personal Access Token (`repo` in `owner/name` format) or OAuth flow. Optionally configure GitHub webhook URL `https://<api-url>/webhooks/github/<org_id>` with `X-Hub-Signature-256`.
- **Weekly Spreadsheet Migration (CSV):** Export historical revenue/churn/issue CSVs with columns `event_type,occurred_at,amount_cents,currency,actor` and import under **Integrations & CSV**.

### Step 4: Verify Metrics & Copilot
- [ ] Confirm **Sync Now** completes cleanly (`SyncRun` status `completed`).
- [ ] Confirm KPI cards (MRR, Churn Rate, PRs Merged, Open Issues, Cycle Time) reflect ingested data on **Overview & KPIs**.
- [ ] Test an AI Copilot read query (`"Summarize our MRR and open issues"`) and a mutating proposal approval (`"Sync razorpay"` -> **Approve & Execute**).
