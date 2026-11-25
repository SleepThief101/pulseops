import type {
  CopilotChatResponse,
  CopilotProposal,
  EventIngestResult,
  EventItem,
  IntegrationItem,
  IntegrationSyncResponse,
  MemberItem,
  MetricsSummary,
  MetricsTimeseries,
  RegisterResponse,
  Role,
  SyncRunItem,
  TokenResponse,
  UserOrganization,
  UserProfile,
} from "../types/api";

export function resolveApiBaseUrl(env?: {
  PROD?: boolean;
  VITE_API_URL?: string;
}): string {
  const configured = env?.VITE_API_URL ? String(env.VITE_API_URL).trim() : "";
  if (env?.PROD) {
    if (!configured) {
      throw new Error(
        "VITE_API_URL must be configured for production builds (cannot fall back to localhost)."
      );
    }
    if (/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?(\/|$)/i.test(configured)) {
      throw new Error(
        "VITE_API_URL cannot point to localhost or 127.0.0.1 in production."
      );
    }
    return configured.replace(/\/+$/, "");
  }
  return (configured || "http://localhost:8000").replace(/\/+$/, "");
}

export const API_BASE_URL = resolveApiBaseUrl(
  typeof import.meta !== "undefined" ? import.meta.env : undefined
);

export class ApiError extends Error {
  status: number;
  requestId: string | null;

  constructor(message: string, status: number, requestId: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.requestId = requestId;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  token: string | null = null,
  onUnauthorized?: () => void
): Promise<T> {
  const headers = new Headers(options.headers || {});
  if (!headers.has("Content-Type") && options.body && typeof options.body === "string") {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  const requestId = res.headers.get("X-Request-ID");

  if (!res.ok) {
    if (res.status === 401 && onUnauthorized) {
      onUnauthorized();
    }
    let detail = `Request failed (${res.status})`;
    try {
      const errBody = await res.json();
      if (errBody && typeof errBody.detail === "string") {
        detail = errBody.detail;
      }
    } catch {
      // ignore non-JSON error body
    }
    throw new ApiError(detail, res.status, requestId);
  }

  if (res.status === 204) {
    return undefined as T;
  }

  return (await res.json()) as T;
}

export const apiClient = {
  register(email: string, password: string, organizationName: string) {
    return request<RegisterResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify({
        email,
        password,
        organization_name: organizationName,
      }),
    });
  },

  login(email: string, password: string) {
    return request<TokenResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  },

  getMe(token: string, onUnauthorized?: () => void) {
    return request<UserProfile>("/me", {}, token, onUnauthorized);
  },

  getMyOrganizations(token: string, onUnauthorized?: () => void) {
    return request<UserOrganization[]>("/me/organizations", {}, token, onUnauthorized);
  },

  getMetricsSummary(orgId: string, days: number, token: string, onUnauthorized?: () => void) {
    return request<MetricsSummary>(
      `/orgs/${orgId}/metrics/summary?days=${days}`,
      {},
      token,
      onUnauthorized
    );
  },

  getMetricsTimeseries(
    orgId: string,
    days: number,
    token: string,
    onUnauthorized?: () => void
  ) {
    return request<MetricsTimeseries>(
      `/orgs/${orgId}/metrics/timeseries?days=${days}`,
      {},
      token,
      onUnauthorized
    );
  },

  listEvents(
    orgId: string,
    token: string,
    source?: string,
    eventType?: string,
    onUnauthorized?: () => void
  ) {
    const params = new URLSearchParams({ limit: "100" });
    if (source) params.set("source", source);
    if (eventType) params.set("event_type", eventType);
    return request<EventItem[]>(
      `/orgs/${orgId}/events?${params.toString()}`,
      {},
      token,
      onUnauthorized
    );
  },

  listIntegrations(orgId: string, token: string, onUnauthorized?: () => void) {
    return request<IntegrationItem[]>(
      `/orgs/${orgId}/integrations`,
      {},
      token,
      onUnauthorized
    );
  },

  connectIntegration(
    orgId: string,
    provider: string,
    credentials: Record<string, unknown>,
    token: string,
    onUnauthorized?: () => void
  ) {
    return request<IntegrationItem>(
      `/orgs/${orgId}/integrations`,
      {
        method: "POST",
        body: JSON.stringify({ provider, credentials }),
      },
      token,
      onUnauthorized
    );
  },

  syncIntegration(
    orgId: string,
    integrationId: string,
    fullSync: boolean,
    token: string,
    onUnauthorized?: () => void
  ) {
    return request<IntegrationSyncResponse>(
      `/orgs/${orgId}/integrations/${integrationId}/sync?full_sync=${fullSync}`,
      { method: "POST" },
      token,
      onUnauthorized
    );
  },

  deleteIntegration(
    orgId: string,
    integrationId: string,
    token: string,
    onUnauthorized?: () => void
  ) {
    return request<void>(
      `/orgs/${orgId}/integrations/${integrationId}`,
      { method: "DELETE" },
      token,
      onUnauthorized
    );
  },

  listSyncRuns(orgId: string, token: string, onUnauthorized?: () => void) {
    return request<SyncRunItem[]>(
      `/orgs/${orgId}/sync-runs`,
      {},
      token,
      onUnauthorized
    );
  },

  importCsv(
    orgId: string,
    csvText: string,
    token: string,
    onUnauthorized?: () => void
  ) {
    return request<EventIngestResult>(
      `/orgs/${orgId}/imports/csv`,
      {
        method: "POST",
        body: JSON.stringify({ csv_text: csvText }),
      },
      token,
      onUnauthorized
    );
  },

  listMembers(orgId: string, token: string, onUnauthorized?: () => void) {
    return request<MemberItem[]>(
      `/orgs/${orgId}/members`,
      {},
      token,
      onUnauthorized
    );
  },

  addMember(
    orgId: string,
    email: string,
    role: Role,
    token: string,
    onUnauthorized?: () => void
  ) {
    return request<MemberItem>(
      `/orgs/${orgId}/members`,
      {
        method: "POST",
        body: JSON.stringify({ email, role }),
      },
      token,
      onUnauthorized
    );
  },

  sendCopilotMessage(
    orgId: string,
    message: string,
    token: string,
    onUnauthorized?: () => void
  ) {
    return request<CopilotChatResponse>(
      `/orgs/${orgId}/copilot/chat`,
      {
        method: "POST",
        body: JSON.stringify({ message }),
      },
      token,
      onUnauthorized
    );
  },

  listProposals(orgId: string, token: string, onUnauthorized?: () => void) {
    return request<CopilotProposal[]>(
      `/orgs/${orgId}/copilot/proposals`,
      {},
      token,
      onUnauthorized
    );
  },

  decideProposal(
    orgId: string,
    proposalId: string,
    decision: "approve" | "reject",
    token: string,
    onUnauthorized?: () => void
  ) {
    return request<CopilotProposal>(
      `/orgs/${orgId}/copilot/proposals/${proposalId}/decision`,
      {
        method: "POST",
        body: JSON.stringify({ decision }),
      },
      token,
      onUnauthorized
    );
  },
};
