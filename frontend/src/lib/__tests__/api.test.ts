import { describe, expect, it, vi } from "vitest";
import { ApiError, apiClient, resolveApiBaseUrl } from "../api";

describe("resolveApiBaseUrl", () => {
  it("falls back to localhost in non-production environments", () => {
    expect(resolveApiBaseUrl({ PROD: false })).toBe("http://localhost:8000");
    expect(resolveApiBaseUrl({ PROD: false, VITE_API_URL: "http://127.0.0.1:8000/" })).toBe(
      "http://127.0.0.1:8000"
    );
  });

  it("rejects missing or localhost URLs in production builds", () => {
    expect(() => resolveApiBaseUrl({ PROD: true })).toThrow(/VITE_API_URL/);
    expect(() =>
      resolveApiBaseUrl({ PROD: true, VITE_API_URL: "http://localhost:8000" })
    ).toThrow(/localhost/);
    expect(
      resolveApiBaseUrl({ PROD: true, VITE_API_URL: "https://pulseops-api.onrender.com/" })
    ).toBe("https://pulseops-api.onrender.com");
  });
});

describe("apiClient", () => {
  it("attaches Authorization header and exposes X-Request-ID on error", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Unauthorized" }), {
        status: 401,
        headers: {
          "Content-Type": "application/json",
          "X-Request-ID": "req-uuid-123",
        },
      })
    );
    const onUnauthorized = vi.fn();

    await expect(apiClient.getMe("jwt-token", onUnauthorized)).rejects.toMatchObject({
      name: "ApiError",
      status: 401,
      requestId: "req-uuid-123",
    } satisfies Partial<ApiError>);

    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    const [, init] = fetchSpy.mock.calls[0];
    const headers = init?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer jwt-token");
    fetchSpy.mockRestore();
  });

  it("posts CSV text JSON payload to /orgs/{orgId}/imports/csv", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ total_received: 1, inserted_count: 1, skipped_count: 0 }),
        { status: 201, headers: { "Content-Type": "application/json" } }
      )
    );

    const csv = "event_type,occurred_at,amount_cents\nsubscription.charged,2026-11-25T10:00:00Z,9900";
    const res = await apiClient.importCsv("org-123", csv, "jwt-token");
    expect(res).toEqual({ total_received: 1, inserted_count: 1, skipped_count: 0 });

    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe("http://localhost:8000/orgs/org-123/imports/csv");
    expect(init?.method).toBe("POST");
    expect((init?.headers as Headers).get("Content-Type")).toBe("application/json");
    expect(init?.body).toBe(JSON.stringify({ csv_text: csv }));
    fetchSpy.mockRestore();
  });

  it("retries transient 503 GET cold-start responses and forwards pagination & CSV export filters", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Service waking up" }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify([]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      )
      .mockResolvedValueOnce(
        new Response("id,source\n1,razorpay\n", {
          status: 200,
          headers: {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": 'attachment; filename="pulseops-events-org-1.csv"',
          },
        })
      );

    const events = await apiClient.listEvents("org-1", "jwt-token", "razorpay", undefined, undefined, 51, 50);
    expect(events).toEqual([]);
    expect(fetchSpy.mock.calls[0][0]).toBe(
      "http://localhost:8000/orgs/org-1/events?limit=51&offset=50&source=razorpay"
    );

    const exported = await apiClient.exportEventsCsv("org-1", "jwt-token", "razorpay");
    expect(exported.filename).toBe("pulseops-events-org-1.csv");
    expect(exported.csvText).toContain("razorpay");
    fetchSpy.mockRestore();
  });
});
