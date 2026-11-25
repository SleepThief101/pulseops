import React, { useCallback, useEffect, useState } from "react";
import { CopilotIcon } from "../components/Icons";
import { useAuth } from "../context/AuthContext";
import { ApiError, apiClient } from "../lib/api";
import { formatDateTime } from "../lib/format";
import type { CopilotProposal } from "../types/api";

interface ChatMsg {
  role: "user" | "assistant";
  content: string;
  modelUsed?: string;
  fallbackMode?: boolean;
}

const QUICK_PROMPTS = [
  "Summarize our MRR, churn, and open issues",
  "How is GitHub PR and issue cycle time trending?",
  "Propose syncing our razorpay integration",
];

function proposalStatusBadge(status: CopilotProposal["status"]): { cls: string; dot: string } {
  if (status === "executed" || status === "approved") {
    return { cls: "badge badge-ok", dot: "dot-ok" };
  }
  if (status === "rejected" || status === "failed") {
    return { cls: "badge badge-err", dot: "dot-err" };
  }
  return { cls: "badge badge-warn", dot: "dot-warn" };
}

export function CopilotPage() {
  const { token, activeOrg, logout } = useAuth();
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [proposals, setProposals] = useState<CopilotProposal[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canApprove = activeOrg?.role === "owner" || activeOrg?.role === "member";
  const pendingCount = proposals.filter((p) => p.status === "pending").length;

  const refreshProposals = useCallback(async () => {
    if (!token || !activeOrg) return;
    const list = await apiClient.listProposals(activeOrg.organization_id, token, logout);
    setProposals(list);
  }, [token, activeOrg, logout]);

  useEffect(() => {
    refreshProposals().catch(() => {
      // ignore if copilot routes are unavailable
    });
  }, [refreshProposals]);

  async function sendPrompt(promptText: string) {
    if (!token || !activeOrg || !promptText.trim()) return;
    const text = promptText.trim();
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setBusy(true);
    setError(null);
    try {
      const res = await apiClient.sendCopilotMessage(
        activeOrg.organization_id,
        text,
        token,
        logout
      );
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: res.reply,
          modelUsed: res.model_used,
          fallbackMode: res.fallback_mode,
        },
      ]);
      await refreshProposals();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Copilot request failed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    await sendPrompt(input);
  }

  async function handleDecision(proposalId: string, decision: "approve" | "reject") {
    if (!token || !activeOrg) return;
    setBusy(true);
    setError(null);
    try {
      await apiClient.decideProposal(
        activeOrg.organization_id,
        proposalId,
        decision,
        token,
        logout
      );
      await refreshProposals();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Decision failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid-asymmetric">
      <section className="panel">
        <div className="panel-header">
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <CopilotIcon size={16} />
            <div>
              <h3 className="panel-title">Operations Copilot Console</h3>
              <p className="panel-subtitle">
                Read-only KPI queries run directly; mutating actions generate approval proposals
              </p>
            </div>
          </div>
          <span className="badge badge-ai">Tenant Scoped</span>
        </div>

        <div className="panel-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {error && (
            <div className="alert alert-err" role="alert">
              {error}
            </div>
          )}

          <div className="row-actions" aria-label="Suggested prompts">
            {QUICK_PROMPTS.map((q) => (
              <button
                key={q}
                type="button"
                className="prompt-chip"
                disabled={busy}
                onClick={() => sendPrompt(q)}
              >
                {q}
              </button>
            ))}
          </div>

          <div className="copilot-thread" aria-live="polite">
            {messages.length === 0 ? (
              <div style={{ color: "var(--text-muted)", margin: "auto 0", textAlign: "center", padding: 24 }}>
                <div style={{ fontWeight: 500, color: "var(--text-secondary)", marginBottom: 4 }}>
                  Ask PulseOps Copilot about live metrics or integration state
                </div>
                <div style={{ fontSize: "0.78rem" }}>
                  Select a prompt above or enter a question below.
                </div>
              </div>
            ) : (
              messages.map((m, idx) => (
                <div
                  key={idx}
                  className={`msg-bubble ${
                    m.role === "user" ? "msg-user" : "msg-assistant"
                  }`}
                >
                  <div className="msg-meta">
                    <span style={{ fontWeight: 600, color: "var(--text-secondary)" }}>
                      {m.role === "user" ? "You" : "PulseOps Copilot"}
                    </span>
                    {m.role === "assistant" && m.modelUsed && (
                      <span className="mono">
                        · {m.fallbackMode ? "deterministic-fallback" : m.modelUsed}
                      </span>
                    )}
                  </div>
                  <div>{m.content}</div>
                </div>
              ))
            )}
          </div>

          <form onSubmit={handleSend} className="row-actions">
            <input
              aria-label="Copilot message"
              className="input"
              style={{ flex: 1 }}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about MRR, churn, open issues, or request a sync..."
              disabled={busy}
            />
            <button className="btn" type="submit" disabled={busy || !input.trim()}>
              {busy ? "Running..." : "Send"}
            </button>
          </form>
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h3 className="panel-title">Action Proposals Queue</h3>
            <p className="panel-subtitle">Explicit human approval required prior to execution</p>
          </div>
          <span className={`badge ${pendingCount > 0 ? "badge-warn" : "badge"} tabular`}>
            {pendingCount} pending
          </span>
        </div>

        <div className="panel-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {!canApprove && (
            <div className="alert alert-warn">
              Viewer role is read-only: member or owner permissions are required to propose or decide actions.
            </div>
          )}

          {proposals.length === 0 ? (
            <p className="panel-subtitle" style={{ padding: "16px 0", textAlign: "center" }}>
              No action proposals created yet.
            </p>
          ) : (
            proposals.map((p) => {
              const badge = proposalStatusBadge(p.status);
              return (
                <div
                  key={p.id}
                  style={{
                    border: "1px solid var(--border-subtle)",
                    borderRadius: "var(--radius-md)",
                    padding: 14,
                    background: "var(--bg-input)",
                    display: "flex",
                    flexDirection: "column",
                    gap: 8,
                  }}
                >
                  <div className="row-actions" style={{ justifyContent: "space-between" }}>
                    <strong style={{ fontSize: "0.88rem" }}>{p.title}</strong>
                    <span className={badge.cls}>
                      <span className={`status-dot ${badge.dot}`} />
                      {p.status}
                    </span>
                  </div>
                  <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>
                    {p.description}
                  </div>
                  <div
                    className="row-actions"
                    style={{ justifyContent: "space-between", fontSize: "0.74rem", color: "var(--text-muted)" }}
                  >
                    <code>{p.tool_name}</code>
                    <span className="tabular">{formatDateTime(p.created_at)}</span>
                  </div>
                  {p.status === "pending" && canApprove && (
                    <div className="row-actions" style={{ paddingTop: 4 }}>
                      <button
                        type="button"
                        className="btn btn-sm"
                        disabled={busy}
                        onClick={() => handleDecision(p.id, "approve")}
                      >
                        Approve &amp; Execute
                      </button>
                      <button
                        type="button"
                        className="btn btn-danger btn-sm"
                        disabled={busy}
                        onClick={() => handleDecision(p.id, "reject")}
                      >
                        Reject
                      </button>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </section>
    </div>
  );
}
