import { describe, expect, it } from "vitest";
import {
  parseCaseDetail,
  parseCaseListResponse,
  parseChatResponse,
  parsePortalCapabilities,
} from "./responseSchemas";

describe("parseCaseDetail", () => {
  const validCase = {
    case_id: "case-1",
    metadata: {
      processed_at: "2026-06-04T00:00:00Z",
      expires_at: "2026-07-04T00:00:00Z",
      retrieval_status: "indexed",
      source_completeness: "complete",
    },
    alert_payload: { notable_id: "abc-123" },
    analysis: {
      alert_reconciliation: { verdict: "likely_malicious" },
      competing_hypotheses: [],
    },
    report_md_path: "/reports/case-1.md",
    report_html_path: null,
  };

  it("accepts a well-formed case detail payload", () => {
    expect(parseCaseDetail(validCase)).toEqual(validCase);
  });

  it("accepts null analysis", () => {
    expect(parseCaseDetail({ ...validCase, analysis: null })).toEqual({
      ...validCase,
      analysis: null,
    });
  });

  it("rejects analysis delivered as a string", () => {
    expect(parseCaseDetail({ ...validCase, analysis: "bad" })).toBeNull();
  });

  it("rejects missing metadata", () => {
    expect(parseCaseDetail({ ...validCase, metadata: "bad" })).toBeNull();
  });
});

describe("parseCaseListResponse", () => {
  it("accepts a well-formed list payload", () => {
    expect(
      parseCaseListResponse({
        items: [
          {
            case_id: "case-1",
            processed_at: "2026-06-04T00:00:00Z",
            expires_at: "2026-07-04T00:00:00Z",
            verdict: null,
            confidence: null,
            search_name: null,
            retrieval_status: "pending",
            source_completeness: "complete",
          },
        ],
        limit: 50,
        has_more: false,
        next_cursor: null,
      }),
    ).not.toBeNull();
  });

  it("rejects payloads missing pagination fields", () => {
    expect(parseCaseListResponse({ items: [], limit: 50 })).toBeNull();
  });
});

describe("parsePortalCapabilities", () => {
  it("rejects partial capability payloads", () => {
    expect(parsePortalCapabilities({ case_qa_enabled: true })).toBeNull();
  });
});

describe("parseChatResponse", () => {
  it("rejects chat payloads missing answer_status", () => {
    expect(parseChatResponse({ answer: "hi", session_id: null })).toBeNull();
  });
});
