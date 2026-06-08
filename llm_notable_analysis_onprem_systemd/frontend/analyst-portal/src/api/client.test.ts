import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  INVALID_RESPONSE_STATUS,
  fetchCase,
  fetchCases,
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
    vi.unstubAllGlobals();
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
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
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
});
