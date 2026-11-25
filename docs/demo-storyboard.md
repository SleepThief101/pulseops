# PulseOps Demo Video Script & Storyboard

Target runtime: **2 minutes 45 seconds** (concise recruiter/technical walkthrough).

---

## Pre-Recording Environment Setup

1. Ensure Docker services (`api`, `worker`, `db`, `redis`) are running cleanly and Alembic is at head (`d3eb48b5de85`).
2. Ensure local `.env` has `CORS_ORIGINS=http://localhost:5173`.
3. Start the Vite frontend (`cd frontend && npm run dev`) and open `http://localhost:5173` in a clean browser window at `1440x900`.
4. Keep terminal ready in split pane for showing JSON logs / test counts if desired.

---

## Storyboard & Narration Script

### Scene 1 — Problem & Registration (`0:00 – 0:30`)
- **Screen:** `AuthPage` ("Create Organization").
- **Action:** Create a new workspace (`Acme Cloud`) and register a founder account.
- **Narration:**
  > "Small SaaS teams waste hours every week stitching together Stripe or Razorpay exports, GitHub PR spreadsheets, and issue trackers. PulseOps replaces that spreadsheet loop with an AI-native operational control tower backed by FastAPI, PostgreSQL 16, Redis/ARQ, and React."
- **Highlight:** Atomic creation of User + Organization + `owner` Membership with Argon2id hashing and HS256 JWT.

### Scene 2 — Connecting Integrations & Mock Billing (`0:30 – 1:05`)
- **Screen:** `Integrations & CSV` tab.
- **Action:**
  1. Connect **Razorpay** (`Mock / Synthetic Fallback` mode) -> click **Sync Now**.
  2. Connect **GitHub** (`Mock` mode, `acme/control-tower`) -> click **Sync Now**.
  3. Point to the **Recent Sync Runs** table showing `completed` runs with inserted/skipped counts.
- **Narration:**
  > "Credentials are encrypted at rest with Fernet before touching PostgreSQL. Every connector—Razorpay Test Mode with mock-billing fallback, GitHub REST/OAuth, or CSV uploads—normalizes events into a single tenant-scoped stream with unique database constraints so re-syncing is strictly idempotent."

### Scene 3 — Live KPIs, Recharts Trends & Event Drilldown (`1:05 – 1:40`)
- **Screen:** `Overview & KPIs` tab.
- **Action:**
  1. Show populated KPI cards: **Net MRR**, **ARR**, **Churn Rate**, **GitHub PRs Merged**, **Open Issues**, and **Avg Issue Cycle Time**.
  2. Hover over the Recharts **Daily Revenue vs Churn** `AreaChart` and **Engineering Throughput** `BarChart`.
  3. Click a KPI card to drill down into the `Events Stream` tab; click **Inspect** on a row to expand its normalized JSON payload.
- **Narration:**
  > "Our metrics engine aggregates directly from the normalized event store—showing net MRR, churn, PR throughput, open issues, and issue cycle time across selectable 7, 30, or 90-day windows, with click-through drilldowns to inspect every underlying event."

### Scene 4 — AI Copilot & Human-in-the-Loop Approvals (`1:40 – 2:20`)
- **Screen:** `AI Copilot & Approvals` tab.
- **Action:**
  1. Ask: `"Summarize our MRR, churn, and open issues"` -> show factual tenant-scoped briefing.
  2. Ask: `"Sync my razorpay integration"` -> show that Copilot does **not** execute mutations autonomously; instead it creates a **`pending` ActionProposal**.
  3. Click **Approve & Execute** -> status updates to **`executed`** cleanly.
- **Narration:**
  > "Read-only analytics tools execute directly within the user's organization scope, while any mutating action—like triggering an integration sync—creates an auditable ActionProposal requiring explicit human approval by an authorized member or owner."

### Scene 5 — Multi-Tenant RBAC & Engineering Quality (`2:20 – 2:45`)
- **Screen:** `Team & RBAC` tab + terminal showing `pytest` / GitHub Actions CI badge.
- **Action:** Show `owner` / `member` / `viewer` roles and CI pipeline (`Gitleaks`, `Ruff`, `Alembic`, backend + frontend suites).
- **Narration:**
  > "Every endpoint enforces organization membership and role hierarchy with 404 cross-tenant obscurity, structured JSON request logging, and automated CI checks across both backend and frontend. Thanks for watching."
