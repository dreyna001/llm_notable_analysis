import { afterEach, describe, expect, it, vi } from "vitest";
import { resetPortalAuthBuildConfigCache } from "../auth/authConfig";
import {
  ApiError,
  INVALID_RESPONSE_STATUS,
  PORTAL_AUTH_TOKEN_STORAGE_KEY,
  fetchCase,
  fetchCases,
  setPortalAuthErrorHandler,
  setPortalAuthToken,
  setPortalTokenProvider,
} from "./client";
import { INVALID_RESPONSE_MESSAGE } from "./responseSchemas";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("fetchCase response validation", () => {
  afterEach(() => {
    resetPortalAuthBuildConfigCache();
    vi.unstubAllGlobals();
  });

  it("returns validated case detail payloads", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          case_id: "case-1",
          metadata: {
            processed_at: "2026-06-04T00:00:00Z",
            expires_at: "2026-07-04T00:00:00Z",
            retrieval_status: "indexed",
            source_completeness: "complete",
          },
          alert_payload: { notable_id: "abc-123" },
          analysis: null,
          report_md_path: "/reports/case-1.md",
          report_html_path: null,
          content_bounds: {
            alert_payload_truncated: false,
            analysis_truncated: false,
            alert_payload_total_keys: 1,
            analysis_total_keys: 0,
            raw_sections: ["alert_payload", "analysis"],
          },
        }),
      ),
    );

    await expect(fetchCase("case-1")).resolves.toMatchObject({
      case_id: "case-1",
      analysis: null,
    });
  });

  it("rejects malformed case detail payloads with a controlled API error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          case_id: "case-1",
          metadata: {
            processed_at: "2026-06-04T00:00:00Z",
            expires_at: "2026-07-04T00:00:00Z",
            retrieval_status: "indexed",
            source_completeness: "complete",
          },
          alert_payload: { notable_id: "abc-123" },
          analysis: "not-an-object",
          report_md_path: "/reports/case-1.md",
          report_html_path: null,
          content_bounds: {
            alert_payload_truncated: false,
            analysis_truncated: false,
            alert_payload_total_keys: 1,
            analysis_total_keys: 0,
            raw_sections: ["alert_payload", "analysis"],
          },
        }),
      ),
    );

    await expect(fetchCase("case-1")).rejects.toEqual(
      new ApiError(
        INVALID_RESPONSE_STATUS,
        INVALID_RESPONSE_MESSAGE,
        "invalid_response",
      ),
    );
  });

  it("aborts in-flight fetchCase requests when the signal is cancelled", async () => {
    const controller = new AbortController();
    vi.stubGlobal(
      "fetch",
      vi.fn((_input, init?: RequestInit) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        }),
      ),
    );

    const pending = fetchCase("case-1", { signal: controller.signal });
    controller.abort();

    await expect(pending).rejects.toEqual(
      new ApiError(0, "Request cancelled.", "cancelled"),
    );
  });
});

describe("fetchCases request cancellation", () => {
  afterEach(() => {
    window.sessionStorage.clear();
    window.localStorage.clear();
    setPortalTokenProvider(null);
    setPortalAuthErrorHandler(null);
    resetPortalAuthBuildConfigCache();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.stubEnv("VITE_PORTAL_AUTH_MODE", "manual");
  });

  it("passes AbortSignal through to fetch", async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn(async () =>
      jsonResponse({
        items: [],
        limit: 50,
        has_more: false,
        next_cursor: null,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await fetchCases({ limit: 50 }, { signal: controller.signal });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/cases?limit=50",
      expect.objectContaining({
        headers: expect.any(Headers),
        signal: expect.any(AbortSignal),
      }),
    );
  });

  it("uses configured API base URL and JWT bearer token", async () => {
    vi.stubEnv("VITE_PORTAL_API_BASE_URL", "https://api.example.test/");
    setPortalAuthToken("jwt-token");
    const fetchMock = vi.fn(async () =>
      jsonResponse({
        items: [],
        limit: 50,
        has_more: false,
        next_cursor: null,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await fetchCases({ limit: 50 });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.example.test/api/cases?limit=50");
    expect((init?.headers as Headers).get("Authorization")).toBe("Bearer jwt-token");
  });

  it("falls back to local storage token for browser auth", async () => {
    window.localStorage.setItem(PORTAL_AUTH_TOKEN_STORAGE_KEY, "stored-token");
    const fetchMock = vi.fn(async () =>
      jsonResponse({
        items: [],
        limit: 50,
        has_more: false,
        next_cursor: null,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await fetchCases({ limit: 50 });

    const init = fetchMock.mock.calls[0][1];
    expect((init?.headers as Headers).get("Authorization")).toBe(
      "Bearer stored-token",
    );
  });

  it("aborts in-flight fetchCases requests when the signal is cancelled", async () => {
    const controller = new AbortController();
    vi.stubGlobal(
      "fetch",
      vi.fn((_input, init?: RequestInit) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        }),
      ),
    );

    const pending = fetchCases({ limit: 50 }, { signal: controller.signal });
    controller.abort();

    await expect(pending).rejects.toEqual(
      new ApiError(0, "Request cancelled.", "cancelled"),
    );
  });

  it("uses the async token provider without reading manual storage", async () => {
    window.localStorage.setItem(PORTAL_AUTH_TOKEN_STORAGE_KEY, "stored-token");
    setPortalTokenProvider(async () => "provider-token");
    const fetchMock = vi.fn(async () =>
      jsonResponse({
        items: [],
        limit: 50,
        has_more: false,
        next_cursor: null,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await fetchCases({ limit: 50 });

    const init = fetchMock.mock.calls[0][1];
    expect((init?.headers as Headers).get("Authorization")).toBe(
      "Bearer provider-token",
    );
  });

  it("notifies the auth error handler for 401 and 403 responses", async () => {
    const handler = vi.fn();
    setPortalAuthErrorHandler(handler);
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse({ detail: "Unauthorized" }, 401))
        .mockResolvedValueOnce(jsonResponse({ detail: "Forbidden" }, 403)),
    );

    await expect(fetchCases({ limit: 50 })).rejects.toBeInstanceOf(ApiError);
    await expect(fetchCases({ limit: 50 })).rejects.toBeInstanceOf(ApiError);

    expect(handler).toHaveBeenNthCalledWith(1, "unauthorized");
    expect(handler).toHaveBeenNthCalledWith(2, "forbidden");
  });
});
