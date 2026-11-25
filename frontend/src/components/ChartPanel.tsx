import type React from "react";
import { EmptyState } from "./EmptyState";

export interface ChartLegendItem {
  label: string;
  color: string;
}

interface ChartPanelProps {
  title: string;
  subtitle: string;
  legend: ChartLegendItem[];
  empty?: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
  children: React.ReactNode;
}

export function ChartPanel({
  title,
  subtitle,
  legend,
  empty = false,
  emptyTitle = "No data in window",
  emptyDescription,
  children,
}: ChartPanelProps) {
  return (
    <div className="chart-panel">
      <div className="chart-header">
        <div>
          <h2 className="chart-title">{title}</h2>
          <p className="chart-subtitle">{subtitle}</p>
        </div>
        <div className="chart-legend" aria-label="Chart legend">
          {legend.map((item) => (
            <span key={item.label} className="legend-item">
              <span
                className="status-dot"
                style={{ background: item.color }}
                aria-hidden="true"
              />
              {item.label}
            </span>
          ))}
        </div>
      </div>
      <div className="chart-body">
        {empty ? (
          <EmptyState
            title={emptyTitle}
            description={emptyDescription}
            minHeight={240}
          />
        ) : (
          children
        )}
      </div>
    </div>
  );
}
