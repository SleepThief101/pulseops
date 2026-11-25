import React, { useCallback, useEffect, useState } from "react";
import { EmptyState } from "../components/EmptyState";
import { RefreshIcon, UploadIcon } from "../components/Icons";
import { type BadgeTone, StatusBadge } from "../components/StatusBadge";
import { useAuth } from "../context/AuthContext";
import { API_BASE_URL, ApiError, apiClient } from "../lib/api";
import { formatDateTime } from "../lib/format";
import type { IntegrationItem, SyncRunItem } from "../types/api";

const SAMPLE_CSV = [
  "event_type,occurred_at,amount_cents,currency,actor,plan",
  `subscription.charged,${new Date().toISOString()},14900,USD,cust_csv_01,scale`,
  `issue.closed,${new Date().toISOString()},,,alice,`,
].join("\n");

function integrationTone(status: IntegrationItem["status"]): BadgeTone {
  if (status === "active") return "ok";
  if (status === "pending") return "warn";
  if (status === "disconnected" || status === "inactive") return "neutral";
  return "err";
}

function syncRunTone(status: SyncRunItem["status"]): BadgeTone {
  if (status === "completed") return "ok";
  if (status === "failed") return "err";
  return "warn";
}

export function IntegrationsPage() {
  const { token, activeOrg, logout } = useAuth();
  const [integrations, setIntegrations] = useState<IntegrationItem[]>([]);
  const [syncRuns, setSyncRuns] = useState<SyncRunItem[]>([]);
  const [provider, setProvider] = useState<"razorpay" | "github" | "fake">("razorpay");
  const [mode, setMode] = useState<"mock" | "credentials">("mock");
  const [repo, setRepo] = useState("pulseops/app");
  const [keyId, setKeyId] = useState("");
  const [secretOrToken, setSecretOrToken] = useState("");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [csvText, setCsvText] = useState(SAMPLE_CSV);
  const [csvFileName, setCsvFileName] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const isOwner = activeOrg?.role === "owner";
  const canOperate = activeOrg?.role === "owner" || activeOrg?.role === "member";

  useEffect(() => {
    setStatusMsg(null);
    setErrorMsg(null);
    setConfirmDeleteId(null);
    setKeyId("");
    setSecretOrToken("");
    setWebhookSecret("");
  }, [activeOrg?.organization_id]);

  const refresh = useCallback(async () => {
    if (!token || !activeOrg) return;
    const [ints, runs] = await Promise.all([
      apiClient.listIntegrations(activeOrg.organization_id, token, logout),
      apiClient.listSyncRuns(activeOrg.organization_id, token, logout),
    ]);
    setIntegrations(ints);
    setSyncRuns(runs);
  }, [token, activeOrg, logout]);

  useEffect(() => {
    refresh().catch((err) => {
      setErrorMsg(err instanceof ApiError ? err.message : "Failed to load integrations.");
    });
  }, [refresh]);

  async function handleConnect(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !activeOrg) return;
    setBusy(true);
    setErrorMsg(null);
    setStatusMsg(null);

    let credentials: Record<string, unknown> = {};
    if (provider === "razorpay") {
      credentials =
        mode === "mock"
          ? { mode: "mock" }
          : { key_id: keyId.trim(), key_secret: secretOrToken.trim() };
    } else if (provider === "github") {
      credentials =
        mode === "mock"
          ? { mode: "mock", repo: repo.trim() }
          : { access_token: secretOrToken.trim(), repo: repo.trim() };
    }
    if ((provider === "razorpay" || provider === "github") && webhookSecret.trim()) {
      credentials.webhook_secret = webhookSecret.trim();
    }

    try {
      await apiClient.connectIntegration(
        activeOrg.organization_id,
        provider,
        credentials,
        token,
        logout
      );
      setStatusMsg(`Connected ${provider} integration.`);
      setKeyId("");
      setSecretOrToken("");
      setWebhookSecret("");
      await refresh();
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : "Failed to connect integration.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSync(integrationId: string) {
    if (!token || !activeOrg) return;
    setBusy(true);
    setSyncingId(integrationId);
    setErrorMsg(null);
    setStatusMsg(null);
    try {
      const res = await apiClient.syncIntegration(
        activeOrg.organization_id,
        integrationId,
        true,
        token,
        logout
      );
      setStatusMsg(
        `Sync complete: ${res.inserted_count} inserted, ${res.skipped_count} duplicates skipped.`
      );
      await refresh();
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : "Sync failed.");
    } finally {
      setSyncingId(null);
      setBusy(false);
    }
  }

  async function handleDelete(integrationId: string) {
    if (!token || !activeOrg) return;
    setBusy(true);
    setErrorMsg(null);
    try {
      await apiClient.deleteIntegration(activeOrg.organization_id, integrationId, token, logout);
      setConfirmDeleteId(null);
      setStatusMsg("Integration removed.");
      await refresh();
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : "Delete failed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleCsvFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setErrorMsg(null);
    setStatusMsg(null);
    if (file.size > 2 * 1024 * 1024) {
      setErrorMsg("Selected CSV file exceeds the 2 MB limit.");
      return;
    }
    try {
      const content = await file.text();
      setCsvText(content);
      setCsvFileName(file.name);
      setStatusMsg(`Loaded ${file.name} (${file.size} bytes). Click "Import CSV Events" to ingest.`);
    } catch {
      setErrorMsg("Unable to read the selected CSV file.");
    }
  }

  async function handleCsvImport(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !activeOrg) return;
    if (!csvText.trim()) {
      setErrorMsg("Please select a CSV file or enter CSV rows before importing.");
      return;
    }
    setBusy(true);
    setErrorMsg(null);
    setStatusMsg(null);
    try {
      const res = await apiClient.importCsv(activeOrg.organization_id, csvText, token, logout);
      setStatusMsg(
        `CSV imported: ${res.inserted_count} inserted, ${res.skipped_count} duplicates skipped (total ${res.total_received}).`
      );
      await refresh();
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : "CSV import failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {statusMsg && (
        <div className="alert alert-ok" role="status" aria-live="polite">
          <span>{statusMsg}</span>
        </div>
      )}
      {errorMsg && (
        <div className="alert alert-err" role="alert">
          <span>{errorMsg}</span>
        </div>
      )}

      {/* Top row: Connected Connectors & Sync Audit */}
      <div className="grid-2col">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Connected Integrations</h2>
              <p className="panel-subtitle">Active sources scoped to this organization</p>
            </div>
            <StatusBadge tone="neutral" className="tabular">
              {integrations.length} connected
            </StatusBadge>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Provider</th>
                  <th>Status</th>
                  <th>Last Synced</th>
                  <th style={{ textAlign: "right" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {integrations.length === 0 ? (
                  <tr>
                    <td colSpan={4}>
                      <EmptyState
                        title="No integrations connected"
                        description="Configure Razorpay, GitHub, or Fake connector below to begin ingesting data."
                        minHeight={120}
                      />
                    </td>
                  </tr>
                ) : (
                  integrations.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <strong style={{ textTransform: "capitalize", fontWeight: 600 }}>
                          {item.provider}
                        </strong>
                      </td>
                      <td>
                        <StatusBadge tone={integrationTone(item.status)} dot>
                          {item.status}
                        </StatusBadge>
                      </td>
                      <td
                        className="tabular"
                        style={{ color: "var(--text-secondary)", fontSize: "0.84rem" }}
                      >
                        {formatDateTime(item.last_synced_at)}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        <div className="row-actions" style={{ justifyContent: "flex-end" }}>
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            disabled={!canOperate || busy}
                            onClick={() => handleSync(item.id)}
                          >
                            <RefreshIcon size={12} />
                            {syncingId === item.id ? "Syncing…" : "Sync Now"}
                          </button>
                          {isOwner && confirmDeleteId === item.id && (
                            <>
                              <button
                                type="button"
                                className="btn btn-danger btn-sm"
                                disabled={busy}
                                onClick={() => handleDelete(item.id)}
                              >
                                Confirm
                              </button>
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                disabled={busy}
                                onClick={() => setConfirmDeleteId(null)}
                              >
                                Cancel
                              </button>
                            </>
                          )}
                          {isOwner && confirmDeleteId !== item.id && (
                            <button
                              type="button"
                              className="btn btn-danger btn-sm"
                              disabled={busy}
                              onClick={() => setConfirmDeleteId(item.id)}
                            >
                              Remove
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Recent Sync Runs</h2>
              <p className="panel-subtitle">Worker &amp; manual ingestion audit trail</p>
            </div>
            <StatusBadge tone="neutral" className="tabular">
              {syncRuns.length} runs
            </StatusBadge>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Status</th>
                  <th className="num-col">Received</th>
                  <th className="num-col">Inserted</th>
                  <th className="num-col">Skipped</th>
                  <th>Started</th>
                </tr>
              </thead>
              <tbody>
                {syncRuns.length === 0 ? (
                  <tr>
                    <td colSpan={5}>
                      <EmptyState
                        title="No sync runs yet"
                        description="Run a manual or scheduled connector sync to view ingestion counts."
                        minHeight={120}
                      />
                    </td>
                  </tr>
                ) : (
                  syncRuns.map((run) => (
                    <tr key={run.id}>
                      <td>
                        <StatusBadge tone={syncRunTone(run.status)} dot>
                          {run.status}
                        </StatusBadge>
                        {run.status === "failed" && run.error_message && (
                          <div className="sync-error-note">{run.error_message}</div>
                        )}
                      </td>
                      <td className="num-col">{run.events_received}</td>
                      <td
                        className="num-col"
                        style={{ color: "var(--accent-text)", fontWeight: 500 }}
                      >
                        {run.events_inserted}
                      </td>
                      <td className="num-col" style={{ color: "var(--text-muted)" }}>
                        {run.events_skipped}
                      </td>
                      <td
                        className="tabular"
                        style={{
                          color: "var(--text-secondary)",
                          whiteSpace: "nowrap",
                          fontSize: "0.84rem",
                        }}
                      >
                        {formatDateTime(run.started_at)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      {/* Bottom row: Connect Form + CSV Import */}
      <div className="grid-2col">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Connect Integration</h2>
              <p className="panel-subtitle">
                Credentials are encrypted at rest with Fernet before storage
              </p>
            </div>
            {!isOwner && <StatusBadge tone="warn">Owner Only</StatusBadge>}
          </div>

          <div className="panel-pad">
            {!isOwner && (
              <div className="alert alert-warn" style={{ marginBottom: 16 }}>
                Only organization owners can connect or remove integrations.
              </div>
            )}
            <form onSubmit={handleConnect}>
              <div className="form-group">
                <label className="form-label" htmlFor="provider">
                  Connector Provider
                </label>
                <select
                  id="provider"
                  name="provider"
                  className="select"
                  value={provider}
                  disabled={!isOwner || busy}
                  onChange={(e) => setProvider(e.target.value as "razorpay" | "github" | "fake")}
                >
                  <option value="razorpay">Razorpay (Billing &amp; Churn)</option>
                  <option value="github">GitHub (PRs &amp; Issues)</option>
                  <option value="fake">Fake Connector (Synthetic Dev/Test)</option>
                </select>
              </div>

              {provider !== "fake" && (
                <div className="form-group">
                  <label className="form-label" htmlFor="connMode">
                    Connection Mode
                  </label>
                  <select
                    id="connMode"
                    name="connMode"
                    className="select"
                    value={mode}
                    disabled={!isOwner || busy}
                    onChange={(e) => setMode(e.target.value as "mock" | "credentials")}
                  >
                    <option value="mock">Mock / Synthetic Fallback (No External API)</option>
                    <option value="credentials">Test Mode Keys / Access Token</option>
                  </select>
                </div>
              )}

              {provider === "github" && (
                <div className="form-group">
                  <label className="form-label" htmlFor="ghRepo">
                    Repository (owner/name)
                  </label>
                  <input
                    id="ghRepo"
                    name="ghRepo"
                    autoComplete="off"
                    spellCheck={false}
                    className="input mono"
                    value={repo}
                    disabled={!isOwner || busy}
                    onChange={(e) => setRepo(e.target.value)}
                    placeholder="owner/repository…"
                    required
                  />
                </div>
              )}

              {provider === "razorpay" && mode === "credentials" && (
                <>
                  <div className="form-group">
                    <label className="form-label" htmlFor="rzpKey">
                      Razorpay Test Key ID (rzp_test_…)
                    </label>
                    <input
                      id="rzpKey"
                      name="rzpKey"
                      autoComplete="off"
                      spellCheck={false}
                      className="input mono"
                      value={keyId}
                      disabled={!isOwner || busy}
                      onChange={(e) => setKeyId(e.target.value)}
                      placeholder="rzp_test_…"
                      required
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label" htmlFor="rzpSecret">
                      Razorpay Key Secret
                    </label>
                    <input
                      id="rzpSecret"
                      name="rzpSecret"
                      autoComplete="new-password"
                      className="input"
                      type="password"
                      value={secretOrToken}
                      disabled={!isOwner || busy}
                      onChange={(e) => setSecretOrToken(e.target.value)}
                      required
                    />
                  </div>
                </>
              )}

              {provider === "github" && mode === "credentials" && (
                <div className="form-group">
                  <label className="form-label" htmlFor="ghToken">
                    GitHub Personal Access Token
                  </label>
                  <input
                    id="ghToken"
                    name="ghToken"
                    autoComplete="new-password"
                    className="input"
                    type="password"
                    value={secretOrToken}
                    disabled={!isOwner || busy}
                    onChange={(e) => setSecretOrToken(e.target.value)}
                    required
                  />
                </div>
              )}

              {(provider === "razorpay" || provider === "github") && (
                <div className="form-group">
                  <label className="form-label" htmlFor="whSecret">
                    Webhook Secret (optional)
                  </label>
                  <input
                    id="whSecret"
                    name="whSecret"
                    autoComplete="new-password"
                    className="input"
                    type="password"
                    value={webhookSecret}
                    disabled={!isOwner || busy}
                    onChange={(e) => setWebhookSecret(e.target.value)}
                    placeholder="HMAC-SHA256 webhook verification secret…"
                  />
                  {activeOrg && (
                    <div className="form-hint">
                      Webhook URL:{" "}
                      <code>
                        {API_BASE_URL}/webhooks/{provider}/{activeOrg.organization_id}
                      </code>
                    </div>
                  )}
                </div>
              )}

              <button className="btn" type="submit" disabled={!isOwner || busy}>
                Connect {provider}
              </button>
            </form>
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">CSV Event Import</h2>
              <p className="panel-subtitle">
                Idempotent SHA-256 deduplicated spreadsheet ingestion (max 2&nbsp;MB)
              </p>
            </div>
            {!canOperate && <StatusBadge tone="warn">Member+ Required</StatusBadge>}
          </div>

          <div className="panel-pad">
            {!canOperate && (
              <div className="alert alert-warn" style={{ marginBottom: 16 }}>
                Read-only viewer role cannot import CSV events (member or owner role required).
              </div>
            )}
            <form onSubmit={handleCsvImport}>
              <div className="form-group">
                <label className="form-label" htmlFor="csvFile">
                  Upload CSV File (.csv)
                </label>
                <div className="dropzone">
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <UploadIcon size={16} style={{ color: "var(--text-muted)", flexShrink: 0 }} />
                    <div>
                      <div style={{ fontSize: "0.9rem", fontWeight: 500 }}>
                        {csvFileName ? csvFileName : "Choose a UTF-8 CSV file from disk"}
                      </div>
                      <div className="form-hint">
                        Required: <code>event_type</code>, <code>occurred_at</code> · Optional:{" "}
                        <code>amount_cents</code>, <code>currency</code>, <code>actor</code>
                      </div>
                    </div>
                  </div>
                  <input
                    id="csvFile"
                    type="file"
                    accept=".csv,text/csv"
                    disabled={!canOperate || busy}
                    onChange={handleCsvFileSelect}
                    style={{ fontSize: "0.84rem", maxWidth: "100%" }}
                  />
                </div>
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="csvInput">
                  CSV Payload Preview / Editor
                </label>
                <textarea
                  id="csvInput"
                  name="csvInput"
                  spellCheck={false}
                  className="textarea"
                  rows={6}
                  value={csvText}
                  onChange={(e) => setCsvText(e.target.value)}
                  disabled={!canOperate || busy}
                />
              </div>

              <button className="btn" type="submit" disabled={!canOperate || busy}>
                <UploadIcon size={14} />
                Import CSV Events
              </button>
            </form>
          </div>
        </section>
      </div>
    </>
  );
}
