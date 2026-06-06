import type { CaseDetail, CaseSummary } from "../types";

export function alertNameFromCaseDetail(detail: CaseDetail): string | null {
  const payload = detail.alert_payload;
  for (const key of [
    "search_name",
    "searchName",
    "rule_name",
    "rule",
    "signature",
    "title",
  ]) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return null;
}

export function caseDetailToSummary(detail: CaseDetail): CaseSummary {
  const analysis = detail.analysis;
  return {
    case_id: detail.case_id,
    processed_at: detail.metadata.processed_at,
    expires_at: detail.metadata.expires_at,
    verdict:
      typeof analysis.verdict === "string"
        ? analysis.verdict
        : typeof analysis.final_verdict === "string"
          ? analysis.final_verdict
          : null,
    confidence:
      typeof analysis.confidence === "string" ? analysis.confidence : null,
    search_name: alertNameFromCaseDetail(detail),
    retrieval_status: detail.metadata.retrieval_status,
    source_completeness: detail.metadata.source_completeness,
  };
}
