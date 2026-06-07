import type { CaseDetail, CaseSummary } from "../types";

function asRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return {};
}

function numericOrNull(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

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
  const analysis = detail.analysis ?? {};
  const reconciliation = asRecord(analysis.alert_reconciliation);
  return {
    case_id: detail.case_id,
    processed_at: detail.metadata.processed_at,
    expires_at: detail.metadata.expires_at,
    verdict:
      typeof reconciliation.verdict === "string"
        ? reconciliation.verdict
        : typeof analysis.verdict === "string"
          ? analysis.verdict
          : typeof analysis.final_verdict === "string"
            ? analysis.final_verdict
            : null,
    confidence:
      numericOrNull(reconciliation.confidence) ??
      numericOrNull(analysis.confidence),
    search_name: alertNameFromCaseDetail(detail),
    retrieval_status: detail.metadata.retrieval_status,
    source_completeness: detail.metadata.source_completeness,
  };
}
