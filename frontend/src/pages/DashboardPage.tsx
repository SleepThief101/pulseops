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
import { ArrowRightIcon } from "../components/Icons";
import { useAuth } from "../context/AuthContext";
import { ApiError, apiClient } from "../lib/api";
import { formatCurrencyCents, formatShortDate } from "../lib/format";
import type { MetricsSummary, MetricsTimeseriesPoint } from "../types/api";

interface DashboardPageProps {
  windowDays: number;
  onGoToIntegrations: () => void;
  onDrilldownEvents: (source: string) => void;
}

function formatCompactDollarAxis(value: number): string {
  if (value === 0) return "$0";
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token || !activeOrg) return;
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([
      apiClient.getMetricsSummary(activeOrg.organization_id, windowDays, token, logout),
      apiClient.getMetricsTimeseries(activeOrg.organization_id, windowDays, token, logout),
    ])
      .then(([sumRes, tsRes]) => {
        if (cancelled) return;
        setSummary(sumRes);
        setPoints(tsRes.points);
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
  }, [token, activeOrg, windowDays, logout]);

  if (!activeOrg) {
    return (
      <div className="panel panel-pad">
        Select or create an organization to view metrics.
      </div>
    );
  }

  if (loading) {
    return (
      <div className="panel panel-pad" style={{ color: "var(--text-secondary)" }}>
        Loading SaaS and engineering metrics...
      </div>
    );
  }

  if (error) {
    return (
      <div className="alert alert-err" role="alert">
        {error}
      </div>
    );
  }

  if (!summary) {
    return null;
  }

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

  return (
    <>
      {summary.total_events_in_window === 0 && (
        <div className="panel panel-pad row-actions" style={{ justifyContent: "space-between" }}>
          <div>
            <strong style={{ fontSize: "0.9rem" }}>
              No operational events synced in the last {windowDays} days.
            </strong>
            <div className="panel-subtitle">
              Connect Razorpay (Test/Mock), GitHub, or upload a CSV to populate live metrics.
            </div>
          </div>
          <button type="button" className="btn" onClick={onGoToIntegrations}>
            Connect Integrations
          </button>
        </div>
      )}

      {/* Connected 4-column KPI Rail */}
      <section className="kpi-rail" aria-label="Key Metrics">
        <div
          className="kpi-cell"
          role="button"
          tabIndex={0}
          onClick={() => onDrilldownEvents("razorpay")}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onDrilldownEvents("razorpay");
            }
          }}
        >
          <div className="kpi-cell-head">
            <span className="kpi-label">Net MRR ({windowDays}d)</span>
            <span className="badge badge-ok">Billing</span>
          </div>
          <div className="kpi-value">{formatCurrencyCents(summary.mrr_cents)}</div>
          <div className="kpi-meta">
            <span className="tabular">ARR {formatCurrencyCents(summary.arr_cents)}</span>
            <span className="kpi-drill">
              Inspect <ArrowRightIcon size={12} />
            </span>
          </div>
        </div>

        <div
          className="kpi-cell"
          role="button"
          tabIndex={0}
          onClick={() => onDrilldownEvents("razorpay")}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onDrilldownEvents("razorpay");
            }
          }}
        >
          <div className="kpi-cell-head">
            <span className="kpi-label">Churn Rate</span>
            <span
              className={`badge ${
                summary.churn_rate_pct > 15
                  ? "badge-err"
                  : summary.churn_rate_pct > 0
                    ? "badge-warn"
                    : "badge-ok"
              }`}
            >
              {summary.churned_subscriptions_count} churned
            </span>
          </div>
          <div className="kpi-value">{summary.churn_rate_pct}%</div>
          <div className="kpi-meta">
            <span className="tabular">
              {summary.active_subscribers_count} active subscribers
            </span>
            <span className="kpi-drill">
              Inspect <ArrowRightIcon size={12} />
            </span>
          </div>
        </div>

        <div
          className="kpi-cell"
          role="button"
          tabIndex={0}
          onClick={() => onDrilldownEvents("github")}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onDrilldownEvents("github");
            }
          }}
        >
          <div className="kpi-cell-head">
            <span className="kpi-label">Pull Requests</span>
            <span className="badge badge-info">GitHub</span>
          </div>
          <div className="kpi-value">{summary.prs_merged} merged</div>
          <div className="kpi-meta">
            <span className="tabular">
              {summary.prs_opened} opened
              {summary.avg_pr_cycle_time_hours !== null
                ? ` · ${summary.avg_pr_cycle_time_hours}h cycle`
                : ""}
            </span>
            <span className="kpi-drill">
              Inspect <ArrowRightIcon size={12} />
            </span>
          </div>
        </div>

        <div
          className="kpi-cell"
          role="button"
          tabIndex={0}
          onClick={() => onDrilldownEvents("github")}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onDrilldownEvents("github");
            }
          }}
        >
          <div className="kpi-cell-head">
            <span className="kpi-label">Open Issues</span>
            <span
              className={`badge ${
                summary.open_issues_count > 0 ? "badge-warn" : "badge-ok"
              }`}
            >
              {summary.issues_closed_count} closed
            </span>
          </div>
          <div className="kpi-value">{summary.open_issues_count}</div>
          <div className="kpi-meta">
            <span className="tabular">
              {summary.avg_issue_cycle_time_hours !== null
                ? `Avg cycle ${summary.avg_issue_cycle_time_hours}h`
                : "No closed cycle data"}
            </span>
            <span className="kpi-drill">
              Inspect <ArrowRightIcon size={12} />
            </span>
          </div>
        </div>
      </section>

      {/* Secondary Window Telemetry Strip */}
      <div className="telemetry-strip" aria-label="Window Telemetry Summary">
        <div className="telemetry-item">
          <span>Gross Revenue</span>
          <span className="telemetry-val">
            {formatCurrencyCents(summary.gross_revenue_cents)}
          </span>
        </div>
        <div className="telemetry-item">
          <span>Refunds</span>
          <span className="telemetry-val">
            {formatCurrencyCents(summary.refunded_cents)}
          </span>
        </div>
        <div className="telemetry-item">
          <span>Churned MRR</span>
          <span className="telemetry-val">
            {formatCurrencyCents(summary.churned_mrr_cents)}
          </span>
        </div>
        <div className="telemetry-item">
          <span>Events in {windowDays}d Window</span>
          <span className="telemetry-val">{summary.total_events_in_window}</span>
        </div>
      </div>

      {/* Deliberate Trend Charts */}
      <section className="grid-charts" aria-label="Trend Charts">
        <div className="panel">
          <div className="panel-header">
            <div>
              <h3 className="panel-title">Revenue &amp; Churn Trajectory</h3>
              <p className="panel-subtitle">Daily recognized billing vs refunds &amp; churn ({windowDays}d)</p>
            </div>
            <div className="chart-legend">
              <span className="legend-item">
                <span className="status-dot" style={{ background: "#10b981" }} />
                Revenue
              </span>
              <span className="legend-item">
                <span className="status-dot" style={{ background: "#f43f5e" }} />
                Churn / Refunds
              </span>
            </div>
          </div>
          <div className="panel-pad">
            {!hasRevenueActivity ? (
              <div
                style={{
                  height: 260,
                  display: "grid",
                  placeItems: "center",
                  color: "var(--text-muted)",
                  fontSize: "0.84rem",
                }}
              >
                No revenue or churn events recorded in the last {windowDays} days.
              </div>
            ) : (
              <div style={{ width: "100%", height: 260 }}>
                <ResponsiveContainer>
                  <AreaChart
                    data={chartData}
                    margin={{ top: 8, right: 8, left: -12, bottom: 0 }}
                  >
                    <defs>
                      <linearGradient id="pulseopsRevGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#10b981" stopOpacity={0.28} />
                        <stop offset="95%" stopColor="#10b981" stopOpacity={0.0} />
                      </linearGradient>
                      <linearGradient id="pulseopsChurnGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.26} />
                        <stop offset="95%" stopColor="#f43f5e" stopOpacity={0.0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid
                      vertical={false}
                      stroke="rgba(255,255,255,0.06)"
                      strokeDasharray="3 3"
                    />
                    <XAxis
                      dataKey="label"
                      stroke="#71717a"
                      tickLine={false}
                      axisLine={{ stroke: "rgba(255,255,255,0.08)" }}
                      fontSize={11}
                      minTickGap={26}
                    />
                    <YAxis
                      stroke="#71717a"
                      tickLine={false}
                      axisLine={false}
                      fontSize={11}
                      tickFormatter={formatCompactDollarAxis}
                    />
                    <Tooltip content={<CustomRevenueTooltip />} />
                    <Area
                      type="monotone"
                      dataKey="revenueDollars"
                      name="Revenue"
                      stroke="#10b981"
                      strokeWidth={2}
                      fill="url(#pulseopsRevGrad)"
                      activeDot={{ r: 4, fill: "#10b981", stroke: "#09090b", strokeWidth: 2 }}
                    />
                    <Area
                      type="monotone"
                      dataKey="churnDollars"
                      name="Churn / Refunds"
                      stroke="#f43f5e"
                      strokeWidth={1.75}
                      fill="url(#pulseopsChurnGrad)"
                      activeDot={{ r: 4, fill: "#f43f5e", stroke: "#09090b", strokeWidth: 2 }}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <div>
              <h3 className="panel-title">Engineering Delivery Velocity</h3>
              <p className="panel-subtitle">Merged pull requests vs issue flow ({windowDays}d)</p>
            </div>
            <div className="chart-legend">
              <span className="legend-item">
                <span className="status-dot" style={{ background: "#38bdf8" }} />
                PRs Merged
              </span>
              <span className="legend-item">
                <span className="status-dot" style={{ background: "#f59e0b" }} />
                Issues Opened
              </span>
              <span className="legend-item">
                <span className="status-dot" style={{ background: "#10b981" }} />
                Issues Closed
              </span>
            </div>
          </div>
          <div className="panel-pad">
            {!hasEngActivity ? (
              <div
                style={{
                  height: 260,
                  display: "grid",
                  placeItems: "center",
                  color: "var(--text-muted)",
                  fontSize: "0.84rem",
                }}
              >
                No PR or issue events recorded in the last {windowDays} days.
              </div>
            ) : (
              <div style={{ width: "100%", height: 260 }}>
                <ResponsiveContainer>
                  <BarChart
                    data={chartData}
                    margin={{ top: 8, right: 8, left: -18, bottom: 0 }}
                    barGap={2}
                  >
                    <CartesianGrid
                      vertical={false}
                      stroke="rgba(255,255,255,0.06)"
                      strokeDasharray="3 3"
                    />
                    <XAxis
                      dataKey="label"
                      stroke="#71717a"
                      tickLine={false}
                      axisLine={{ stroke: "rgba(255,255,255,0.08)" }}
                      fontSize={11}
                      minTickGap={26}
                    />
                    <YAxis
                      stroke="#71717a"
                      tickLine={false}
                      axisLine={false}
                      fontSize={11}
                      allowDecimals={false}
                    />
                    <Tooltip
                      content={<CustomEngTooltip />}
                      cursor={{ fill: "rgba(255, 255, 255, 0.03)" }}
                    />
                    <Bar
                      dataKey="prs_merged"
                      name="PRs Merged"
                      fill="#38bdf8"
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
            )}
          </div>
        </div>
      </section>
    </>
  );
}
