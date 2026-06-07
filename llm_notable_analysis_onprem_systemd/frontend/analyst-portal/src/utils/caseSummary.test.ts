import { describe, expect, it } from "vitest";
import type { CaseDetail } from "../types";
import { caseDetailToSummary } from "./caseSummary";

const baseDetail: CaseDetail = {
  case_id: "case-1",
  metadata: {
    processed_at: "2026-06-04T00:00:00Z",
    expires_at: "2026-07-04T00:00:00Z",
    retrieval_status: "not_indexed",
    source_completeness: "missing_analysis",
  },
  alert_payload: {
    search_name: "Suspicious PowerShell",
  },
  analysis: null,
  report_md_path: null,
  report_html_path: null,
};

describe("caseDetailToSummary", () => {
  it("summarizes cases that have no structured analysis", () => {
    expect(caseDetailToSummary(baseDetail)).toEqual({
      case_id: "case-1",
      processed_at: "2026-06-04T00:00:00Z",
      expires_at: "2026-07-04T00:00:00Z",
      verdict: null,
      confidence: null,
      search_name: "Suspicious PowerShell",
      retrieval_status: "not_indexed",
      source_completeness: "missing_analysis",
    });
  });

  it("reads verdict and confidence from alert reconciliation when present", () => {
    const detail: CaseDetail = {
      ...baseDetail,
      metadata: {
        ...baseDetail.metadata,
        retrieval_status: "ready",
        source_completeness: "complete",
      },
      analysis: {
        alert_reconciliation: {
          verdict: "likely_malicious",
          confidence: "0.82",
        },
      },
    };

    expect(caseDetailToSummary(detail)).toMatchObject({
      verdict: "likely_malicious",
      confidence: 0.82,
    });
  });
});
