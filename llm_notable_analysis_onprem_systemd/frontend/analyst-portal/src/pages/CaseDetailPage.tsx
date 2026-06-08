import { MessageSquare } from "lucide-react";
import {
  useEffect,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  CollapsibleDetailCard,
  DetailBulletList,
  DetailCard,
  DetailCardTitle,
  DetailCodeBlock,
  DetailDriverCol,
  DetailDriverGrid,
  DetailError,
  DetailHero,
  DetailHypothesisBlock,
  DetailKvGrid,
  DetailKvRow,
  DetailMetaGrid,
  DetailMetaTerm,
  DetailMetaValue,
  DetailMetric,
  DetailMetricGrid,
  DetailMiniTitle,
  DetailMuted,
  DetailPivotBlock,
  DetailProgressRow,
  DetailSectionLabel,
  DetailStack,
  DetailTwoCol,
  hypothesisChipClass,
  hypothesisTitleClass,
  InterpretationAssessmentBadge,
  InterpretationDeltaBadge,
  ttpScoreBadgeVariant,
} from "../components/case-detail/CaseDetailUi";
import { CaseArchiveNoticeBanner } from "../components/CaseArchiveNoticeBanner";
import { ApiError, fetchCase } from "../api/client";
import type { CaseDetail } from "../types";
import {
  caseDetailTabNeedsUrlCleanup,
  resolveCaseDetailTab,
  type CaseDetailTab,
} from "../utils/caseDetailTabs";
import { retrievalStatusLabel } from "../utils/retrievalStatus";
import { sourceCompletenessLabel } from "../utils/sourceCompleteness";
import { verdictLabel, verdictTone, type VerdictTone } from "../utils/verdict";

type AlertReconciliation = {
  verdict?: unknown;
  confidence?: unknown;
  one_sentence_summary?: unknown;
  decision_drivers?: unknown;
  recommended_actions?: unknown;
};

