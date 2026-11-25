import React from "react";
import { useAuth } from "../context/AuthContext";
import type { Role } from "../types/api";
import {
  CopilotIcon,
  EventsIcon,
  IntegrationsIcon,
  OverviewIcon,
  TeamIcon,
} from "./Icons";
import { PulseOpsLogo } from "./PulseOpsLogo";
import { type BadgeTone, StatusBadge } from "./StatusBadge";

export type NavTab = "dashboard" | "integrations" | "events" | "copilot" | "team";

interface LayoutProps {
  activeTab: NavTab;
  onSelectTab: (tab: NavTab) => void;
  windowDays: number;
  onChangeWindowDays: (days: number) => void;
  children: React.ReactNode;
}

const NAV_ITEMS: Array<{
  id: NavTab;
  label: string;
  title: string;
  subtitle: string;
  icon: React.ReactNode;
}> = [
  {
    id: "dashboard",
    label: "Overview",
    title: "Operations Overview",
    subtitle: "Revenue health, churn velocity, cycle time, and engineering throughput",
    icon: <OverviewIcon className="nav-icon" />,
  },
  {
    id: "events",
    label: "Events Stream",
    title: "Normalized Events Stream",
    subtitle: "Tenant-scoped billing, GitHub, and CSV ingestion timeline",
    icon: <EventsIcon className="nav-icon" />,
  },
  {
    id: "integrations",
    label: "Integrations & CSV",
    title: "Integrations & CSV Hub",
    subtitle: "Encrypted connector credentials, sync execution history, and spreadsheet imports",
    icon: <IntegrationsIcon className="nav-icon" />,
  },
  {
    id: "copilot",
    label: "AI Copilot",
    title: "AI Operations Copilot",
    subtitle: "Tenant-scoped operational briefings with human-in-the-loop action approvals",
    icon: <CopilotIcon className="nav-icon" />,
  },
  {
    id: "team",
    label: "Team & RBAC",
    title: "Team & Access Control",
    subtitle: "Organization membership directory and backend-enforced permissions",
    icon: <TeamIcon className="nav-icon" />,
  },
];

const WINDOW_OPTIONS = [
  { value: 7, label: "7D" },
  { value: 30, label: "30D" },
  { value: 90, label: "90D" },
];

export function roleBadgeTone(role: Role | string): BadgeTone {
  if (role === "owner") return "ok";
  if (role === "member") return "action";
  return "neutral";
}

export function roleBadgeClass(role: Role | string): string {
  if (role === "owner") return "badge badge-ok";
  if (role === "member") return "badge badge-action";
  return "badge";
}

export function Layout({
  activeTab,
  onSelectTab,
  windowDays,
  onChangeWindowDays,
  children,
}: LayoutProps) {
  const { user, organizations, activeOrg, setActiveOrgId, logout } = useAuth();
  const activeMeta = NAV_ITEMS.find((n) => n.id === activeTab) ?? NAV_ITEMS[0];
  const emailInitial = user?.email ? user.email.slice(0, 1).toUpperCase() : "P";

  return (
    <div className="app-layout">
      <a href="#main-content" className="skip-nav">
        Skip to content
      </a>

      <aside className="sidebar">
        <div className="sidebar-brand">
          <PulseOpsLogo size={20} subtitle="CONTROL TOWER" />
        </div>

        <nav className="sidebar-nav" aria-label="Main navigation">
          <div className="sidebar-section-label">Workspace</div>
          <div className="nav-list">
            {NAV_ITEMS.map((item) => {
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  aria-current={isActive ? "page" : undefined}
                  className={`nav-btn ${isActive ? "active" : ""}`}
                  onClick={() => onSelectTab(item.id)}
                >
                  {item.icon}
                  <span>{item.label}</span>
                </button>
              );
            })}
          </div>
        </nav>

        <div className="sidebar-footer">
          <div className="avatar-chip" aria-hidden="true">
            {emailInitial}
          </div>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div
              style={{
                fontSize: "0.84rem",
                fontWeight: 500,
                color: "var(--text-primary)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
              title={user?.email}
            >
              {user?.email}
            </div>
            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
              {activeOrg ? `${activeOrg.role} access` : "Authenticated"}
            </div>
          </div>
        </div>
      </aside>

      <div className="main-area">
        <header className="topbar">
          <div className="topbar-left">
            {organizations.length > 0 && (
              <select
                aria-label="Active Organization"
                className="select org-select"
                value={activeOrg?.organization_id ?? ""}
                onChange={(e) => setActiveOrgId(e.target.value)}
              >
                {organizations.map((org) => (
                  <option key={org.organization_id} value={org.organization_id}>
                    {org.organization_name}
                  </option>
                ))}
              </select>
            )}
            {activeOrg && (
              <StatusBadge tone={roleBadgeTone(activeOrg.role)} dot>
                {activeOrg.role}
              </StatusBadge>
            )}
          </div>

          <div className="row-actions">
            <div className="segmented" role="group" aria-label="Metrics Window">
              {WINDOW_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  aria-pressed={windowDays === opt.value}
                  className={`segmented-btn ${windowDays === opt.value ? "active" : ""}`}
                  onClick={() => onChangeWindowDays(opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>

            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={logout}
            >
              Sign Out
            </button>
          </div>
        </header>

        <main className="content" id="main-content">
          <div className="page-header">
            <div>
              <h1 className="page-title">{activeMeta.title}</h1>
              <p className="page-desc">{activeMeta.subtitle}</p>
            </div>
          </div>
          {children}
        </main>
      </div>
    </div>
  );
}
