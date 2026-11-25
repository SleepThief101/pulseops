import React, { useEffect, useState } from "react";
import { PulseOpsLogo } from "../components/PulseOpsLogo";
import { useAuth } from "../context/AuthContext";
import { ApiError, apiClient } from "../lib/api";

export function AuthPage() {
  const { loginWithToken } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [orgName, setOrgName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [slowWakeNotice, setSlowWakeNotice] = useState(false);

  useEffect(() => {
    apiClient.warmUpHealth();
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    setSlowWakeNotice(false);
    const wakeTimer = setTimeout(() => setSlowWakeNotice(true), 3500);
    try {
      if (mode === "register") {
        await apiClient.register(email.trim(), password, orgName.trim());
      }
      const tokenRes = await apiClient.login(email.trim(), password);
      await loginWithToken(tokenRes.access_token);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.requestId ? `${err.message} (Request ID: ${err.requestId})` : err.message);
      } else {
        setError("Authentication failed. Check API connectivity.");
      }
    } finally {
      clearTimeout(wakeTimer);
      setSlowWakeNotice(false);
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-shell">
      <aside className="auth-aside">
        <div>
          <PulseOpsLogo size={26} subtitle="OPERATIONS CONTROL TOWER" />

          <h2 className="auth-headline">
            One operational telemetry plane for revenue and engineering.
          </h2>
          <p className="page-desc" style={{ maxWidth: 420 }}>
            Replace weekly spreadsheets with normalized billing, churn, PR throughput,
            and issue cycle-time visibility.
          </p>

          <ul className="auth-spec-list">
            <li className="auth-spec-item">
              <span className="status-dot dot-ok" style={{ marginTop: 7 }} />
              <span>
                <strong style={{ color: "var(--text-primary)", fontWeight: 500 }}>
                  Tenant-isolated RBAC
                </strong>{" "}
                — Strict organization scoping across owner, member, and viewer roles.
              </span>
            </li>
            <li className="auth-spec-item">
              <span className="status-dot dot-info" style={{ marginTop: 7 }} />
              <span>
                <strong style={{ color: "var(--text-primary)", fontWeight: 500 }}>
                  Idempotent ingestion
                </strong>{" "}
                — Encrypted Razorpay, GitHub, and CSV streams deduplicated in PostgreSQL.
              </span>
            </li>
            <li className="auth-spec-item">
              <span className="status-dot dot-warn" style={{ marginTop: 7 }} />
              <span>
                <strong style={{ color: "var(--text-primary)", fontWeight: 500 }}>
                  Human-approved AI Copilot
                </strong>{" "}
                — Read-only briefings and gated mutation proposals with audit attribution.
              </span>
            </li>
          </ul>
        </div>

        <div className="mono" style={{ fontSize: "0.74rem", color: "var(--text-muted)" }}>
          PulseOps v1.0 · Argon2id + HS256 JWT · Fernet Encrypted Credentials
        </div>
      </aside>

      <main className="auth-main">
        <div className="auth-card">
          <div className="auth-mobile-brand" style={{ marginBottom: 16 }}>
            <PulseOpsLogo size={22} subtitle="OPERATIONS CONTROL TOWER" />
          </div>
          <div style={{ marginBottom: 20 }}>
            <h1 className="brand-title" style={{ fontSize: "1.18rem" }}>
              {mode === "login" ? "Sign in to PulseOps" : "Create workspace"}
            </h1>
            <p className="panel-subtitle" style={{ marginTop: 4 }}>
              {mode === "login"
                ? "Enter your credentials to open your organization control tower."
                : "Provision an owner account and isolated tenant organization."}
            </p>
          </div>

          <div
            className="segmented"
            role="tablist"
            aria-label="Authentication mode"
            style={{ width: "100%", marginBottom: 18 }}
          >
            <button
              type="button"
              role="tab"
              aria-selected={mode === "login"}
              className={`segmented-btn ${mode === "login" ? "active" : ""}`}
              style={{ flex: 1 }}
              onClick={() => {
                setMode("login");
                setError(null);
              }}
            >
              Sign In
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "register"}
              className={`segmented-btn ${mode === "register" ? "active" : ""}`}
              style={{ flex: 1 }}
              onClick={() => {
                setMode("register");
                setError(null);
              }}
            >
              Create Organization
            </button>
          </div>

          {error && (
            <div className="alert alert-err" style={{ marginBottom: 14 }} role="alert">
              <span>{error}</span>
            </div>
          )}

          {slowWakeNotice && !error && (
            <div className="alert alert-warn" style={{ marginBottom: 14 }} role="status">
              <span>
                Connecting to PulseOps API — Render free-tier services may take 30–50s on cold start.
              </span>
            </div>
          )}

          <form onSubmit={handleSubmit}>
            {mode === "register" && (
              <div className="form-group">
                <label className="form-label" htmlFor="orgName">
                  Organization Name
                </label>
                <input
                  id="orgName"
                  className="input"
                  type="text"
                  required
                  value={orgName}
                  onChange={(e) => setOrgName(e.target.value)}
                  placeholder="Acme SaaS"
                />
              </div>
            )}

            <div className="form-group">
              <label className="form-label" htmlFor="email">
                Work Email
              </label>
              <input
                id="email"
                className="input"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="founder@acme.io"
              />
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="password">
                Password
              </label>
              <input
                id="password"
                className="input"
                type="password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="At least 8 characters"
              />
            </div>

            <button
              className="btn"
              type="submit"
              disabled={submitting}
              style={{ width: "100%", marginTop: 4, padding: "9px 14px" }}
            >
              {submitting
                ? "Authenticating..."
                : mode === "login"
                  ? "Sign In"
                  : "Create Account & Workspace"}
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}
