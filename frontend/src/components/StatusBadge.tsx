import type React from "react";

export type BadgeTone = "ok" | "action" | "info" | "warn" | "err" | "ai" | "neutral";

interface StatusBadgeProps {
  tone?: BadgeTone;
  dot?: boolean;
  className?: string;
  children: React.ReactNode;
}

const TONE_CLASS: Record<BadgeTone, string> = {
  ok: "badge badge-ok",
  action: "badge badge-action",
  info: "badge badge-info",
  warn: "badge badge-warn",
  err: "badge badge-err",
  ai: "badge badge-ai",
  neutral: "badge",
};

const DOT_CLASS: Record<BadgeTone, string> = {
  ok: "status-dot dot-ok",
  action: "status-dot dot-action",
  info: "status-dot dot-info",
  warn: "status-dot dot-warn",
  err: "status-dot dot-err",
  ai: "status-dot dot-ai",
  neutral: "status-dot dot-muted",
};

export function StatusBadge({
  tone = "neutral",
  dot = false,
  className = "",
  children,
}: StatusBadgeProps) {
  return (
    <span className={`${TONE_CLASS[tone]}${className ? ` ${className}` : ""}`}>
      {dot && <span className={DOT_CLASS[tone]} aria-hidden="true" />}
      {children}
    </span>
  );
}
