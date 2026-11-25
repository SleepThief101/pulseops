import type React from "react";

interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  minHeight?: number;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  minHeight = 180,
}: EmptyStateProps) {
  return (
    <div className="empty-state" style={{ minHeight }}>
      {icon && <div className="empty-state-icon">{icon}</div>}
      <div className="empty-state-title">{title}</div>
      {description && <div className="empty-state-desc">{description}</div>}
      {action && <div style={{ marginTop: 10 }}>{action}</div>}
    </div>
  );
}
