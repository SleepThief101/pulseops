import React, { useCallback, useEffect, useState } from "react";
import { EmptyState } from "../components/EmptyState";
import { roleBadgeTone } from "../components/Layout";
import { StatusBadge } from "../components/StatusBadge";
import { useAuth } from "../context/AuthContext";
import { ApiError, apiClient } from "../lib/api";
import { formatDateTime } from "../lib/format";
import type { MemberItem, Role } from "../types/api";

export function TeamPage() {
  const { token, activeOrg, logout } = useAuth();
  const [members, setMembers] = useState<MemberItem[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const isOwner = activeOrg?.role === "owner";

  useEffect(() => {
    setEmail("");
    setStatus(null);
    setError(null);
  }, [activeOrg?.organization_id]);

  const loadMembers = useCallback(async () => {
    if (!token || !activeOrg) return;
    const data = await apiClient.listMembers(activeOrg.organization_id, token, logout);
    setMembers(data);
  }, [token, activeOrg, logout]);

  useEffect(() => {
    loadMembers().catch((err) => {
      setError(err instanceof ApiError ? err.message : "Failed to load members.");
    });
  }, [loadMembers]);

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !activeOrg) return;
    setError(null);
    setStatus(null);
    setSubmitting(true);
    try {
      await apiClient.addMember(activeOrg.organization_id, email.trim(), role, token, logout);
      setStatus(`Added ${email.trim()} as ${role}.`);
      setEmail("");
      await loadMembers();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to add member.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="grid-asymmetric">
      {/* Left: Members Directory */}
      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Organization Members</h2>
            <p className="panel-subtitle">
              {activeOrg?.organization_name} · Access scoped strictly to this tenant
            </p>
          </div>
          <StatusBadge tone="neutral" className="tabular">
            {members.length} members
          </StatusBadge>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Member</th>
                <th>Role</th>
                <th>Joined</th>
              </tr>
            </thead>
            <tbody>
              {members.length === 0 ? (
                <tr>
                  <td colSpan={3}>
                    <EmptyState
                      title="No members loaded"
                      description="Organization membership records will appear here."
                      minHeight={140}
                    />
                  </td>
                </tr>
              ) : (
                members.map((m) => (
                  <tr key={m.membership_id}>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <span className="avatar-chip" aria-hidden="true">
                          {m.email.slice(0, 1).toUpperCase()}
                        </span>
                        <span style={{ fontWeight: 500 }}>{m.email}</span>
                      </div>
                    </td>
                    <td>
                      <StatusBadge tone={roleBadgeTone(m.role)} dot>
                        {m.role}
                      </StatusBadge>
                    </td>
                    <td
                      className="tabular"
                      style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}
                    >
                      {formatDateTime(m.created_at)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Right column: Add Member + Role Capability Matrix */}
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Add Existing User</h2>
              <p className="panel-subtitle">Grant organization access to a registered account</p>
            </div>
            {!isOwner && <StatusBadge tone="warn">Owner Only</StatusBadge>}
          </div>

          <div className="panel-pad">
            {status && (
              <div className="alert alert-ok" style={{ marginBottom: 16 }} role="status" aria-live="polite">
                {status}
              </div>
            )}
            {error && (
              <div className="alert alert-err" style={{ marginBottom: 16 }} role="alert">
                {error}
              </div>
            )}
            {!isOwner && (
              <div className="alert alert-warn" style={{ marginBottom: 16 }}>
                Only organization owners can invite or assign member roles.
              </div>
            )}

            <form onSubmit={handleInvite}>
              <div className="form-group">
                <label className="form-label" htmlFor="memberEmail">
                  User Email
                </label>
                <input
                  id="memberEmail"
                  name="memberEmail"
                  autoComplete="off"
                  spellCheck={false}
                  className="input"
                  type="email"
                  required
                  disabled={!isOwner || submitting}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="teammate@acme.io…"
                />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="memberRole">
                  Role Assignment
                </label>
                <select
                  id="memberRole"
                  name="memberRole"
                  className="select"
                  disabled={!isOwner || submitting}
                  value={role}
                  onChange={(e) => setRole(e.target.value as Role)}
                >
                  <option value="viewer">Viewer — Read-only KPIs, events &amp; briefings</option>
                  <option value="member">Member — Trigger syncs, CSV &amp; approve proposals</option>
                  <option value="owner">Owner — Credentials, members, audit logs</option>
                </select>
              </div>
              <button className="btn" type="submit" disabled={!isOwner || submitting}>
                {submitting ? "Adding…" : "Add Member"}
              </button>
            </form>
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <h2 className="panel-title">Role Capability Matrix</h2>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Role</th>
                  <th>Authorized Scope</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>
                    <StatusBadge tone="ok" dot>
                      owner
                    </StatusBadge>
                  </td>
                  <td style={{ color: "var(--text-secondary)", fontSize: "0.875rem", lineHeight: 1.45 }}>
                    Full administration, encrypted integrations, member roles, audit logs, and disconnect approvals
                  </td>
                </tr>
                <tr>
                  <td>
                    <StatusBadge tone="action" dot>
                      member
                    </StatusBadge>
                  </td>
                  <td style={{ color: "var(--text-secondary)", fontSize: "0.875rem", lineHeight: 1.45 }}>
                    Trigger connector syncs, CSV import, Copilot sync proposals &amp; approvals
                  </td>
                </tr>
                <tr>
                  <td>
                    <StatusBadge tone="neutral" dot>
                      viewer
                    </StatusBadge>
                  </td>
                  <td style={{ color: "var(--text-secondary)", fontSize: "0.875rem", lineHeight: 1.45 }}>
                    Read-only dashboards, normalized events stream &amp; read-only Copilot briefings
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}
