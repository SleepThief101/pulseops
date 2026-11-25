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

const DEFAULT_TIMEOUT_MS = 45_000;
const TRANSIENT_HTTP_STATUSES = new Set([502, 503, 504]);

export class ApiError extends Error {
  status: number;
  requestId: string | null;
  isTransient: boolean;

  constructor(
    message: string,
    status: number,
    requestId: string | null = null,
    isTransient = false
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.requestId = requestId;
    this.isTransient = isTransient;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchWithTimeout(
  url: string,
  options: RequestInit,
  timeoutMs = DEFAULT_TIMEOUT_MS
): Promise<Response> {
  if (typeof AbortController === "undefined" || options.signal) {
    return fetch(url, options);
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function performRequest(
  path: string,
  options: RequestInit = {},
  token: string | null = null,
  onUnauthorized?: () => void
): Promise<Response> {
  const headers = new Headers(options.headers || {});
  if (!headers.has("Content-Type") && options.body && typeof options.body === "string") {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const method = (options.method || "GET").toUpperCase();
  const canRetryGet = method === "GET";
  const maxAttempts = canRetryGet ? 2 : 1;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    let res: Response;
    try {
      res = await fetchWithTimeout(`${API_BASE_URL}${path}`, {
        ...options,
        headers,
      });
    } catch (err) {
      const timedOut = err instanceof Error && err.name === "AbortError";
      if (attempt < maxAttempts) {
        await sleep(1500);
        continue;
      }
      throw new ApiError(
        timedOut
          ? "Request timed out. The API server may be waking from free-tier sleep; please retry."
          : "Unable to reach the PulseOps API. If using free-tier hosting, it may be waking up.",
        0,
        null,
        true
      );
    }

    const requestId = res.headers.get("X-Request-ID");

    if (!res.ok) {
      if (res.status === 401 && onUnauthorized) {
        onUnauthorized();
      }
      if (attempt < maxAttempts && TRANSIENT_HTTP_STATUSES.has(res.status)) {
        await sleep(1500);
        continue;
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
      throw new ApiError(
        detail,
        res.status,
        requestId,
        TRANSIENT_HTTP_STATUSES.has(res.status)
      );
    }

    return res;
  }

  throw new ApiError("Request failed unexpectedly.", 0, null, true);
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  token: string | null = null,
  onUnauthorized?: () => void
): Promise<T> {
  const res = await performRequest(path, options, token, onUnauthorized);
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

export const apiClient = {
  warmUpHealth() {
    fetchWithTimeout(`${API_BASE_URL}/health`, { method: "GET" }, 10_000).catch(() => {
      // silent non-blocking cold-start wake ping
    });
  },

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
    onUnauthorized?: () => void,
    limit = 50,
    offset = 0
  ) {
    const params = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    if (source) params.set("source", source);
    if (eventType) params.set("event_type", eventType);
    return request<EventItem[]>(
      `/orgs/${orgId}/events?${params.toString()}`,
      {},
      token,
      onUnauthorized
    );
  },

  async exportEventsCsv(
    orgId: string,
    token: string,
    source?: string,
    eventType?: string,
    onUnauthorized?: () => void
  ): Promise<{ filename: string; csvText: string }> {
    const params = new URLSearchParams({ limit: "1000", days: "365" });
    if (source) params.set("source", source);
    if (eventType) params.set("event_type", eventType);
    const res = await performRequest(
      `/orgs/${orgId}/events/export?${params.toString()}`,
      {},
      token,
      onUnauthorized
    );
    const csvText = await res.text();
    const disp = res.headers.get("Content-Disposition") || "";
    const match = disp.match(/filename="([^"]+)"/i);
    return {
      filename: match ? match[1] : `pulseops-events-${orgId}.csv`,
      csvText,
    };
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
