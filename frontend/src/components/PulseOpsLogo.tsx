interface PulseOpsLogoProps {
  size?: number;
  showWordmark?: boolean;
  subtitle?: string;
  tone?: "inherit" | "dark" | "light";
}

/**
 * Reusable PulseOps brand mark combining an architectural control tower
 * observation deck and pylons with an integrated live signal pulse.
 */
export function PulseOpsMark({ size = 24 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      style={{ flexShrink: 0, display: "block" }}
    >
      {/* Beacon node */}
      <circle cx="12" cy="3.2" r="1.25" fill="var(--accent-action, #0ea5e9)" />
      {/* Control tower observation deck */}
      <path
        d="M4.5 7.5L6.75 5H17.25L19.5 7.5L17.75 10.75H6.25L4.5 7.5Z"
        stroke="currentColor"
        strokeWidth="1.55"
        strokeLinejoin="round"
      />
      {/* Live telemetry pulse motif */}
      <path
        d="M7.25 7.85H9.6L10.95 6L12.7 9.65L14.1 7.85H16.75"
        stroke="var(--accent-action, #0ea5e9)"
        strokeWidth="1.65"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Stepped structural tower pylons and foundation */}
      <path
        d="M8.25 10.75L7 20.25M15.75 10.75L17 20.25M4.75 20.25H19.25"
        stroke="currentColor"
        strokeWidth="1.55"
        strokeLinecap="round"
      />
      {/* Center telemetry spine */}
      <path
        d="M12 10.75V20.25"
        stroke="currentColor"
        strokeOpacity="0.35"
        strokeWidth="1.25"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function PulseOpsLogo({
  size = 24,
  showWordmark = true,
  subtitle = "OPERATIONS CONTROL TOWER",
  tone = "inherit",
}: PulseOpsLogoProps) {
  const isLight = tone === "light";
  const color = isLight
    ? "#0d0d0f"
    : tone === "dark"
      ? "#f2f2f3"
      : "var(--text-primary, currentColor)";

  return (
    <div className="brand-lockup" style={{ color, padding: 0 }} translate="no">
      <div
        className="brand-mark-badge"
        aria-hidden="true"
        style={
          isLight
            ? {
                background: "#f4f4f5",
                borderColor: "rgba(13, 13, 15, 0.14)",
                boxShadow: "none",
              }
            : undefined
        }
      >
        <PulseOpsMark size={size} />
      </div>
      {showWordmark && (
        <div>
          <div className="brand-title" style={{ color }}>
            PulseOps
          </div>
          {subtitle && (
            <div
              className="brand-tag"
              style={isLight ? { color: "#52525b" } : undefined}
            >
              {subtitle}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
