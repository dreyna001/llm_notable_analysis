import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  INVALID_RESPONSE_STATUS,
  fetchCase,
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
});
