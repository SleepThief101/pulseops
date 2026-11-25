import React, { useCallback, useEffect, useRef, useState } from "react";
import { EmptyState } from "../components/EmptyState";
import { CopilotIcon } from "../components/Icons";
import { MarkdownContent } from "../components/MarkdownContent";
import { type BadgeTone, StatusBadge } from "../components/StatusBadge";
import { useAuth } from "../context/AuthContext";
import { ApiError, apiClient } from "../lib/api";
import { formatDateTime } from "../lib/format";
import type { CopilotProposal } from "../types/api";

interface ChatMsg {
  role: "user" | "assistant";
  content: string;
  modelUsed?: string;
  fallbackMode?: boolean;
  cached?: boolean;
  toolsExecuted?: string[];
}

const QUICK_PROMPTS = [
  { text: "Summarize our MRR, churn, and open issues", mutating: false },
  { text: "How is GitHub PR and issue cycle time trending?", mutating: false },
  { text: "Propose syncing our razorpay integration", mutating: true },
];

function proposalBorderColor(status: CopilotProposal["status"], toolName: string): string {
  if (status === "executed" || status === "approved") return "var(--accent)";
  if (status === "rejected" || status === "failed") return "var(--danger)";
  if (toolName === "disconnect_integration") return "var(--danger)";
  return "var(--warn)";
}

function proposalStatusTone(status: CopilotProposal["status"]): BadgeTone {
  if (status === "executed" || status === "approved") return "ok";
  if (status === "rejected" || status === "failed") return "err";
  return "warn";
}

