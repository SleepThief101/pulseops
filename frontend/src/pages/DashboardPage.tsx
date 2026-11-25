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
import { formatCurrencyCents, formatDateTime, formatShortDate } from "../lib/format";
import type {
  IntegrationItem,
  MetricsSummary,
  MetricsTimeseriesPoint,
} from "../types/api";

interface DashboardPageProps {
  windowDays: number;
  onGoToIntegrations: () => void;
  onDrilldownEvents: (source: string) => void;
}

function formatCompactDollarAxis(value: number): string {
  if (value === 0) return "$0";
  if (Math.abs(value) >= 1_000_000) {
    return `$${(value / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  }
  if (Math.abs(value) >= 1000) {
    return `$${(value / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  }
  return `$${value}`;
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
              style={{ background: entry.color || "var(--accent)" }}
            />
            {entry.name}
          </span>
          <span className="tabular" style={{ fontWeight: 600 }}>
            {formatCurrencyCents(Math.round(Number(entry.value || 0) * 100))}
          </span>
        </div>
      ))}
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
  const [summary, setSummary] = useState<MetricsSummary | null>(null);
  const [points, setPoints] = useState<MetricsTimeseriesPoint[]>([]);
  const [integrations, setIntegrations] = useState<IntegrationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);

  useEffect(() => {
    if (!token || !activeOrg) return;
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([
      apiClient.getMetricsSummary(activeOrg.organization_id, windowDays, token, logout),
      apiClient.getMetricsTimeseries(activeOrg.organization_id, windowDays, token, logout),
      apiClient
        .listIntegrations(activeOrg.organization_id, token, logout)
        .catch(() => [] as IntegrationItem[]),
    ])
      .then(([sumRes, tsRes, intsRes]) => {
        if (cancelled) return;
        setSummary(sumRes);
        setPoints(tsRes.points);
        setIntegrations(intsRes);
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
  }, [token, activeOrg, windowDays, reloadTick, logout]);

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

  const chartData = points.map((p) => ({
    ...p,
    label: formatShortDate(p.date),
    revenueDollars: Number((p.revenue_cents / 100).toFixed(2)),
    churnDollars: Number((p.churn_cents / 100).toFixed(2)),
  }));

  const hasRevenueActivity = chartData.some(
    (p) => p.revenueDollars > 0 || p.churnDollars > 0
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
              No operational events synced in the last {windowDays} days.
            </div>
            <div className="page-desc" style={{ margin: 0 }}>
              Connect Razorpay, GitHub, or upload a CSV to populate live metrics.
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
          label={`Net MRR (${windowDays}d)`}
          value={formatCurrencyCents(summary.mrr_cents)}
          badgeText="Billing"
          badgeTone="ok"
          meta={`ARR ${formatCurrencyCents(summary.arr_cents)}`}
          onClick={() => onDrilldownEvents("razorpay")}
        />

        <KpiCard
          label="Churn Rate"
          value={`${summary.churn_rate_pct}%`}
          badgeText={`${summary.churned_subscriptions_count} churned`}
          badgeTone={churnBadgeTone}
          meta={`${summary.active_subscribers_count} active subscribers`}
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

      {/* Secondary Financials & Operational Health Split */}
      <section className="ops-health-grid" aria-label="Window Financials and Health">
        <div className="telemetry-strip" aria-label="Window Financial Summary">
          <div className="telemetry-item">
            <span className="telemetry-label">Gross Revenue</span>
            <span className="telemetry-val">
              {formatCurrencyCents(summary.gross_revenue_cents)}
            </span>
          </div>
          <div className="telemetry-item">
            <span className="telemetry-label">Refunds</span>
            <span className="telemetry-val">
              {formatCurrencyCents(summary.refunded_cents)}
            </span>
          </div>
          <div className="telemetry-item">
            <span className="telemetry-label">Churned MRR</span>
            <span className="telemetry-val">
              {formatCurrencyCents(summary.churned_mrr_cents)}
            </span>
          </div>
          <div className="telemetry-item">
            <span className="telemetry-label">Events ({windowDays}d)</span>
            <span className="telemetry-val">{summary.total_events_in_window}</span>
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
          title="Revenue & Churn Trajectory"
          subtitle={`Daily recognized billing vs refunds & churn (${windowDays}d)`}
          legend={[
            { label: "Revenue", color: "#10b981" },
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
                margin={{ top: 10, right: 8, left: -4, bottom: 0 }}
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
                  tickFormatter={formatCompactDollarAxis}
                  width={56}
                />
                <Tooltip content={<CustomRevenueTooltip />} />
                <Area
                  type="monotone"
                  dataKey="revenueDollars"
                  name="Revenue"
                  stroke="#10b981"
                  strokeWidth={2}
                  fill="url(#pulseopsRevGrad)"
                  activeDot={{ r: 4, fill: "#10b981", stroke: "#0d0d0f", strokeWidth: 2 }}
                />
                <Area
                  type="monotone"
                  dataKey="churnDollars"
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
          subtitle={`Merged pull requests vs issue flow (${windowDays}d)`}
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