// Deterministic verdict -> threat color. Red is most malicious, green is least
// malicious; unknown verdicts stay amber.
const THREAT_COLOR: Record<VerdictTone, string> = {
  malicious: "#f87171",
  benign: "#4ade80",
  unknown: "#fbbf24",
};

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
  const value = detail?.analysis?.alert_reconciliation;
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

  function selectTab(tab: CaseDetailTab) {
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
  const threatColor = THREAT_COLOR[verdictTone(reconciliation.verdict)];
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
  const availableTabIds = tabs.map(([tab]) => tab);
  const availableTabsKey = availableTabIds.join(",");
  const activeTab = resolveCaseDetailTab(searchParams.get("tab"), availableTabIds);

  useEffect(() => {
    if (!detail) return;
    const tabParam = searchParams.get("tab");
    const availableTabs = availableTabsKey.split(",") as CaseDetailTab[];
    if (!caseDetailTabNeedsUrlCleanup(tabParam, availableTabs)) return;
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.delete("tab");
        return next;
      },
      { replace: true },
    );
  }, [detail, caseId, availableTabsKey, searchParams, setSearchParams]);

  return (
    <section className="space-y-6">
      <DetailHero
        caseId={caseId}
        chatLink={
          <Button asChild size="sm" variant="outline">
            <Link to={`/?case_id=${encodeURIComponent(caseId)}`}>
              <MessageSquare className="size-3.5" />
              Ask Assistant about this case
            </Link>
          </Button>
        }
        meta={[
          { label: "Notable name", value: searchName },
          { label: "Source ID", value: sourceId },
          { label: "Processed", value: detail?.metadata.processed_at ?? "loading" },
        ]}
      />

      {loading ? <DetailMuted>Loading case...</DetailMuted> : null}
      {error ? <DetailError>{error}</DetailError> : null}

      {detail?.metadata.archive_notices?.length ? (
        <CaseArchiveNoticeBanner notices={detail.metadata.archive_notices} />
      ) : null}

      {detail ? (
        <>
          <DetailMetricGrid>
            <DetailMetric
              label="Confidence"
              sub={verdict}
              value={confidence.metric}
              valueStyle={{ color: threatColor }}
            />
            <DetailMetric
              label="Chatbot readiness"
              sub="Retrievable in chatbot"
              value={retrievalStatusLabel(detail.metadata.retrieval_status)}
              valueStyle={{
                color: retrievalStatusColor(detail.metadata.retrieval_status),
              }}
            />
            <DetailMetric
              label="Analysis availability"
              sub="Structured analysis status"
              value={sourceCompletenessLabel(detail.metadata.source_completeness)}
              valueStyle={{
                color: completenessColor(detail.metadata.source_completeness),
              }}
            />
          </DetailMetricGrid>

          <Tabs
            value={activeTab}
            onValueChange={(value) => selectTab(value as CaseDetailTab)}
          >
            <TabsList>
              {tabs.map(([tab, label]) => (
                <TabsTrigger key={tab} value={tab}>
                  {label}
                </TabsTrigger>
              ))}
            </TabsList>

          <TabsContent value="overview">
            <div className="space-y-4">
              <DetailTwoCol>
                <DetailCard>
                  <DetailCardTitle>Confidence breakdown</DetailCardTitle>
                  <DetailProgressRow
                    color={threatColor}
                    label="Overall"
                    score={confidence.score}
                    width={confidence.width}
                  />
                  {summary ? (
                    <p className="mt-3 text-sm leading-relaxed text-foreground/90">
                      {summary}
                    </p>
                  ) : null}
                </DetailCard>

                <DetailCard>
                  <DetailCardTitle>Hypothesis summary</DetailCardTitle>
                  <div className="space-y-3">
                    {benignHypothesis ? (
                      <DetailHypothesisBlock
                        body={
                          asTextList(benignHypothesis.evidence_support).join("; ") ||
                          "No supporting evidence listed."
                        }
                        title={asText(benignHypothesis.hypothesis)}
                        variant="benign"
                      />
                    ) : null}
                    {adversaryHypothesis ? (
                      <DetailHypothesisBlock
                        body={
                          asTextList(adversaryHypothesis.evidence_support).join("; ") ||
                          "No supporting evidence listed."
                        }
                        title={asText(adversaryHypothesis.hypothesis)}
                        variant="adversary"
                      />
                    ) : null}
                    {!benignHypothesis && !adversaryHypothesis ? (
                      <DetailMuted>No hypothesis summary available.</DetailMuted>
                    ) : null}
                  </div>
                </DetailCard>
              </DetailTwoCol>

              <DetailCard>
                <DetailCardTitle>Decision drivers</DetailCardTitle>
                <DetailDriverGrid>
                  <DetailDriverCol title="Toward malicious" variant="malicious">
                    {driverGroups.malicious.length ? (
                      <DetailBulletList items={driverGroups.malicious} />
                    ) : (
                      <DetailMuted>No malicious drivers listed.</DetailMuted>
                    )}
                  </DetailDriverCol>
                  <DetailDriverCol title="Toward benign" variant="benign">
                    {driverGroups.benign.length ? (
                      <DetailBulletList items={driverGroups.benign} />
                    ) : (
                      <DetailMuted>No benign drivers listed.</DetailMuted>
                    )}
                  </DetailDriverCol>
                </DetailDriverGrid>
              </DetailCard>
            </div>
          </TabsContent>

          <TabsContent value="hypotheses">
            <DetailStack>
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
                  <CollapsibleDetailCard
                    chip={
                      <span className={hypothesisChipClass(type)}>{label}</span>
                    }
                    key={`${type}-${index}`}
                    open={isOpen}
                    title={asText(hypothesis.hypothesis)}
                    titleClassName={hypothesisTitleClass(type)}
                    onToggle={() => toggleOpenKey(setOpenHypotheses, key)}
                  >
                    <DetailMiniTitle titleClass="mini-title-support">
                      Evidence support
                    </DetailMiniTitle>
                    {asTextList(hypothesis.evidence_support).length ? (
                      <DetailBulletList
                        items={asTextList(hypothesis.evidence_support)}
                      />
                    ) : (
                      <DetailMuted>No supporting evidence listed.</DetailMuted>
                    )}
                    <DetailMiniTitle titleClass="mini-title-gap">
                      Evidence gaps
                    </DetailMiniTitle>
                    {asTextList(hypothesis.evidence_gaps).length ? (
                      <DetailBulletList items={asTextList(hypothesis.evidence_gaps)} />
                    ) : (
                      <DetailMuted>No evidence gaps listed.</DetailMuted>
                    )}
                    <DetailMiniTitle titleClass="mini-title-pivot">
                      Best pivots
                    </DetailMiniTitle>
                    <DetailPivotBlock>
                      {pivots.join(" | ") || "No pivots provided."}
                    </DetailPivotBlock>
                  </CollapsibleDetailCard>
                );
              })}
            </DetailStack>
          </TabsContent>

          <TabsContent value="actions">
            <DetailCard>
              <DetailCardTitle>Actions</DetailCardTitle>
              {groupedActions.map((group) =>
                group.items.length ? (
                  <div className="mb-4 last:mb-0" key={group.title}>
                    <DetailMiniTitle titleClass={group.titleClass}>
                      {group.title}
                    </DetailMiniTitle>
                    <DetailBulletList items={group.items} />
                  </div>
                ) : null,
              )}
            </DetailCard>
          </TabsContent>

          <TabsContent value="ttps">
            <div className="space-y-3">
              <DetailSectionLabel>MITRE ATT&amp;CK</DetailSectionLabel>
              <DetailStack>
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
                    <CollapsibleDetailCard
                      chip={
                        <span className={hypothesisChipClass("ttp")}>{ttpId}</span>
                      }
                      key={key}
                      open={isOpen}
                      title={ttpName}
                      titleClassName={hypothesisTitleClass("ttp")}
                      trailing={
                        <Badge variant={ttpScoreBadgeVariant(score.label)}>
                          {score.label}
                        </Badge>
                      }
                      onToggle={() => toggleOpenKey(setOpenTtps, key)}
                    >
                      <DetailProgressRow
                        color={score.color}
                        label="Confidence"
                        score={score.score}
                        width={score.width}
                      />
                      <DetailMiniTitle titleClass="mini-title-pivot">
                        Explanation
                      </DetailMiniTitle>
                      <p className="text-sm leading-relaxed text-foreground/90">
                        {explanation}
                      </p>
                      {uncertainty ? (
                        <>
                          <DetailMiniTitle titleClass="mini-title-uncertainty">
                            Uncertainty
                          </DetailMiniTitle>
                          <DetailBulletList items={[uncertainty]} />
                        </>
                      ) : null}
                      <DetailMiniTitle titleClass="mini-title-support">
                        Evidence fields
                      </DetailMiniTitle>
                      {evidenceRows.length ? (
                        <DetailKvGrid>
                          {evidenceRows.map(([label, value]) => (
                            <DetailKvRow key={`${label}-${value}`} label={label} value={value} />
                          ))}
                        </DetailKvGrid>
                      ) : (
                        <DetailMuted>No evidence fields listed.</DetailMuted>
                      )}
                    </CollapsibleDetailCard>
                  );
                })}
              </DetailStack>
            </div>
          </TabsContent>

          <TabsContent value="iocs">
            <DetailCard>
              <DetailCardTitle>Indicators of Compromise</DetailCardTitle>
              <DetailKvGrid>
                {IOC_FIELDS.map(([key, label]) => {
                  const values = asTextList(iocs[key]);
                  if (!values.length) return null;
                  return (
                    <DetailKvRow
                      key={key}
                      label={label}
                      value={values.join(", ")}
                    />
                  );
                })}
              </DetailKvGrid>
            </DetailCard>
          </TabsContent>

          <TabsContent value="evidence">
            <DetailCard>
              <DetailCardTitle>Raw evidence fields</DetailCardTitle>
              {Object.keys(detail.alert_payload).length ? (
                <DetailKvGrid>
                  {rawEvidenceRows(detail.alert_payload).map(([key, value, isDanger]) => (
                    <DetailKvRow
                      danger={isDanger}
                      key={key}
                      label={key}
                      value={value}
                    />
                  ))}
                </DetailKvGrid>
              ) : (
                <DetailMuted>No raw alert fields available.</DetailMuted>
              )}
            </DetailCard>
          </TabsContent>

          <TabsContent value="queries">
            <div className="space-y-4">
              <DetailMetricGrid>
                {(
                  [
                    ["Attempted", querySummary.attempted ?? 0],
                    ["Executed", querySummary.executed ?? 0],
                    ["Denied", querySummary.denied ?? 0],
                    ["Failed", querySummary.failed ?? 0],
                    ["Skipped", querySummary.skipped ?? 0],
                  ] as const
                ).map(([label, value]) => (
                  <DetailMetric
                    key={label}
                    label={label}
                    value={asText(value, "0")}
                  />
                ))}
              </DetailMetricGrid>
              {queryItems.length ? (
                <DetailStack>
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
                      <CollapsibleDetailCard
                        chip={
                          <span className={hypothesisChipClass(chipClass)}>
                            Query {index + 1}
                          </span>
                        }
                        key={key}
                        open={isOpen}
                        title={status}
                        titleClassName={hypothesisTitleClass(chipClass)}
                        onToggle={() => toggleOpenKey(setOpenQueries, key)}
                      >
                        <DetailMiniTitle titleClass="mini-title-pivot">
                          Query
                        </DetailMiniTitle>
                        <DetailPivotBlock>
                          {queryText || "No query text recorded."}
                        </DetailPivotBlock>
                        <DetailMiniTitle titleClass="mini-title-support">
                          Execution facts
                        </DetailMiniTitle>
                        <DetailKvGrid>
                          <DetailKvRow
                            label="Hypothesis"
                            value={hypothesisIndexLabel(query.hypothesis_index)}
                          />
                          <DetailKvRow label="Result count" value={resultCount} />
                          <DetailKvRow label="Reference" value={reference} />
                        </DetailKvGrid>
                        {message ? (
                          <>
                            <DetailMiniTitle titleClass="mini-title-gap">
                              Message
                            </DetailMiniTitle>
                            <p className="text-sm leading-relaxed text-foreground/90">
                              {message}
                            </p>
                          </>
                        ) : null}
                        {queryInterpretations.length ? (
                          <div className="space-y-3">
                            <DetailMiniTitle titleClass="mini-title-pivot">
                              Interpretation
                            </DetailMiniTitle>
                            {queryInterpretations.map((item, interpIndex) => {
                              const observations = asTextList(item.key_observations);
                              const gaps = asTextList(item.remaining_gaps);
                              return (
                                <DetailCard
                                  key={`${key}-interpretation-${interpIndex}`}
                                >
                                  <div className="mb-3 flex flex-wrap gap-2">
                                    <InterpretationAssessmentBadge
                                      assessment={item.assessment}
                                    />
                                    <InterpretationDeltaBadge
                                      delta={item.confidence_delta}
                                    />
                                  </div>
                                  <p className="text-sm leading-relaxed text-foreground/90">
                                    {asText(item.rationale, "No rationale provided.")}
                                  </p>
                                  <DetailDriverGrid>
                                    <DetailDriverCol
                                      title="Key observations"
                                      variant="benign"
                                    >
                                      {observations.length ? (
                                        <DetailBulletList items={observations} />
                                      ) : (
                                        <DetailMuted>
                                          No key observations listed.
                                        </DetailMuted>
                                      )}
                                    </DetailDriverCol>
                                    <DetailDriverCol
                                      title="Remaining gaps"
                                      variant="malicious"
                                    >
                                      {gaps.length ? (
                                        <DetailBulletList items={gaps} />
                                      ) : (
                                        <DetailMuted>
                                          No remaining gaps listed.
                                        </DetailMuted>
                                      )}
                                    </DetailDriverCol>
                                  </DetailDriverGrid>
                                </DetailCard>
                              );
                            })}
                          </div>
                        ) : null}
                      </CollapsibleDetailCard>
                    );
                  })}
                </DetailStack>
              ) : (
                <DetailCard>
                  <DetailMuted>No query attempts recorded.</DetailMuted>
                </DetailCard>
              )}
            </div>
          </TabsContent>

          <TabsContent value="servicenow">
            <DetailCard>
              <DetailCardTitle>ServiceNow</DetailCardTitle>
              <DetailCodeBlock>
                {JSON.stringify(analysis.servicenow_section, null, 2)}
              </DetailCodeBlock>
            </DetailCard>
          </TabsContent>

          <TabsContent value="raw">
            <DetailCard>
              <DetailCardTitle>Raw Output</DetailCardTitle>
              <DetailCodeBlock>
                {String(analysis.raw_response ?? "")}
              </DetailCodeBlock>
            </DetailCard>
          </TabsContent>

          <TabsContent value="metadata">
            <DetailCard>
              <DetailCardTitle>Case Metadata</DetailCardTitle>
              <DetailMetaGrid>
                <DetailMetaTerm>Case ID</DetailMetaTerm>
                <DetailMetaValue>{detail.case_id}</DetailMetaValue>
                <DetailMetaTerm>Notable name</DetailMetaTerm>
                <DetailMetaValue>{searchName}</DetailMetaValue>
                <DetailMetaTerm>Expires</DetailMetaTerm>
                <DetailMetaValue>{detail.metadata.expires_at ?? "-"}</DetailMetaValue>
                <DetailMetaTerm>Report markdown</DetailMetaTerm>
                <DetailMetaValue>{detail.report_md_path ?? "-"}</DetailMetaValue>
              </DetailMetaGrid>
            </DetailCard>
          </TabsContent>

          </Tabs>
        </>
      ) : null}
    </section>
  );
}
