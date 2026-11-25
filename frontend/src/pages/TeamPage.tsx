import React, { useCallback, useEffect, useState } from "react";
import { roleBadgeClass } from "../components/Layout";
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
      <section className="panel">
        <div className="panel-header">
          <div>
            <h3 className="panel-title">Organization Members</h3>
            <p className="panel-subtitle">
              {activeOrg?.organization_name} · Access scoped strictly to this tenant
            </p>
          </div>
          <span className="badge tabular">{members.length} members</span>
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
              {members.map((m) => (
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
                    <span className={roleBadgeClass(m.role)}>
                      <span
                        className={`status-dot ${
                          m.role === "owner"
                            ? "dot-ok"
                            : m.role === "member"
                              ? "dot-info"
                              : "dot-muted"
                        }`}
                      />
                      {m.role}
                    </span>
                  </td>
                  <td className="tabular" style={{ color: "var(--text-secondary)" }}>
                    {formatDateTime(m.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <section className="panel">
          <div className="panel-header">
            <div>
              <h3 className="panel-title">Add Existing User</h3>
              <p className="panel-subtitle">Grant organization access to a registered account</p>
            </div>
            {!isOwner && <span className="badge badge-warn">Owner Only</span>}
          </div>

          <div className="panel-pad">
            {status && (
              <div className="alert alert-ok" style={{ marginBottom: 14 }} role="status">
                {status}
              </div>
            )}
            {error && (
              <div className="alert alert-err" style={{ marginBottom: 14 }} role="alert">
                {error}
              </div>
            )}
            {!isOwner && (
              <div className="alert alert-warn" style={{ marginBottom: 14 }}>
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
                  className="input"
                  type="email"
                  required
                  disabled={!isOwner}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="teammate@acme.io"
                />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="memberRole">
                  Role Assignment
                </label>
                <select
                  id="memberRole"
                  className="select"
                  disabled={!isOwner}
                  value={role}
                  onChange={(e) => setRole(e.target.value as Role)}
                >
                  <option value="viewer">Viewer — Read-only KPIs, events &amp; briefings</option>
                  <option value="member">Member — Trigger syncs, CSV &amp; approve proposals</option>
                  <option value="owner">Owner — Credentials, members, audit logs</option>
                </select>
              </div>
              <button className="btn" type="submit" disabled={!isOwner || submitting}>
                {submitting ? "Adding..." : "Add Member"}
              </button>
            </form>
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <h3 className="panel-title">Role Capability Matrix</h3>
          </div>
          <div className="panel-pad" style={{ display: "flex", flexDirection: "column", gap: 10, fontSize: "0.8rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <span className="badge badge-ok">owner</span>
              <span style={{ color: "var(--text-secondary)", textAlign: "right" }}>
                Full admin, integrations, members, audit logs &amp; disconnect approvals
              </span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <span className="badge badge-info">member</span>
              <span style={{ color: "var(--text-secondary)", textAlign: "right" }}>
                Sync connectors, CSV import, Copilot sync proposals &amp; approvals
              </span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <span className="badge">viewer</span>
              <span style={{ color: "var(--text-secondary)", textAlign: "right" }}>
                Read-only dashboards, events stream &amp; read-only Copilot briefings
              </span>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
