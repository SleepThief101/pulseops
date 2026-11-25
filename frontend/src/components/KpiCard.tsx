import type React from "react";
import { ArrowRightIcon } from "./Icons";
import { type BadgeTone, StatusBadge } from "./StatusBadge";

interface KpiCardProps {
  label: string;
  value: React.ReactNode;
  badgeText: string;
  badgeTone: BadgeTone;
  meta: React.ReactNode;
  drillLabel?: string;
  onClick: () => void;
}

export function KpiCard({
  label,
  value,
  badgeText,
  badgeTone,
  meta,
  drillLabel = "Inspect",
  onClick,
}: KpiCardProps) {
  return (
    <button type="button" className="kpi-card" onClick={onClick}>
      <div className="kpi-card-head">
        <span className="kpi-label">{label}</span>
        <StatusBadge tone={badgeTone}>{badgeText}</StatusBadge>
      </div>
      <div className="kpi-value">{value}</div>
      <div className="kpi-meta">
        <span className="tabular">{meta}</span>
        <span className="kpi-drill">
          {drillLabel} <ArrowRightIcon size={12} />
        </span>
      </div>
    </button>
  );
}
