import {
  useEffect,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ApiError, fetchCase } from "../api/client";
import type { CaseDetail } from "../types";
import {
  parseCaseDetailTab,
  type CaseDetailTab,
} from "../utils/caseDetailTabs";

type AlertReconciliation = {
  verdict?: unknown;
  confidence?: unknown;
  one_sentence_summary?: unknown;
  decision_drivers?: unknown;
  recommended_actions?: unknown;
};

type ThreatLevel = "malicious" | "benign" | "unknown";

// Deterministic verdict -> threat color. Red is most malicious, green is least
// malicious; unknown verdicts stay amber.
const THREAT_COLOR: Record<ThreatLevel, string> = {
  malicious: "#f87171",
  benign: "#4ade80",
  unknown: "#fbbf24",
};

function normalizeVerdict(verdict: unknown): string {
  const text = String(verdict ?? "").toLowerCase().replace(/[\s-]+/g, "_");
  if (text.includes("malicious") || text.includes("true_positive")) {
    return "likely_malicious";
  }
  if (text.includes("benign") || text.includes("false_positive")) {
    return "likely_benign";
  }
  return "unknown";
}

function verdictThreatLevel(verdict: unknown): ThreatLevel {
  switch (normalizeVerdict(verdict)) {
    case "likely_malicious":
      return "malicious";
    case "likely_benign":
      return "benign";
    default:
      return "unknown";
  }
}

function verdictLabel(verdict: unknown): string {
  const labels: Record<string, string> = {
    likely_malicious: "Likely malicious",
    likely_benign: "Likely benign",
    unknown: "Unknown",
  };
  return labels[normalizeVerdict(verdict)];
}

function asText(value: unknown, fallback = "-"): string {
  if (typeof value === "string" && value.trim()) return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function asRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return {};
}

function asArray(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (value === null || value === undefined || value === "") return [];
  return [value];
}

function asTextList(value: unknown): string[] {
  return asArray(value)
    .map((item) => asText(item, ""))
    .filter(Boolean);
}

function toggleOpenKey(
  setter: Dispatch<SetStateAction<Set<string>>>,
  key: string,
) {
  setter((prev) => {
    const next = new Set(prev);
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
    }
    return next;
  });
}

function getAlertReconciliation(detail: CaseDetail | null): AlertReconciliation {
  const value = detail?.analysis.alert_reconciliation;
  if (value && typeof value === "object") {
    return value as AlertReconciliation;
  }
  return {};
}

function confidenceStats(value: unknown): {
  metric: string;
  score: string;
  width: number;
} {
  const raw = typeof value === "number" ? value : Number.parseFloat(String(value ?? ""));
  if (!Number.isFinite(raw)) {
    return { metric: "-", score: "-", width: 0 };
  }
  const percent = raw <= 1 ? raw * 100 : raw;
  const width = Math.max(0, Math.min(100, percent));
  return {
    metric: `${Math.round(width)}%`,
    score: raw <= 1 ? raw.toFixed(2) : `${Math.round(width)}%`,
    width,
  };
}

function splitTtpExplanation(value: unknown): {
  explanation: string;
  uncertainty: string;
} {
  const text = asText(value, "");
  if (!text) {
    return { explanation: "", uncertainty: "" };
  }
  const match = text.match(/^(.*?)(?:\s*Uncertainty:)\s*(.*)$/is);
  if (!match) {
    return { explanation: text, uncertainty: "" };
  }
  const explanation = match[1].trim().replace(/\.\s*$/, "");
  const uncertainty = match[2].trim();
  return {
    explanation: explanation || "No explanation provided.",
    uncertainty,
  };
}

function ttpScoreStats(ttp: Record<string, unknown>): {
  score: string;
  width: number;
  label: string;
  color: string;
  barColor: string;
} {
  const raw = Number.parseFloat(
    String(ttp.confidence_score ?? ttp.score ?? ttp.confidence ?? ""),
  );
  if (!Number.isFinite(raw)) {
    return {
      score: "-",
      width: 0,
      label: "Unknown",
      color: STATUS_MUTED,
      barColor: STATUS_MUTED,
    };
  }
  const normalized = raw <= 1 ? raw : raw / 100;
  const width = Math.max(0, Math.min(100, normalized * 100));
  if (normalized >= 0.8) {
    return {
      score: normalized.toFixed(2),
      width,
      label: "High",
      color: STATUS_RED,
      barColor: "#ef4444",
    };
  }
  if (normalized >= 0.5) {
    return {
      score: normalized.toFixed(2),
      width,
      label: "Medium",
      color: STATUS_AMBER,
      barColor: "#f59e0b",
    };
  }
  return {
    score: normalized.toFixed(2),
    width,
    label: "Low",
    color: STATUS_MUTED,
    barColor: "#475569",
  };
}

