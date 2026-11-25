export type Role = "owner" | "member" | "viewer";

export interface UserProfile {
  id: string;
  email: string;
  created_at: string;
}

export interface UserOrganization {
  organization_id: string;
  organization_name: string;
  role: Role;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface RegisterResponse {
  user_id: string;
  email: string;
  created_at: string;
  organization_id: string;
  organization_name: string;
  role: Role;
}

export interface MetricsSummary {
  organization_id: string;
  window_days: number;
  gross_revenue_cents: number;
  refunded_cents: number;
  churned_mrr_cents: number;
  mrr_cents: number;
  arr_cents: number;
  active_subscribers_count: number;
  churned_subscriptions_count: number;
  churn_rate_pct: number;
  prs_opened: number;
  prs_merged: number;
  open_issues_count: number;
  issues_closed_count: number;
  avg_issue_cycle_time_hours: number | null;
  avg_pr_cycle_time_hours: number | null;
  total_events_in_window: number;
}

export interface MetricsTimeseriesPoint {
  date: string;
  revenue_cents: number;
  churn_cents: number;
  prs_opened: number;
  prs_merged: number;
  issues_opened: number;
  issues_closed: number;
}

export interface MetricsTimeseries {
  organization_id: string;
  window_days: number;
  points: MetricsTimeseriesPoint[];
}

export interface IntegrationItem {
  id: string;
  organization_id: string;
  provider: string;
  status: string;
  last_synced_at: string | null;
  created_at: string;
}

export interface IntegrationSyncResponse {
  integration_id: string;
  provider: string;
  status: string;
  total_received: number;
  inserted_count: number;
  skipped_count: number;
  sync_run_id: string | null;
  queued: boolean;
}

export interface SyncRunItem {
  id: string;
  organization_id: string;
  integration_id: string;
  status: string;
  events_received: number;
  events_inserted: number;
  events_skipped: number;
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface EventItem {
  id: string;
  organization_id: string;
  integration_id: string | null;
  source: string;
  external_id: string;
  event_type: string;
  occurred_at: string;
  amount_cents: number | null;
  currency: string | null;
  actor: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface EventIngestResult {
  total_received: number;
  inserted_count: number;
  skipped_count: number;
}

export interface MemberItem {
  membership_id: string;
  user_id: string;
  organization_id: string;
  email: string;
  role: Role;
  created_at: string;
}

export interface CopilotProposal {
  id: string;
  organization_id: string;
  proposed_by_user_id: string;
  tool_name: string;
  title: string;
  description: string;
  arguments: Record<string, unknown>;
  status: "pending" | "approved" | "rejected" | "executed" | "failed";
  reviewed_by_user_id: string | null;
  reviewed_at: string | null;
  execution_result: Record<string, unknown> | null;
  created_at: string;
}

export interface CopilotChatResponse {
  reply: string;
  model_used: string;
  fallback_mode: boolean;
  tool_calls_executed: Array<{
    tool_name: string;
    result: Record<string, unknown>;
  }>;
  pending_proposals: CopilotProposal[];
}
