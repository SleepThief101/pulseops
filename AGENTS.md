# PulseOps — AI Development Instructions

## Project identity

PulseOps is an AI-native control tower for small SaaS teams.
It replaces weekly spreadsheets tracking MRR, churn, GitHub PRs,
open issues and issue cycle time.

This is a production-oriented portfolio project intended for
deployment and technical recruiter demonstrations.

## Technology stack

**Backend:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, Psycopg 3, Redis 7, ARQ, Pydantic Settings

**Frontend:** React, Vite, TypeScript, Recharts

**Integrations:** Razorpay Test Mode, GitHub API, CSV imports, DeepSeek API, MCP Python SDK

**Infrastructure:** Docker Compose, GitHub Actions, Neon, Upstash, Vercel, Render or Fly.io

---

## Architecture

- Maintain separation between routers, services, schemas, models and database logic.
- Use SQLAlchemy 2 conventions.
- Use Pydantic for validation.
- Use Alembic for database schema migrations.
- Use type hints throughout.
- Keep business logic out of route handlers.
- Avoid unnecessary dependencies and abstractions.
- Explain unfamiliar technical concepts briefly.

## Multi-tenancy

- Every tenant-owned database table must have `org_id`.
- Every tenant-owned query must enforce organization scope.
- Never trust client-supplied `org_id` for authorization.
- Derive organization access from authenticated membership.
- Enforce owner, member and viewer permissions on the backend.
- Never rely on frontend filtering for tenant isolation.
- Prevent cross-tenant reads and writes.
- Add automated tests for cross-tenant access.
- Treat tenant isolation failures as critical security bugs.

## Cost control

- Prefer free tiers and local development.
- Never activate paid services without explicit approval.
- Never provision unnecessary cloud infrastructure.
- Minimize external API and AI model calls.
- Use synthetic data when real integration access is unavailable.
- Use Razorpay Test Mode exclusively during development.
- Never activate live payment processing.
- Document simulated integrations honestly in the README.

## Secret safety

- Never hardcode credentials or API keys.
- Never print secrets in logs or terminal output.
- Never commit `.env`.
- Keep `.env.example` populated only with dummy values.
- Use Pydantic Settings for environment configuration.
- Never expose backend credentials to the frontend.
- Never paste API keys into prompts or chat.
- Never disable Gitleaks or secret scanning to bypass errors.

## Engineering quality

- Write readable, maintainable Python and TypeScript.
- Handle exceptions explicitly.
- Use structured logging.
- Write meaningful pytest tests.
- Keep API responses consistent.
- Document important engineering decisions.
- Never claim tests passed without actually executing them.
- Run `git diff --check` before committing.
- Update `PROGRESS.md` after every completed development step.

## Git rules

- Work in the existing pulseops repository.
- Use the existing `main` branch.
- Follow Conventional Commits.
- Never force push.
- Never rewrite existing Git history without approval.
- Never discard uncommitted user changes.
- Review changes before committing.
- Obtain explicit approval before pushing.

## Approval requirements

Require explicit approval before:

- Deleting files or directories.
- Dropping databases or deleting Docker volumes.
- Running destructive database migrations.
- Running `git reset --hard`, `git clean` or force push.
- Deploying to production.
- Activating paid infrastructure.
- Performing live payment operations.
- Accessing files outside the PulseOps workspace.
- Making any irreversible external change.

## Agent workflow

For every development task:

1. Inspect existing code.
2. Read the exact task requirements.
3. Implement only the requested task.
4. Run relevant tests.
5. Fix implementation-related failures.
6. Verify the Done When criteria.
7. Update `PROGRESS.md`.
8. Review `git diff` and `git diff --check`.
9. Report changed files and actual test results.
10. Stop and wait for the next instruction.

Do not start the next development step without explicit instruction.