export function CopilotPage() {
  const { token, activeOrg, logout } = useAuth();
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [proposals, setProposals] = useState<CopilotProposal[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);

  const isOwner = activeOrg?.role === "owner";
  const canApprove = isOwner || activeOrg?.role === "member";
  const pendingCount = proposals.filter((p) => p.status === "pending").length;

  const canDecideProposal = (proposal: CopilotProposal): boolean => {
    if (proposal.tool_name === "disconnect_integration") return isOwner;
    return canApprove;
  };

  const refreshProposals = useCallback(async () => {
    if (!token || !activeOrg) return;
    const list = await apiClient.listProposals(activeOrg.organization_id, token, logout);
    setProposals(list);
  }, [token, activeOrg, logout]);

  useEffect(() => {
    setMessages([]);
    setInput("");
    setError(null);
    refreshProposals().catch((err) => {
      setError(err instanceof ApiError ? err.message : "Failed to load action proposals.");
    });
  }, [activeOrg?.organization_id, refreshProposals]);

  useEffect(() => {
    if (threadRef.current) {
      threadRef.current.scrollTop = threadRef.current.scrollHeight;
    }
  }, [messages, busy]);

  async function sendPrompt(promptText: string) {
    if (!token || !activeOrg || !promptText.trim()) return;
    const text = promptText.trim();
    const fromInput = promptText === input;
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    if (fromInput) setInput("");
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
          cached: res.cached,
          toolsExecuted: res.tool_calls_executed?.map((t) => t.tool_name) ?? [],
        },
      ]);
      await refreshProposals();
    } catch (err) {
      if (fromInput) setInput(text);
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
    <div className="copilot-layout">
      {/* Operations Copilot Console */}
      <section className="panel">
        <div className="panel-header">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <CopilotIcon size={18} style={{ color: "var(--ai)", opacity: 0.9 }} />
            <div>
              <h2 className="panel-title">Operations Copilot Console</h2>
              <p className="panel-subtitle">
                Read-only queries execute directly · mutating actions create approval proposals
              </p>
            </div>
          </div>
          <StatusBadge tone="ai">Tenant Scoped</StatusBadge>
        </div>

        <div className="panel-pad" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {error && (
            <div className="alert alert-err" role="alert">
              {error}
            </div>
          )}

          <div
            className="row-actions"
            aria-label="Suggested prompts"
            style={{ flexWrap: "wrap" }}
          >
            {QUICK_PROMPTS.map((q) => {
              const disabledForViewer = q.mutating && !canApprove;
              return (
                <button
                  key={q.text}
                  type="button"
                  className="prompt-chip"
                  disabled={busy || disabledForViewer}
                  title={
                    disabledForViewer
                      ? "Member or owner role required to propose actions"
                      : undefined
                  }
                  onClick={() => sendPrompt(q.text)}
                >
                  {q.text}
                </button>
              );
            })}
          </div>

          <div
            ref={threadRef}
            className="copilot-thread"
            aria-live="polite"
            aria-label="Copilot conversation"
          >
            {messages.length === 0 && !busy ? (
              <div className="copilot-empty">
                <CopilotIcon size={28} style={{ opacity: 0.25 }} />
                <div className="copilot-empty-title">
                  Ask Copilot about live revenue, churn, or engineering throughput
                </div>
                <div className="copilot-empty-hint">
                  Choose a suggested operational prompt above or enter a custom query below.
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
                      <span className="mono" style={{ fontSize: "0.75rem" }}>
                        · {m.fallbackMode ? "deterministic-fallback" : m.modelUsed}
                        {m.cached ? " · cached" : ""}
                      </span>
                    )}
                  </div>
                  {m.role === "assistant" ? (
                    <MarkdownContent content={m.content} />
                  ) : (
                    <div>{m.content}</div>
                  )}
                  {m.role === "assistant" &&
                    m.toolsExecuted &&
                    m.toolsExecuted.length > 0 && (
                      <div className="msg-tools" aria-label="Tools executed">
                        {m.toolsExecuted.map((tool, tIdx) => (
                          <StatusBadge key={`${tool}-${tIdx}`} tone="ai">
                            {tool}
                          </StatusBadge>
                        ))}
                      </div>
                    )}
                </div>
              ))
            )}
            {busy && (
              <div
                className="msg-bubble msg-assistant"
                style={{ opacity: 0.78, fontStyle: "italic", fontSize: "0.9rem" }}
              >
                <div className="msg-meta">
                  <span style={{ fontWeight: 600, color: "var(--text-secondary)" }}>
                    PulseOps Copilot
                  </span>
                </div>
                Analyzing tenant telemetry…
              </div>
            )}
          </div>

          <form onSubmit={handleSend} className="row-actions">
            <input
              name="copilotPrompt"
              aria-label="Copilot message"
              autoComplete="off"
              className="input"
              style={{ flex: 1 }}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about MRR, churn, open issues, or request a sync…"
              disabled={busy}
            />
            <button className="btn" type="submit" disabled={busy || !input.trim()}>
              {busy ? "Running…" : "Send"}
            </button>
          </form>
        </div>
      </section>

      {/* Action Proposals Queue */}
      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Action Proposals</h2>
            <p className="panel-subtitle">
              Explicit human approval required prior to execution
            </p>
          </div>
          <StatusBadge tone={pendingCount > 0 ? "warn" : "neutral"} className="tabular">
            {pendingCount} pending
          </StatusBadge>
        </div>

        <div
          className="panel-pad"
          style={{ display: "flex", flexDirection: "column", gap: 12 }}
        >
          {!canApprove && (
            <div className="alert alert-warn">
              Viewer role is read-only — member or owner permissions are required to propose or decide actions.
            </div>
          )}

          {proposals.length === 0 ? (
            <EmptyState
              title="No action proposals yet"
              description="Mutating operations requested via Copilot will appear here for review."
              minHeight={160}
            />
          ) : (
            proposals.map((p) => {
              const borderColor = proposalBorderColor(p.status, p.tool_name);
              return (
                <div
                  key={p.id}
                  className="proposal-card"
                  style={{ borderLeftColor: borderColor }}
                >
                  <div
                    className="row-actions"
                    style={{ justifyContent: "space-between" }}
                  >
                    <span className="proposal-card-title">{p.title}</span>
                    <StatusBadge tone={proposalStatusTone(p.status)} dot>
                      {p.status}
                    </StatusBadge>
                  </div>

                  <div className="proposal-card-desc">{p.description}</div>

                  <div className="proposal-card-meta">
                    <code style={{ color: "var(--text-secondary)" }}>{p.tool_name}</code>
                    <span className="tabular">{formatDateTime(p.created_at)}</span>
                  </div>

                  {p.status === "failed" &&
                    typeof p.execution_result?.error === "string" && (
                      <div className="sync-error-note">
                        {p.execution_result.error}
                      </div>
                    )}

                  {p.status === "pending" && canDecideProposal(p) && (
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

                  {p.status === "pending" &&
                    canApprove &&
                    !canDecideProposal(p) && (
                      <div className="form-hint">
                        Owner permission required to approve or reject this action.
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
