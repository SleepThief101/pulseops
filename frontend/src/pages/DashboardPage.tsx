import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ChartPanel } from "../components/ChartPanel";
import { EmptyState } from "../components/EmptyState";
import { KpiCard } from "../components/KpiCard";
import { StatusBadge } from "../components/StatusBadge";
import { useAuth } from "../context/AuthContext";
import { ApiError, apiClient } from "../lib/api";
import {
  formatDateTime,
  formatMoneyMinor,
  formatShortDate,
  getMinorUnitExponent,
  minorToMajorNumber,
} from "../lib/format";
import type {
  CurrencyMetricsSummary,
  IntegrationItem,
  MetricsSummary,
  MetricsTimeseriesPoint,
} from "../types/api";

interface DashboardPageProps {
  windowDays: number;
  onGoToIntegrations: () => void;
  onDrilldownEvents: (source: string) => void;
}

const DEMO_ORG_NAME = "PulseOps Synthetic Demo";

function formatCompactMoneyAxis(value: number, currency: string | null): string {
  const sym =
    currency === "INR"
      ? "₹"
      : currency === "EUR"
        ? "€"
        : currency === "GBP"
          ? "£"
          : currency === "JPY"
            ? "¥"
            : currency === "USD" || !currency
              ? "$"
              : `${currency} `;
  if (value === 0) return `${sym}0`;
  if (Math.abs(value) >= 1_000_000) {
    return `${sym}${(value / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  }
  if (Math.abs(value) >= 1000) {
    return `${sym}${(value / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  }
  return `${sym}${value}`;
}

interface TooltipPayloadEntry {
  name?: string;
  value?: number;
  color?: string;
  dataKey?: string;
}

function CustomRevenueTooltip({
  active,
  payload,
  label,
  currency,
}: {
  active?: boolean;
  payload?: TooltipPayloadEntry[];
  label?: string;
  currency: string | null;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const exp = getMinorUnitExponent(currency);
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-date">{label}</div>
      {payload.map((entry) => {
        const minor = Math.round(Number(entry.value || 0) * 10 ** exp);
        return (
          <div key={entry.dataKey || entry.name} className="chart-tooltip-row">
            <span className="legend-item">
              <span
                className="status-dot"
                style={{ background: entry.color || "var(--accent)" }}
              />
              {entry.name}
            </span>
            <span className="tabular" style={{ fontWeight: 600 }}>
              {formatMoneyMinor(minor, currency, exp)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function CustomEngTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TooltipPayloadEntry[];
  label?: string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-date">{label}</div>
      {payload.map((entry) => (
        <div key={entry.dataKey || entry.name} className="chart-tooltip-row">
          <span className="legend-item">
            <span
              className="status-dot"
              style={{ background: entry.color || "var(--info)" }}
            />
            {entry.name}
          </span>
          <span className="tabular" style={{ fontWeight: 600 }}>
            {entry.value ?? 0}
          </span>
        </div>
      ))}
    </div>
  );
}

export function DashboardPage({
  windowDays,
  onGoToIntegrations,
  onDrilldownEvents,
}: DashboardPageProps) {
  const { token, activeOrg, logout } = useAuth();
  const isDemoWorkspace = activeOrg?.organization_name === DEMO_ORG_NAME;
  const [includeSynthetic, setIncludeSynthetic] = useState<boolean>(isDemoWorkspace);
  const [selectedCurrency, setSelectedCurrency] = useState<string>("");
  const [summary, setSummary] = useState<MetricsSummary | null>(null);
  const [points, setPoints] = useState<MetricsTimeseriesPoint[]>([]);
  const [integrations, setIntegrations] = useState<IntegrationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);

  useEffect(() => {
    setIncludeSynthetic(activeOrg?.organization_name === DEMO_ORG_NAME);
    setSelectedCurrency("");
  }, [activeOrg?.organization_id, activeOrg?.organization_name]);

  useEffect(() => {
    if (!token || !activeOrg) return;
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([
      apiClient.getMetricsSummary(
        activeOrg.organization_id,
        windowDays,
        token,
        logout,
        includeSynthetic
      ),
      apiClient.getMetricsTimeseries(
        activeOrg.organization_id,
        windowDays,
        token,
        logout,
        includeSynthetic
      ),
      apiClient
        .listIntegrations(activeOrg.organization_id, token, logout)
        .catch(() => [] as IntegrationItem[]),
    ])
      .then(([sumRes, tsRes, intsRes]) => {
        if (cancelled) return;
        setSummary(sumRes);
        setPoints(tsRes.points);
        setIntegrations(intsRes);
        if (sumRes.currencies.length > 0) {
          setSelectedCurrency((prev) =>
            prev && sumRes.currencies.includes(prev) ? prev : sumRes.currencies[0]
          );
        } else {
          setSelectedCurrency("");
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load metrics.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [token, activeOrg, windowDays, includeSynthetic, reloadTick, logout]);

  if (!activeOrg) {
    return (
      <div className="panel">
        <EmptyState
          title="No active organization"
          description="Select or create an organization in the top bar to view operational metrics."
        />
      </div>
    );
  }

  if (loading) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <div className="kpi-grid" aria-label="Loading metrics">
          {[0, 1, 2, 3].map((idx) => (
            <div
              key={idx}
              className="kpi-card"
              style={{ cursor: "default", gap: 12 }}
            >
              <div className="skeleton-line" style={{ width: "52%", height: 12 }} />
              <div className="skeleton-line" style={{ width: "72%", height: 32, borderRadius: 6 }} />
              <div className="skeleton-line" style={{ width: "86%", height: 12 }} />
            </div>
          ))}
        </div>
        <div className="panel panel-pad" style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
          Loading operational metrics…
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="alert alert-err" role="alert" style={{ alignItems: "center" }}>
        <span>{error}</span>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() => setReloadTick((t) => t + 1)}
        >
          Retry
        </button>
      </div>
    );
  }

  if (!summary) return null;

  const activeCurrencyCode =
    (selectedCurrency && summary.by_currency[selectedCurrency]
      ? selectedCurrency
      : summary.currencies[0]) || null;
  const activeCurrencySummary: CurrencyMetricsSummary | null = activeCurrencyCode
    ? summary.by_currency[activeCurrencyCode] ?? null
    : null;

  const activeExp = activeCurrencySummary?.minor_unit_exponent ?? getMinorUnitExponent(activeCurrencyCode);

  const chartData = points.map((p) => {
    const currPt = activeCurrencyCode ? p.by_currency?.[activeCurrencyCode] : undefined;
    const revMinor = currPt ? currPt.gross_volume_minor : 0;
    const churnMinor = currPt ? currPt.refunded_minor + currPt.churned_mrr_minor : 0;
    return {
      ...p,
      label: formatShortDate(p.date),
      revenueMajor: minorToMajorNumber(revMinor, activeCurrencyCode, activeExp),
      churnMajor: minorToMajorNumber(churnMinor, activeCurrencyCode, activeExp),
    };
  });

  const hasRevenueActivity = chartData.some(
    (p) => p.revenueMajor > 0 || p.churnMajor > 0
  );
  const hasEngActivity = chartData.some(
    (p) => p.prs_merged > 0 || p.issues_opened > 0 || p.issues_closed > 0
  );

  const churnBadgeTone =
    summary.churn_rate_pct > 15
      ? "err"
      : summary.churn_rate_pct > 0
        ? "warn"
        : "ok";

  return (
    <>
      {/* Provenance & Multi-Currency Banner */}
      {(summary.contains_synthetic_data ||
        summary.synthetic_events_excluded ||
        summary.multi_currency) && (
        <div
          className="panel panel-pad"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 14,
            flexWrap: "wrap",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            {summary.contains_synthetic_data && (
              <StatusBadge tone="warn" dot>
                Synthetic / Demo Data ({summary.synthetic_events_in_window} events)
              </StatusBadge>
            )}
            {summary.synthetic_events_excluded && (
              <StatusBadge tone="info" dot>
                Live Metrics Only ({summary.synthetic_events_in_window} synthetic excluded)
              </StatusBadge>
            )}
            {summary.multi_currency && (
              <StatusBadge tone="action">
                Multi-Currency ({summary.currencies.join(" · ")}) — No FX mixing
              </StatusBadge>
            )}
          </div>

          <div className="row-actions">
            {summary.currencies.length > 1 && (
              <div className="segmented" role="group" aria-label="Select Currency">
                {summary.currencies.map((curr) => (
                  <button
                    key={curr}
                    type="button"
                    aria-pressed={activeCurrencyCode === curr}
                    className={`segmented-btn ${activeCurrencyCode === curr ? "active" : ""}`}
                    onClick={() => setSelectedCurrency(curr)}
                  >
                    {curr}
                  </button>
                ))}
              </div>
            )}

            {summary.synthetic_events_in_window > 0 && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setIncludeSynthetic((prev) => !prev)}
              >
                {includeSynthetic ? "Show Live Only" : "Include Synthetic Data"}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Per-currency snapshot cards when multiple currencies exist */}
      {summary.multi_currency && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
            gap: 12,
          }}
          aria-label="Per-Currency Breakdown"
        >
          {summary.currencies.map((curr) => {
            const csum = summary.by_currency[curr];
            const isSelected = curr === activeCurrencyCode;
            return (
              <button
                key={curr}
                type="button"
                className="panel panel-pad"
                onClick={() => setSelectedCurrency(curr)}
                style={{
                  textAlign: "left",
                  cursor: "pointer",
                  borderColor: isSelected
                    ? "var(--accent-action-border)"
                    : "var(--border-subtle)",
                  background: isSelected
                    ? "var(--bg-surface-elevated)"
                    : "var(--bg-surface)",
                }}
              >
                <div className="row-actions" style={{ justifyContent: "space-between", marginBottom: 8 }}>
                  <StatusBadge tone={isSelected ? "action" : "neutral"}>{curr}</StatusBadge>
                  <span style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
                    {csum.minor_unit_name} (10^{csum.minor_unit_exponent ?? "?"})
                  </span>
                </div>
                <div className="tabular" style={{ fontSize: "1.15rem", fontWeight: 600 }}>
                  {csum.formatted_gross_volume}{" "}
                  <span style={{ fontSize: "0.8rem", fontWeight: 400, color: "var(--text-secondary)" }}>
                    gross
                  </span>
                </div>
                <div className="tabular" style={{ fontSize: "0.8125rem", color: "var(--text-muted)", marginTop: 4 }}>
                  MRR {csum.formatted_recurring_mrr} · One-time {csum.formatted_one_time_volume}
                </div>
              </button>
            );
          })}
        </div>
      )}

      {summary.total_events_in_window === 0 && (
        <div
          className="panel panel-pad"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 16,
            flexWrap: "wrap",
          }}
        >
          <div>
            <div style={{ fontWeight: 600, fontSize: "1rem", marginBottom: 4 }}>
              No {includeSynthetic ? "operational" : "live"} events synced in the last {windowDays} days.
            </div>
            <div className="page-desc" style={{ margin: 0 }}>
              {summary.synthetic_events_excluded
                ? `${summary.synthetic_events_in_window} synthetic/mock events exist — toggle "Include Synthetic Data" above or connect a live source.`
                : "Connect Razorpay, GitHub, or upload a CSV to populate live metrics."}
            </div>
          </div>
          <button type="button" className="btn" onClick={onGoToIntegrations}>
            Connect Integrations
          </button>
        </div>
      )}

      {/* Primary KPIs */}
      <section className="kpi-grid" aria-label="Key Metrics">
        <KpiCard
          label={`Recurring MRR${activeCurrencyCode ? ` (${activeCurrencyCode})` : ""}`}
          value={
            activeCurrencySummary
              ? activeCurrencySummary.formatted_recurring_mrr
              : formatMoneyMinor(0, "USD")
          }
          badgeText={
            activeCurrencySummary && !activeCurrencySummary.mrr_reliable
              ? "No Recurring"
              : "Recurring"
          }
          badgeTone={
            activeCurrencySummary && !activeCurrencySummary.mrr_reliable ? "warn" : "ok"
          }
          meta={
            activeCurrencySummary
              ? `ARR ${activeCurrencySummary.formatted_recurring_arr}`
              : "No active subscriptions"
          }
          onClick={() => onDrilldownEvents("razorpay")}
        />

        <KpiCard
          label={`Payment Volume (${windowDays}d${activeCurrencyCode ? ` · ${activeCurrencyCode}` : ""})`}
          value={
            activeCurrencySummary
              ? activeCurrencySummary.formatted_gross_volume
              : formatMoneyMinor(0, "USD")
          }
          badgeText={`${summary.churn_rate_pct}% churn`}
          badgeTone={churnBadgeTone}
          meta={
            activeCurrencySummary
              ? `1-time ${activeCurrencySummary.formatted_one_time_volume} · Sub ${activeCurrencySummary.formatted_subscription_revenue}`
              : `${summary.active_subscribers_count} active subscribers`
          }
          onClick={() => onDrilldownEvents("razorpay")}
        />

        <KpiCard
          label="Pull Requests"
          value={`${summary.prs_merged} merged`}
          badgeText="GitHub"
          badgeTone="info"
          meta={
            <>
              {summary.prs_opened} opened
              {summary.avg_pr_cycle_time_hours !== null
                ? ` · ${summary.avg_pr_cycle_time_hours}h cycle`
                : ""}
            </>
          }
          onClick={() => onDrilldownEvents("github")}
        />

        <KpiCard
          label="Open Issues"
          value={summary.open_issues_count}
          badgeText={`${summary.issues_closed_count} closed`}
          badgeTone={summary.open_issues_count > 0 ? "warn" : "ok"}
          meta={
            summary.avg_issue_cycle_time_hours !== null
              ? `Avg cycle ${summary.avg_issue_cycle_time_hours}h`
              : "No closed cycle data"
          }
          onClick={() => onDrilldownEvents("github")}
        />
      </section>

      {activeCurrencySummary?.mrr_note && (
        <div className="alert alert-warn" role="status">
          <span>{activeCurrencySummary.mrr_note}</span>
        </div>
      )}

      {/* Secondary Financials & Operational Health Split */}
      <section className="ops-health-grid" aria-label="Window Financials and Health">
        <div className="telemetry-strip" aria-label="Window Financial Summary">
          <div className="telemetry-item">
            <span className="telemetry-label">Net Revenue</span>
            <span className="telemetry-val">
              {activeCurrencySummary
                ? activeCurrencySummary.formatted_net_revenue
                : formatMoneyMinor(0, "USD")}
            </span>
          </div>
          <div className="telemetry-item">
            <span className="telemetry-label">Refunds</span>
            <span className="telemetry-val">
              {activeCurrencySummary
                ? activeCurrencySummary.formatted_refunded
                : formatMoneyMinor(0, "USD")}
            </span>
          </div>
          <div className="telemetry-item">
            <span className="telemetry-label">
              Failed ({activeCurrencySummary?.failed_payments_count ?? 0})
            </span>
            <span className="telemetry-val">
              {activeCurrencySummary
                ? activeCurrencySummary.formatted_failed_payments
                : formatMoneyMinor(0, "USD")}
            </span>
          </div>
          <div className="telemetry-item">
            <span className="telemetry-label">Churned MRR</span>
            <span className="telemetry-val">
              {activeCurrencySummary
                ? activeCurrencySummary.formatted_churned_mrr
                : formatMoneyMinor(0, "USD")}
            </span>
          </div>
        </div>

        <div className="connector-health-bar" aria-label="Cycle Time and Integration Health">
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span className="telemetry-label">Cycle Time &amp; Connector Health</span>
            <div className="connector-health-pills">
              <StatusBadge tone={summary.avg_pr_cycle_time_hours !== null ? "info" : "neutral"}>
                PR Cycle:{" "}
                {summary.avg_pr_cycle_time_hours !== null
                  ? `${summary.avg_pr_cycle_time_hours}h`
                  : "No data"}
              </StatusBadge>
              <StatusBadge tone={summary.avg_issue_cycle_time_hours !== null ? "info" : "neutral"}>
                Issue Cycle:{" "}
                {summary.avg_issue_cycle_time_hours !== null
                  ? `${summary.avg_issue_cycle_time_hours}h`
                  : "No data"}
              </StatusBadge>
              {integrations.length === 0 ? (
                <StatusBadge tone="warn" dot>
                  0 connectors
                </StatusBadge>
              ) : (
                integrations.map((integ) => (
                  <StatusBadge
                    key={integ.id}
                    tone={integ.status === "active" ? "ok" : "err"}
                    dot
                  >
                    <span style={{ textTransform: "capitalize" }}>{integ.provider}</span>
                    <span style={{ opacity: 0.7 }}>
                      · {formatDateTime(integ.last_synced_at)}
                    </span>
                  </StatusBadge>
                ))
              )}
            </div>
          </div>

          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onGoToIntegrations}
          >
            Manage
          </button>
        </div>
      </section>

      {/* Primary Operational Charts */}
      <section className="charts-grid" aria-label="Trend Charts">
        <ChartPanel
          title={`Revenue & Churn Trajectory${activeCurrencyCode ? ` (${activeCurrencyCode})` : ""}`}
          subtitle={`Daily recognized billing vs refunds & churn (${windowDays}d UTC)`}
          legend={[
            { label: "Gross Volume", color: "#10b981" },
            { label: "Churn / Refunds", color: "#f43f5e" },
          ]}
          empty={!hasRevenueActivity}
          emptyTitle="No revenue or churn data"
          emptyDescription={`No billing events recorded in the last ${windowDays} days.`}
        >
          <div style={{ width: "100%", height: 280 }}>
            <ResponsiveContainer>
              <AreaChart
                data={chartData}
                margin={{ top: 10, right: 8, left: 0, bottom: 0 }}
              >
                <defs>
                  <linearGradient id="pulseopsRevGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0.0} />
                  </linearGradient>
                  <linearGradient id="pulseopsChurnGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.22} />
                    <stop offset="95%" stopColor="#f43f5e" stopOpacity={0.0} />
                  </linearGradient>
                </defs>
                <CartesianGrid
                  vertical={false}
                  stroke="rgba(255,255,255,0.06)"
                  strokeDasharray="4 4"
                />
                <XAxis
                  dataKey="label"
                  stroke="#52525b"
                  tickLine={false}
                  axisLine={{ stroke: "rgba(255,255,255,0.08)" }}
                  fontSize={13}
                  tick={{ fill: "#a1a1aa" }}
                  minTickGap={30}
                />
                <YAxis
                  stroke="#52525b"
                  tickLine={false}
                  axisLine={false}
                  fontSize={13}
                  tick={{ fill: "#a1a1aa" }}
                  tickFormatter={(val: number) =>
                    formatCompactMoneyAxis(val, activeCurrencyCode)
                  }
                  width={68}
                />
                <Tooltip content={<CustomRevenueTooltip currency={activeCurrencyCode} />} />
                <Area
                  type="monotone"
                  dataKey="revenueMajor"
                  name="Gross Volume"
                  stroke="#10b981"
                  strokeWidth={2}
                  fill="url(#pulseopsRevGrad)"
                  activeDot={{ r: 4, fill: "#10b981", stroke: "#0d0d0f", strokeWidth: 2 }}
                />
                <Area
                  type="monotone"
                  dataKey="churnMajor"
                  name="Churn / Refunds"
                  stroke="#f43f5e"
                  strokeWidth={1.75}
                  fill="url(#pulseopsChurnGrad)"
                  activeDot={{ r: 4, fill: "#f43f5e", stroke: "#0d0d0f", strokeWidth: 2 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </ChartPanel>

        <ChartPanel
          title="Engineering Delivery Velocity"
          subtitle={`Merged pull requests vs issue flow (${windowDays}d UTC)`}
          legend={[
            { label: "PRs Merged", color: "#0ea5e9" },
            { label: "Issues Opened", color: "#f59e0b" },
            { label: "Issues Closed", color: "#10b981" },
          ]}
          empty={!hasEngActivity}
          emptyTitle="No engineering activity"
          emptyDescription={`No PR or issue events recorded in the last ${windowDays} days.`}
        >
          <div style={{ width: "100%", height: 280 }}>
            <ResponsiveContainer>
              <BarChart
                data={chartData}
                margin={{ top: 10, right: 8, left: -12, bottom: 0 }}
                barGap={2}
              >
                <CartesianGrid
                  vertical={false}
                  stroke="rgba(255,255,255,0.06)"
                  strokeDasharray="4 4"
                />
                <XAxis
                  dataKey="label"
                  stroke="#52525b"
                  tickLine={false}
                  axisLine={{ stroke: "rgba(255,255,255,0.08)" }}
                  fontSize={13}
                  tick={{ fill: "#a1a1aa" }}
                  minTickGap={30}
                />
                <YAxis
                  stroke="#52525b"
                  tickLine={false}
                  axisLine={false}
                  fontSize={13}
                  tick={{ fill: "#a1a1aa" }}
                  allowDecimals={false}
                  width={38}
                />
                <Tooltip
                  content={<CustomEngTooltip />}
                  cursor={{ fill: "rgba(255, 255, 255, 0.03)" }}
                />
                <Bar
                  dataKey="prs_merged"
                  name="PRs Merged"
                  fill="#0ea5e9"
                  radius={[3, 3, 0, 0]}
                  maxBarSize={14}
                />
                <Bar
                  dataKey="issues_opened"
                  name="Issues Opened"
                  fill="#f59e0b"
                  radius={[3, 3, 0, 0]}
                  maxBarSize={14}
                />
                <Bar
                  dataKey="issues_closed"
                  name="Issues Closed"
                  fill="#10b981"
                  radius={[3, 3, 0, 0]}
                  maxBarSize={14}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartPanel>
      </section>
    </>
  );
}
