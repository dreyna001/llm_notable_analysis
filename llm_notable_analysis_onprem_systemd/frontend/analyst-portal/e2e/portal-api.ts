import type { APIRequestContext } from "@playwright/test";

export type CaseSummary = {
  case_id: string;
  processed_at: string | null;
  verdict: string | null;
  search_name: string | null;
  retrieval_status: string;
  source_completeness: string;
};

export type CaseDetail = {
  case_id: string;
  metadata: {
    processed_at: string | null;
    retrieval_status: string;
    source_completeness: string;
  };
  alert_payload: Record<string, unknown>;
  analysis: Record<string, unknown>;
};

export type PortalCapabilities = {
  case_qa_enabled: boolean;
  global_retrieval_enabled: boolean;
  chat_history_enabled: boolean;
  general_knowledge_enabled: boolean;
  case_retention_days?: number;
};

export type PortalFixture = {
  capabilities: PortalCapabilities;
  caseSummary: CaseSummary;
  caseDetail: CaseDetail;
  expectedTabLabels: string[];
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asTextList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => (typeof item === "string" ? item.trim() : ""))
    .filter(Boolean);
}

function alertField(detail: CaseDetail, key: string): string {
  const payload = detail.alert_payload;
  const raw = payload[key];
  if (typeof raw === "string" && raw.trim()) {
    return raw.trim();
  }
  return "";
}

function expectedTabLabels(detail: CaseDetail): string[] {
  const analysis = detail.analysis ?? {};
  const reconciliation = asRecord(analysis.alert_reconciliation);
  const hypotheses = asArray(analysis.competing_hypotheses).filter(
    (item) => Object.keys(asRecord(item)).length > 0,
  );
  const actions = analysis.actions;
  const hasActions =
    (actions &&
      typeof actions === "object" &&
      Object.values(asRecord(actions)).some((value) => asTextList(value).length > 0)) ||
    asTextList(reconciliation.recommended_actions).length > 0;
  const ttps = asArray(analysis.ttp_analysis).filter(
    (item) => Object.keys(asRecord(item)).length > 0,
  );
  const iocs = asRecord(analysis.ioc_extraction);
  const iocKeys = [
    "ip_addresses",
    "domains",
    "user_accounts",
    "hostnames",
    "process_names",
    "file_paths",
    "file_hashes",
    "event_ids",
    "urls",
  ];
  const hasIocs = iocKeys.some((key) => asTextList(iocs[key]).length > 0);
  const evidenceVsInference = asRecord(analysis.evidence_vs_inference);
  const hasEvidence =
    asTextList(evidenceVsInference.evidence).length > 0 ||
    asTextList(evidenceVsInference.inferences).length > 0 ||
    Object.keys(detail.alert_payload).length > 0;
  const querySection = asRecord(analysis.query_result_section);
  const hasQueries = Object.keys(querySection).length > 0;
  const hasServiceNow = Object.keys(asRecord(analysis.servicenow_section)).length > 0;
  const hasRaw = Boolean(analysis.poc_unstructured_output || analysis.raw_response);

  const tabs = ["Verdict"];
  if (hypotheses.length) tabs.push("Hypotheses");
  if (hasActions) tabs.push("Actions");
  if (ttps.length) tabs.push("TTPs");
  if (hasIocs) tabs.push("IOCs");
  if (hasEvidence) tabs.push("Evidence");
  if (hasQueries) tabs.push("Query Results");
  if (hasServiceNow) tabs.push("ServiceNow");
  if (hasRaw) tabs.push("Raw Output");
  tabs.push("Case Metadata");
  return tabs;
}

function normalizeVerdict(verdict: string | null | undefined): string {
  const text = String(verdict ?? "").toLowerCase().replace(/[\s-]+/g, "_");
  if (text.includes("malicious") || text.includes("true_positive")) {
    return "likely_malicious";
  }
  if (text.includes("benign") || text.includes("false_positive")) {
    return "likely_benign";
  }
  return "unknown";
}

export function verdictUiLabel(verdict: string | null | undefined): string {
  const labels: Record<string, string> = {
    likely_malicious: "Likely malicious",
    likely_benign: "Likely benign",
    unknown: "Unknown",
  };
  return labels[normalizeVerdict(verdict)] ?? "Unknown";
}

export { retrievalStatusLabel as retrievalUiLabel } from "../src/utils/retrievalStatus";
export { sourceCompletenessLabel as completenessUiLabel } from "../src/utils/sourceCompleteness";

export async function loadPortalFixture(
  request: APIRequestContext,
  caseId: string,
): Promise<PortalFixture> {
  const capabilitiesResponse = await request.get("/api/capabilities");
  if (!capabilitiesResponse.ok()) {
    throw new Error(`capabilities HTTP ${capabilitiesResponse.status()}`);
  }
  const capabilities = (await capabilitiesResponse.json()) as PortalCapabilities;

  const detailResponse = await request.get(
    `/api/cases/${encodeURIComponent(caseId)}`,
  );
  if (!detailResponse.ok()) {
    throw new Error(`case detail HTTP ${detailResponse.status()} for ${caseId}`);
  }
  const caseDetail = (await detailResponse.json()) as CaseDetail;

  const listResponse = await request.get("/api/cases?limit=50");
  if (!listResponse.ok()) {
    throw new Error(`case list HTTP ${listResponse.status()}`);
  }
  const listBody = (await listResponse.json()) as { items: CaseSummary[] };
  const caseSummary =
    listBody.items.find((item) => item.case_id === caseId) ??
    ({
      case_id: caseDetail.case_id,
      processed_at: caseDetail.metadata.processed_at,
      verdict: asRecord(caseDetail.analysis.alert_reconciliation).verdict as
        | string
        | null,
      search_name: alertField(caseDetail, "search_name") || null,
      retrieval_status: caseDetail.metadata.retrieval_status,
      source_completeness: caseDetail.metadata.source_completeness,
    } satisfies CaseSummary);

  return {
    capabilities,
    caseSummary,
    caseDetail,
    expectedTabLabels: expectedTabLabels(caseDetail),
  };
}

export function alertName(detail: CaseDetail): string {
  return (
    alertField(detail, "search_name") ||
    alertField(detail, "searchName") ||
    alertField(detail, "rule_name") ||
    detail.case_id
  );
}

export function reconciliationSummary(detail: CaseDetail): string {
  const reconciliation = asRecord(detail.analysis.alert_reconciliation);
  const summary = reconciliation.one_sentence_summary;
  return typeof summary === "string" ? summary.trim() : "";
}