function recordField(record: Record<string, unknown>, key: string): string {
  return asText(record[key]);
}

function fieldLabel(key: string): string {
  const labels: Record<string, string> = {
    notable_id: "Notable ID",
    search_name: "Alert name",
    risk_score: "Risk Score",
    riskScore: "Risk Score",
    source_ip: "Source IP",
    sourceIPAddress: "Source IP Address",
    event_id: "Event ID",
    eventID: "Event ID",
    event_name: "Event Name",
    eventName: "Event Name",
    user: "User",
    host: "Host",
    hostname: "Hostname",
  };
  if (labels[key]) return labels[key];
  return key
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function rawEvidenceRows(record: Record<string, unknown>): Array<[string, string, boolean]> {
  return Object.entries(record).map(([key, value]) => {
    const fallback = value === undefined ? "-" : JSON.stringify(value);
    const text = asText(value, fallback || "-");
    const lowerKey = key.toLowerCase();
    const lowerValue = text.toLowerCase();
    const isDanger =
      lowerKey.includes("error") ||
      lowerValue.includes("accessdenied") ||
      lowerValue.includes("denied") ||
      lowerValue.includes("failed");
    return [fieldLabel(key), text, isDanger];
  });
}

function alertFieldValue(
  alertPayload: Record<string, unknown>,
  fieldKey: string,
): string | null {
  const key = fieldKey.trim();
  if (!key) return null;
  if (key in alertPayload) {
    return asText(alertPayload[key], "");
  }
  const camel = key.replace(/_([a-z])/g, (_, char: string) => char.toUpperCase());
  if (camel in alertPayload) {
    return asText(alertPayload[camel], "");
  }
  const lower = key.toLowerCase();
  for (const [candidate, value] of Object.entries(alertPayload)) {
    if (candidate.toLowerCase() === lower) {
      return asText(value, "");
    }
  }
  return null;
}

/** Map TTP evidence_fields entries to display rows (label, value). */
function ttpEvidenceRows(
  evidenceFields: string[],
  alertPayload: Record<string, unknown>,
): Array<[string, string]> {
  return evidenceFields.map((item) => {
    const trimmed = item.trim();
    if (!trimmed) {
      return ["-", "-"];
    }
    const equalsAt = trimmed.indexOf("=");
    if (equalsAt > 0) {
      const key = trimmed.slice(0, equalsAt).trim();
      const value = trimmed.slice(equalsAt + 1).trim();
      return [fieldLabel(key), value || "-"];
    }
    const resolved = alertFieldValue(alertPayload, trimmed);
    return [fieldLabel(trimmed), resolved || "-"];
  });
}

function splitDecisionDrivers(drivers: string[]): {
  malicious: string[];
  benign: string[];
} {
  const maliciousWords = [
    "malicious",
    "adversary",
    "suspicious",
    "exfil",
    "denied",
    "outside",
    "persistent",
    "credential",
  ];
  const benignWords = [
    "benign",
    "authorized",
    "approved",
    "scanner",
    "known",
    "managed",
    "expected",
    "legitimate",
  ];
  const malicious = drivers.filter((item) =>
    maliciousWords.some((word) => item.toLowerCase().includes(word)),
  );
  const benign = drivers.filter((item) =>
    benignWords.some((word) => item.toLowerCase().includes(word)),
  );
  if (!malicious.length && !benign.length && drivers.length) {
    const midpoint = Math.max(1, Math.floor(drivers.length / 2));
    return { malicious: drivers.slice(0, midpoint), benign: drivers.slice(midpoint) };
  }
  return { malicious, benign };
}

function firstHypothesis(
  hypotheses: Record<string, unknown>[],
  type: string,
): Record<string, unknown> | null {
  return (
    hypotheses.find(
      (item) => asText(item.hypothesis_type, "").toLowerCase() === type,
    ) ?? null
  );
}

type ActionGroup = {
  title: string;
  titleClass: string;
  items: string[];
};

function actionGroups(
  analysis: Record<string, unknown>,
  reconciliation: AlertReconciliation,
): ActionGroup[] {
  const actions = analysis.actions;
  if (actions && typeof actions === "object" && !Array.isArray(actions)) {
    const record = actions as Record<string, unknown>;
    const immediate = [
      ...asTextList(record.immediate),
      ...asTextList(record.Immediate),
    ];
    const short = [
      ...asTextList(record.short_term),
      ...asTextList(record["short-term"]),
      ...asTextList(record.short),
      ...asTextList(record["Short-term"]),
    ];
    const long = [
      ...asTextList(record.long_term),
      ...asTextList(record["long-term"]),
      ...asTextList(record.long),
      ...asTextList(record["Long-term"]),
    ];
    const known = new Set([...immediate, ...short, ...long]);
    const other: string[] = [];
    for (const value of Object.values(record)) {
      for (const item of asTextList(value)) {
        if (!known.has(item)) {
          other.push(item);
        }
      }
    }
    const groups: ActionGroup[] = [];
    if (immediate.length || other.length) {
      groups.push({
        title: "Immediate",
        titleClass: "mini-title-immediate",
        items: immediate.length ? immediate : other,
      });
    }
    if (short.length) {
      groups.push({
        title: "Short-term",
        titleClass: "mini-title-short",
        items: short,
      });
    }
    if (long.length) {
      groups.push({
        title: "Long-term",
        titleClass: "mini-title-long",
        items: long,
      });
    }
    return groups;
  }

  const flat = Array.isArray(actions)
    ? asTextList(actions)
    : asTextList(reconciliation.recommended_actions);
  if (!flat.length) {
    return [];
  }
  return [
    {
      title: "Immediate",
      titleClass: "mini-title-immediate",
      items: flat,
    },
  ];
}

const IOC_FIELDS: Array<[string, string]> = [
  ["ip_addresses", "IP Addresses"],
  ["domains", "Domains"],
  ["user_accounts", "User Accounts"],
  ["hostnames", "Hostnames"],
  ["process_names", "Processes"],
  ["file_paths", "File Paths"],
  ["file_hashes", "File Hashes"],
  ["event_ids", "Event IDs"],
  ["urls", "URLs"],
];

// Maps the stored retrieval_status into an analyst-readable label.
function retrievalStatusLabel(status: string | null | undefined): string {
  if (!status) return "Loading";
  const labels: Record<string, string> = {
    ready: "Indexed",
    pending: "Indexing pending",
    failed: "Indexing failed",
    not_indexed: "Not indexed",
  };
  return labels[status] ?? status.replace(/_/g, " ");
}

// Deterministic status colors shared by the metric cards: green = ready/complete,
// amber = pending/partial, red = failed, muted gray = not applicable or unknown.
const STATUS_GREEN = "#4ade80";
const STATUS_AMBER = "#fbbf24";
const STATUS_RED = "#f87171";
const STATUS_MUTED = "#94a3b8";

function queryStatusChipClass(status: string): "benign" | "adversary" | "unknown" {
  const lower = status.toLowerCase();
  if (lower === "executed" || lower === "success") {
    return "benign";
  }
  if (lower === "denied" || lower === "failed") {
    return "adversary";
  }
  return "unknown";
}

function hypothesisIndexLabel(index: unknown): string {
  if (typeof index === "number" && Number.isFinite(index)) {
    return String(index + 1);
  }
  return "n/a";
}

function interpretationLabel(value: unknown): string {
  const text = asText(value, "unknown").replace(/_/g, " ");
  return text.replace(/\b\w/g, (char) => char.toUpperCase());
}

function interpretationAssessmentPill(assessment: unknown): string {
  switch (asText(assessment, "unknown").toLowerCase()) {
    case "supports":
      return "interp-pill interp-pill-supports";
    case "weakens":
      return "interp-pill interp-pill-weakens";
    case "inconclusive":
      return "interp-pill interp-pill-inconclusive";
    default:
      return "interp-pill interp-pill-unknown";
  }
}

function interpretationDeltaPill(delta: unknown): string {
  switch (asText(delta, "unknown").toLowerCase()) {
    case "increase":
      return "interp-pill interp-pill-increase";
    case "decrease":
      return "interp-pill interp-pill-decrease";
    case "unchanged":
      return "interp-pill interp-pill-unchanged";
    default:
      return "interp-pill interp-pill-unknown";
  }
}

function interpretationsForQuery(
  query: Record<string, unknown>,
  interpretations: Record<string, unknown>[],
): Record<string, unknown>[] {
  const reference = asText(query.search_reference ?? query.search_id, "");
  return interpretations.filter((item) => {
    const refs = asTextList(item.source_query_refs);
    if (reference && refs.includes(reference)) {
      return true;
    }
    return (
      refs.length === 0 &&
      typeof item.hypothesis_index === "number" &&
      item.hypothesis_index === query.hypothesis_index
    );
  });
}

function retrievalStatusColor(status: string | null | undefined): string {
  switch (status) {
    case "ready":
      return STATUS_GREEN;
    case "pending":
      return STATUS_AMBER;
    case "failed":
      return STATUS_RED;
    default:
      return STATUS_MUTED;
  }
}

function completenessColor(value: string | null | undefined): string {
  const text = String(value ?? "").toLowerCase();
  if (text === "complete") return STATUS_GREEN;
  if (
    text.includes("missing") ||
    text.includes("partial") ||
    text.includes("incomplete")
  ) {
    return STATUS_AMBER;
  }
  return STATUS_MUTED;
}

export function CaseDetailPage() {
  const { caseId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<CaseDetailTab>("overview");
  const [openHypotheses, setOpenHypotheses] = useState<Set<string>>(
    () => new Set(["hypothesis-0"]),
  );
  const [openTtps, setOpenTtps] = useState<Set<string>>(() => new Set(["ttp-0"]));
  const [openQueries, setOpenQueries] = useState<Set<string>>(() => new Set(["query-0"]));

  useEffect(() => {
    setOpenHypotheses(new Set(["hypothesis-0"]));
    setOpenTtps(new Set(["ttp-0"]));
    setOpenQueries(new Set(["query-0"]));
  }, [caseId]);

  useEffect(() => {
    const tabFromUrl = parseCaseDetailTab(searchParams.get("tab"));
    setActiveTab(tabFromUrl ?? "overview");
  }, [caseId, searchParams]);

  function selectTab(tab: CaseDetailTab) {
    setActiveTab(tab);
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (tab === "overview") {
          next.delete("tab");
        } else {
          next.set("tab", tab);
        }
        return next;
      },
      { replace: true },
    );
  }

  useEffect(() => {
    if (!caseId) {
      setError("Missing case id.");
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetchCase(caseId)
      .then((payload) => {
        if (!cancelled) {
          setDetail(payload);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const message =
            err instanceof ApiError
              ? `${err.status}: ${err.message}`
              : err instanceof Error
                ? err.message
                : "Unknown error";
          setDetail(null);
          setError(message);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [caseId]);

  const analysis = detail?.analysis ?? {};
  const reconciliation = getAlertReconciliation(detail);
  const verdict = verdictLabel(reconciliation.verdict);
  const confidence = confidenceStats(reconciliation.confidence);
  const threatColor = THREAT_COLOR[verdictThreatLevel(reconciliation.verdict)];
  const summary = asText(reconciliation.one_sentence_summary, "");
  const searchName = detail ? recordField(detail.alert_payload, "search_name") : "-";
  const sourceId = detail ? recordField(detail.alert_payload, "notable_id") : "-";
  const drivers = asTextList(reconciliation.decision_drivers);
  const driverGroups = splitDecisionDrivers(drivers);
  const hypotheses = asArray(analysis.competing_hypotheses)
    .map(asRecord)
    .filter((item) => Object.keys(item).length > 0);
  let benignCount = 0;
  let adversaryCount = 0;
  const hypothesisCards = hypotheses.map((hypothesis, index) => {
    const type = asText(hypothesis.hypothesis_type, "unknown").toLowerCase();
    if (type === "benign") {
      benignCount += 1;
      return { hypothesis, index, key: `hypothesis-${index}`, label: `Benign ${benignCount}`, type };
    }
    if (type === "adversary") {
      adversaryCount += 1;
      return {
        hypothesis,
        index,
        key: `hypothesis-${index}`,
        label: `Adversary ${adversaryCount}`,
        type,
      };
    }
    return { hypothesis, index, key: `hypothesis-${index}`, label: "Unknown", type };
  });
  const benignHypothesis = firstHypothesis(hypotheses, "benign");
  const adversaryHypothesis = firstHypothesis(hypotheses, "adversary");
  const groupedActions = actionGroups(analysis, reconciliation);
  const hasActions = groupedActions.some((group) => group.items.length > 0);
  const ttps = asArray(analysis.ttp_analysis)
    .map(asRecord)
    .filter((item) => Object.keys(item).length > 0);
  const iocs = asRecord(analysis.ioc_extraction);
  const hasIocs = IOC_FIELDS.some(([key]) => asTextList(iocs[key]).length > 0);
  const evidenceVsInference = asRecord(analysis.evidence_vs_inference);
  const evidence = asTextList(evidenceVsInference.evidence);
  const inferences = asTextList(evidenceVsInference.inferences);
  const hasEvidenceTab =
    evidence.length > 0 || inferences.length > 0 || Object.keys(detail?.alert_payload ?? {}).length > 0;
  const querySection = asRecord(analysis.query_result_section);
  const querySummary = asRecord(querySection.summary);
  const queryItems = asArray(querySection.queries)
    .map(asRecord)
    .filter((item) => Object.keys(item).length > 0);
  const interpretationItems = asArray(analysis.query_result_interpretation)
    .map(asRecord)
    .filter((item) => Object.keys(item).length > 0);
  const hasQueryResults = Object.keys(querySection).length > 0;
  const hasServiceNow = Object.keys(asRecord(analysis.servicenow_section)).length > 0;
  const hasRawOutput = Boolean(analysis.poc_unstructured_output || analysis.raw_response);
  const tabs: Array<[CaseDetailTab, string]> = [
    ["overview", "Verdict"],
    ...(hypotheses.length ? [["hypotheses", "Hypotheses"] as [CaseDetailTab, string]] : []),
    ...(hasActions ? [["actions", "Actions"] as [CaseDetailTab, string]] : []),
    ...(ttps.length ? [["ttps", "TTPs"] as [CaseDetailTab, string]] : []),
    ...(hasIocs ? [["iocs", "IOCs"] as [CaseDetailTab, string]] : []),
    ...(hasEvidenceTab ? [["evidence", "Evidence"] as [CaseDetailTab, string]] : []),
    ...(hasQueryResults ? [["queries", "Query Results"] as [CaseDetailTab, string]] : []),
    ...(hasServiceNow ? [["servicenow", "ServiceNow"] as [CaseDetailTab, string]] : []),
    ...(hasRawOutput ? [["raw", "Raw Output"] as [CaseDetailTab, string]] : []),
    ["metadata", "Case Metadata"],
  ];

  return (
    <section className="case-detail-page">
      <div className="case-hero">
        <div className="case-hero-body">
          <div>
            <div className="eyebrow">Case reconciliation</div>
            <h1>{caseId}</h1>
            <p>Review the alert, Agent verdict, and source evidence.</p>
            <p className="case-hero-action">
              <Link
                className="button"
                rel="noreferrer"
                target="_blank"
                to={`/?case_id=${encodeURIComponent(caseId)}`}
              >
                Ask Assistant about this case
              </Link>
            </p>
          </div>
          <dl className="case-meta-strip">
            <div>
              <dt>Notable name</dt>
              <dd>{searchName}</dd>
            </div>
            <div>
              <dt>Source ID</dt>
              <dd>{sourceId}</dd>
            </div>
            <div>
              <dt>Processed</dt>
              <dd>{detail?.metadata.processed_at ?? "loading"}</dd>
            </div>
          </dl>
        </div>
      </div>

      {loading ? <p className="muted">Loading case...</p> : null}
      {error ? <p className="error">{error}</p> : null}

      {detail ? (
        <>
          <div className="metrics">
            <div className="metric">
              <div className="metric-label">Confidence</div>
              <div className="metric-value" style={{ color: threatColor }}>
                {confidence.metric}
              </div>
              <div className="metric-sub">{verdict}</div>
            </div>
            <div className="metric">
              <div className="metric-label">Chatbot readiness</div>
              <div
                className="metric-value"
                style={{ color: retrievalStatusColor(detail.metadata.retrieval_status) }}
              >
                {retrievalStatusLabel(detail.metadata.retrieval_status)}
              </div>
              <div className="metric-sub">Retrievable in chatbot</div>
            </div>
            <div className="metric">
              <div className="metric-label">Analysis availability</div>
              <div
                className="metric-value"
                style={{ color: completenessColor(detail.metadata.source_completeness) }}
              >
                {detail.metadata.source_completeness}
              </div>
              <div className="metric-sub">Structured analysis status</div>
            </div>
          </div>

          <div className="tabs">
            {tabs.map(([tab, label]) => (
              <button
                className={activeTab === tab ? "tab active" : "tab"}
                key={tab}
                type="button"
                onClick={() => selectTab(tab)}
              >
                {label}
              </button>
            ))}
          </div>

          {activeTab === "overview" ? (
            <>
              <div className="two-col">
                <div className="card">
                  <div className="card-title">Confidence breakdown</div>
                  <div className="conf-row">
                    <span className="conf-label">Overall</span>
                    <div className="bar-bg">
                      <div
                        className="bar-fill"
                        style={{
                          width: `${confidence.width}%`,
                          background: threatColor,
                        }}
                      />
                    </div>
                    <span className="conf-pct" style={{ color: threatColor }}>
                      {confidence.score}
                    </span>
                  </div>
                  {summary ? <p className="summary-note">{summary}</p> : null}
                </div>

                <div className="card">
                  <div className="card-title">Hypothesis summary</div>
                  {benignHypothesis ? (
                    <div className="hyp hyp-benign">
                      <div className="hyp-title">
                        {asText(benignHypothesis.hypothesis)}
                      </div>
                      <div className="hyp-body">
                        {asTextList(benignHypothesis.evidence_support).join("; ") ||
                          "No supporting evidence listed."}
                      </div>
                    </div>
                  ) : null}
                  {adversaryHypothesis ? (
                    <div className="hyp hyp-malicious">
                      <div className="hyp-title">
                        {asText(adversaryHypothesis.hypothesis)}
                      </div>
                      <div className="hyp-body">
                        {asTextList(adversaryHypothesis.evidence_support).join("; ") ||
                          "No supporting evidence listed."}
                      </div>
                    </div>
                  ) : null}
                  {!benignHypothesis && !adversaryHypothesis ? (
                    <p className="muted">No hypothesis summary available.</p>
                  ) : null}
                </div>
              </div>

              <div className="card">
                <div className="card-title">Decision drivers</div>
                <div className="driver-grid">
                  <div className="driver-col driver-malicious">
                    <h4>Toward malicious</h4>
                    {driverGroups.malicious.length ? (
                      <ul className="analysis-list">
                        {driverGroups.malicious.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    ) : (
                      <p className="muted">No malicious drivers listed.</p>
                    )}
                  </div>
                  <div className="driver-col driver-benign">
                    <h4>Toward benign</h4>
                    {driverGroups.benign.length ? (
                      <ul className="analysis-list">
                        {driverGroups.benign.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    ) : (
                      <p className="muted">No benign drivers listed.</p>
                    )}
                  </div>
                </div>
              </div>
            </>
          ) : null}

          {activeTab === "hypotheses" ? (
            <div className="hypothesis-stack">
              {hypothesisCards.map(({ hypothesis, index, key, label, type }) => {
                const isOpen = openHypotheses.has(key);
                const pivots = asArray(hypothesis.best_pivots).map((pivot) => {
                  const record = asRecord(pivot);
                  if (Object.keys(record).length) {
                    const fields = asTextList(record.key_fields).join(", ");
                    return `${asText(record.log_source, "Source")}: ${fields || "-"}`;
                  }
                  return asText(pivot);
                });
                return (
                  <div className="card hyp-card" key={`${type}-${index}`}>
                    <button
                      className="hyp-card-header"
                      type="button"
                      onClick={() => toggleOpenKey(setOpenHypotheses, key)}
                    >
                      <span className={`hyp-chip ${type}`}>
                        {label}
                      </span>
                      <span className={`hyp-card-title ${type}`}>
                        {asText(hypothesis.hypothesis)}
                      </span>
                      <span className={isOpen ? "hyp-chevron open" : "hyp-chevron"}>
                        v
                      </span>
                    </button>
                    {isOpen ? (
                      <div className="hyp-card-body">
                        <div className="mini-title mini-title-support">
                          Evidence support
                        </div>
                        {asTextList(hypothesis.evidence_support).length ? (
                          <ul className="hyp-list">
                            {asTextList(hypothesis.evidence_support).map((item, idx) => (
                              <li key={`${item}-${idx}`}>{item}</li>
                            ))}
                          </ul>
                        ) : (
                          <p className="muted">No supporting evidence listed.</p>
                        )}
                        <div className="mini-title mini-title-gap">Evidence gaps</div>
                        {asTextList(hypothesis.evidence_gaps).length ? (
                          <ul className="hyp-list">
                            {asTextList(hypothesis.evidence_gaps).map((item, idx) => (
                              <li key={`${item}-${idx}`}>{item}</li>
                            ))}
                          </ul>
                        ) : (
                          <p className="muted">No evidence gaps listed.</p>
                        )}
                        <div className="mini-title mini-title-pivot">Best pivots</div>
                        <div className="pivot-block">
                          {pivots.join(" | ") || "No pivots provided."}
                        </div>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          ) : null}

          {activeTab === "actions" ? (
            <div className="card">
              <div className="card-title">Actions</div>
              {groupedActions.map((group) =>
                group.items.length ? (
                  <div className="action-section" key={group.title}>
                    <div className={`mini-title ${group.titleClass}`}>{group.title}</div>
                    <ul className="hyp-list">
                      {group.items.map((item, idx) => (
                        <li key={`${group.title}-${idx}`}>{item}</li>
                      ))}
                    </ul>
                  </div>
                ) : null,
              )}
            </div>
          ) : null}

          {activeTab === "ttps" ? (
            <>
              <div className="analysis-section-label">MITRE ATT&amp;CK</div>
              <div className="ttp-stack">
                {ttps.map((ttp, index) => {
                  const key = `ttp-${index}`;
                  const isOpen = openTtps.has(key);
                  const ttpId = asText(ttp.ttp_id || ttp.technique_id || ttp.id, "Technique");
                  const ttpName = asText(ttp.ttp_name || ttp.technique_name || ttp.name);
                  const score = ttpScoreStats(ttp);
                  const evidenceFields = asTextList(ttp.evidence_fields || ttp.evidence);
                  const evidenceRows = ttpEvidenceRows(
                    evidenceFields,
                    detail?.alert_payload ?? {},
                  );
                  const { explanation, uncertainty } = splitTtpExplanation(
                    ttp.explanation || ttp.rationale,
                  );
                  return (
                    <div className="card hyp-card" key={key}>
                      <button
                        className="hyp-card-header"
                        type="button"
                        onClick={() => toggleOpenKey(setOpenTtps, key)}
                      >
                        <span className="hyp-chip ttp">{ttpId}</span>
                        <span className="hyp-card-title ttp">{ttpName}</span>
                        <span className={`ttp-pill ttp-pill-${score.label.toLowerCase()}`}>
                          {score.label}
                        </span>
                        <span className={isOpen ? "hyp-chevron open" : "hyp-chevron"}>
                          v
                        </span>
                      </button>
                      {isOpen ? (
                        <div className="hyp-card-body">
                          <div className="conf-row ttp-score-row">
                            <span className="conf-label">Confidence</span>
                            <div className="bar-bg ttp-bar-bg">
                              <div
                                className="bar-fill"
                                style={{
                                  width: `${score.width}%`,
                                  background: score.barColor,
                                }}
                              />
                            </div>
                            <span className="conf-pct" style={{ color: score.color }}>
                              {score.score}
                            </span>
                          </div>
                          <div className="mini-title mini-title-pivot">Explanation</div>
                          <p className="summary-note">{explanation}</p>
                          {uncertainty ? (
                            <>
                              <div className="mini-title mini-title-uncertainty">
                                Uncertainty
                              </div>
                              <ul className="hyp-list">
                                <li>{uncertainty}</li>
                              </ul>
                            </>
                          ) : null}
                          <div className="mini-title mini-title-support">Evidence fields</div>
                          {evidenceRows.length ? (
                            <div className="ttp-evidence-grid">
                              {evidenceRows.map(([label, value]) => (
                                <div className="kv-row" key={`${label}-${value}`}>
                                  <span className="kv-key">{label}</span>
                                  <span className="kv-value">{value}</span>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <p className="muted">No evidence fields listed.</p>
                          )}
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </>
          ) : null}

          {activeTab === "iocs" ? (
            <div className="card">
              <div className="card-title">Indicators of Compromise</div>
              <div className="kv-grid">
                {IOC_FIELDS.map(([key, label]) => {
                  const values = asTextList(iocs[key]);
                  if (!values.length) return null;
                  return (
                    <div className="kv-row" key={key}>
                      <span className="kv-key">{label}</span>
                      <span className="kv-value">{values.join(", ")}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : null}

          {activeTab === "evidence" ? (
            <div className="card">
              <div className="card-title">Raw evidence fields</div>
              {Object.keys(detail.alert_payload).length ? (
                <div className="kv-grid">
                  {rawEvidenceRows(detail.alert_payload).map(([key, value, isDanger]) => (
                    <div className="kv-row" key={key}>
                      <span className="kv-key">{key}</span>
                      <span className={isDanger ? "kv-value danger" : "kv-value"}>
                        {value}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="muted">No raw alert fields available.</p>
              )}
            </div>
          ) : null}

          {activeTab === "queries" ? (
            <>
              <div className="metrics">
                {(
                  [
                    ["Attempted", querySummary.attempted ?? 0],
                    ["Executed", querySummary.executed ?? 0],
                    ["Denied", querySummary.denied ?? 0],
                    ["Failed", querySummary.failed ?? 0],
                    ["Skipped", querySummary.skipped ?? 0],
                  ] as const
                ).map(([label, value]) => (
                  <div className="metric" key={label}>
                    <div className="metric-label">{label}</div>
                    <div className="metric-value">{asText(value, "0")}</div>
                  </div>
                ))}
              </div>
              {queryItems.length ? (
                <div className="hypothesis-stack">
                  {queryItems.map((query, index) => {
                    const key = `query-${index}`;
                    const isOpen = openQueries.has(key);
                    const status = asText(query.status, "unknown");
                    const chipClass = queryStatusChipClass(status);
                    const queryText = asText(query.query, "");
                    const reference = asText(
                      query.search_reference ?? query.search_id,
                      "n/a",
                    );
                    const resultCount = asText(query.result_count, "0");
                    const message = asText(query.message, "");
                    const queryInterpretations = interpretationsForQuery(
                      query,
                      interpretationItems,
                    );
                    return (
                      <div className="card hyp-card" key={key}>
                        <button
                          className="hyp-card-header"
                          type="button"
                          onClick={() => toggleOpenKey(setOpenQueries, key)}
                        >
                          <span className={`hyp-chip ${chipClass}`}>
                            Query {index + 1}
                          </span>
                          <span className={`hyp-card-title ${chipClass}`}>
                            {status}
                          </span>
                          <span className={isOpen ? "hyp-chevron open" : "hyp-chevron"}>
                            v
                          </span>
                        </button>
                        {isOpen ? (
                          <div className="hyp-card-body">
                            <div className="mini-title mini-title-pivot">Query</div>
                            <div className="pivot-block">
                              {queryText || "No query text recorded."}
                            </div>
                            <div className="mini-title mini-title-support">
                              Execution facts
                            </div>
                            <div className="ttp-evidence-grid">
                              <div className="kv-row">
                                <span className="kv-key">Hypothesis</span>
                                <span className="kv-value">
                                  {hypothesisIndexLabel(query.hypothesis_index)}
                                </span>
                              </div>
                              <div className="kv-row">
                                <span className="kv-key">Result count</span>
                                <span className="kv-value">{resultCount}</span>
                              </div>
                              <div className="kv-row">
                                <span className="kv-key">Reference</span>
                                <span className="kv-value">{reference}</span>
                              </div>
                            </div>
                            {message ? (
                              <>
                                <div className="mini-title mini-title-gap">Message</div>
                                <p className="summary-note">{message}</p>
                              </>
                            ) : null}
                            {queryInterpretations.length ? (
                              <div className="query-interpretation-block">
                                <div className="mini-title mini-title-pivot">
                                  Interpretation
                                </div>
                                {queryInterpretations.map((item, interpIndex) => {
                                  const observations = asTextList(item.key_observations);
                                  const gaps = asTextList(item.remaining_gaps);
                                  return (
                                    <div
                                      className="query-interpretation-card"
                                      key={`${key}-interpretation-${interpIndex}`}
                                    >
                                      <div className="interp-inline-header">
                                        <span
                                          className={interpretationAssessmentPill(
                                            item.assessment,
                                          )}
                                          title="Assessment"
                                        >
                                          {interpretationLabel(item.assessment)}
                                        </span>
                                        <span
                                          className={interpretationDeltaPill(
                                            item.confidence_delta,
                                          )}
                                          title="Confidence movement"
                                        >
                                          {interpretationLabel(item.confidence_delta)}
                                        </span>
                                      </div>
                                      <p className="summary-note">
                                        {asText(item.rationale, "No rationale provided.")}
                                      </p>
                                      <div className="driver-grid interp-driver-grid">
                                        <div className="driver-col driver-benign">
                                          <h4>Key observations</h4>
                                          {observations.length ? (
                                            <ul className="hyp-list">
                                              {observations.map((entry, idx) => (
                                                <li key={`${entry}-${idx}`}>{entry}</li>
                                              ))}
                                            </ul>
                                          ) : (
                                            <p className="muted">
                                              No key observations listed.
                                            </p>
                                          )}
                                        </div>
                                        <div className="driver-col driver-malicious">
                                          <h4>Remaining gaps</h4>
                                          {gaps.length ? (
                                            <ul className="hyp-list">
                                              {gaps.map((entry, idx) => (
                                                <li key={`${entry}-${idx}`}>{entry}</li>
                                              ))}
                                            </ul>
                                          ) : (
                                            <p className="muted">
                                              No remaining gaps listed.
                                            </p>
                                          )}
                                        </div>
                                      </div>
                                    </div>
                                  );
                                })}
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="card">
                  <p className="muted">No query attempts recorded.</p>
                </div>
              )}
            </>
          ) : null}

          {activeTab === "servicenow" ? (
            <div className="card">
              <div className="card-title">ServiceNow</div>
              <pre className="code-block">
                {JSON.stringify(analysis.servicenow_section, null, 2)}
              </pre>
            </div>
          ) : null}

          {activeTab === "raw" ? (
            <div className="card">
              <div className="card-title">Raw Output</div>
              <pre className="code-block">
                {String(analysis.raw_response ?? "")}
              </pre>
            </div>
          ) : null}

          {activeTab === "metadata" ? (
            <div className="card">
              <div className="card-title">Case Metadata</div>
              <dl className="meta-grid">
                <dt>Case ID</dt>
                <dd>{detail.case_id}</dd>
                <dt>Notable name</dt>
                <dd>{searchName}</dd>
                <dt>Expires</dt>
                <dd>{detail.metadata.expires_at ?? "-"}</dd>
                <dt>Report markdown</dt>
                <dd>{detail.report_md_path ?? "-"}</dd>
              </dl>
            </div>
          ) : null}

        </>
      ) : null}
    </section>
  );
}
