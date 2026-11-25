import React, { useEffect, useMemo, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { ApiError, apiClient } from "../lib/api";
import { formatCurrencyCents, formatDateTime } from "../lib/format";
import type { EventItem } from "../types/api";

interface EventsPageProps {
  initialSource?: string;
}

const SOURCES = [
  { id: "", label: "All" },
  { id: "razorpay", label: "Razorpay" },
  { id: "github", label: "GitHub" },
  { id: "csv", label: "CSV" },
  { id: "fake", label: "Fake" },
];

function sourceBadgeMeta(source: string): { cls: string; dot: string } {
  if (source === "razorpay") return { cls: "badge badge-ok", dot: "dot-ok" };
  if (source === "github") return { cls: "badge badge-info", dot: "dot-info" };
  if (source === "csv") return { cls: "badge badge-warn", dot: "dot-warn" };
  return { cls: "badge", dot: "dot-muted" };
}

export function EventsPage({ initialSource = "" }: EventsPageProps) {
  const { token, activeOrg, logout } = useAuth();
  const [events, setEvents] = useState<EventItem[]>([]);
  const [sourceFilter, setSourceFilter] = useState<string>(initialSource);
  const [eventTypeFilter, setEventTypeFilter] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSourceFilter(initialSource);
  }, [initialSource]);

  useEffect(() => {
    if (!token || !activeOrg) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiClient
      .listEvents(
        activeOrg.organization_id,
        token,
        sourceFilter || undefined,
        eventTypeFilter || undefined,
        logout
      )
      .then((res) => {
        if (!cancelled) setEvents(res);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Failed to load events.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, activeOrg, sourceFilter, eventTypeFilter, logout]);

  const filteredEvents = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return events;
    return events.filter(
      (evt) =>
        (evt.actor && evt.actor.toLowerCase().includes(q)) ||
        evt.external_id.toLowerCase().includes(q) ||
        evt.event_type.toLowerCase().includes(q)
    );
  }, [events, searchQuery]);

  return (
    <section className="panel">
      <div className="panel-header">
        <div className="row-actions" style={{ gap: 10 }}>
          <div className="segmented" role="group" aria-label="Filter by source">
            {SOURCES.map((src) => (
              <button
                key={src.id || "all"}
                type="button"
                aria-pressed={sourceFilter === src.id}
                className={`segmented-btn ${sourceFilter === src.id ? "active" : ""}`}
                onClick={() => setSourceFilter(src.id)}
              >
                {src.label}
              </button>
            ))}
          </div>

          <select
            aria-label="Filter by event type"
            className="select"
            style={{ width: "auto", padding: "6px 10px", fontSize: "0.8rem" }}
            value={eventTypeFilter}
            onChange={(e) => setEventTypeFilter(e.target.value)}
          >
            <option value="">All Event Types</option>
            <option value="subscription.charged">subscription.charged</option>
            <option value="payment.captured">payment.captured</option>
            <option value="payment.refunded">payment.refunded</option>
            <option value="subscription.cancelled">subscription.cancelled</option>
            <option value="pr.opened">pr.opened</option>
            <option value="pr.merged">pr.merged</option>
            <option value="issue.opened">issue.opened</option>
            <option value="issue.closed">issue.closed</option>
          </select>
        </div>

        <div className="row-actions">
          <input
            aria-label="Search events"
            className="input"
            style={{ width: 220, padding: "6px 10px", fontSize: "0.8rem" }}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Filter actor or external ID..."
          />
          <span className="badge tabular">
            {loading ? "Loading..." : `${filteredEvents.length} events`}
          </span>
        </div>
      </div>

      {error && (
        <div style={{ padding: "12px 16px 0" }}>
          <div className="alert alert-err" role="alert">
            {error}
          </div>
        </div>
      )}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Occurred</th>
              <th>Source</th>
              <th>Event Type</th>
              <th className="num-col">Amount</th>
              <th>Actor</th>
              <th>External ID</th>
              <th style={{ textAlign: "right" }}>Payload</th>
            </tr>
          </thead>
          <tbody>
            {!loading && filteredEvents.length === 0 ? (
              <tr>
                <td colSpan={7} style={{ color: "var(--text-muted)", padding: "28px 16px", textAlign: "center" }}>
                  No normalized events match the active filters.
                </td>
              </tr>
            ) : (
              filteredEvents.map((evt) => {
                const isExpanded = expandedId === evt.id;
                const badge = sourceBadgeMeta(evt.source);
                const isDebit =
                  evt.event_type === "payment.refunded" ||
                  evt.event_type === "subscription.cancelled";
                return (
                  <React.Fragment key={evt.id}>
                    <tr>
                      <td className="tabular" style={{ color: "var(--text-secondary)", whiteSpace: "nowrap" }}>
                        {formatDateTime(evt.occurred_at)}
                      </td>
                      <td>
                        <span className={badge.cls}>
                          <span className={`status-dot ${badge.dot}`} />
                          {evt.source}
                        </span>
                      </td>
                      <td>
                        <code style={{ color: "var(--text-primary)" }}>{evt.event_type}</code>
                      </td>
                      <td
                        className="num-col"
                        style={{
                          color:
                            evt.amount_cents === null
                              ? "var(--text-muted)"
                              : isDebit
                                ? "var(--danger-text)"
                                : "var(--accent-text)",
                          fontWeight: evt.amount_cents !== null ? 500 : 400,
                        }}
                      >
                        {evt.amount_cents !== null
                          ? formatCurrencyCents(evt.amount_cents, evt.currency || "USD")
                          : "—"}
                      </td>
                      <td style={{ color: evt.actor ? "var(--text-primary)" : "var(--text-muted)" }}>
                        {evt.actor || "—"}
                      </td>
                      <td className="mono" style={{ color: "var(--text-muted)" }}>
                        {evt.external_id}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        <button
                          type="button"
                          aria-expanded={isExpanded}
                          className="btn btn-secondary btn-sm"
                          onClick={() => setExpandedId(isExpanded ? null : evt.id)}
                        >
                          {isExpanded ? "Close" : "Inspect"}
                        </button>
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr>
                        <td colSpan={7} style={{ background: "rgba(255,255,255,0.015)", padding: "12px 16px" }}>
                          <pre className="payload-pre">
                            {JSON.stringify(
                              {
                                id: evt.id,
                                integration_id: evt.integration_id,
                                occurred_at: evt.occurred_at,
                                payload: evt.payload,
                              },
                              null,
                              2
                            )}
                          </pre>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
