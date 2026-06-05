export type CaseDetailTab =
  | "overview"
  | "hypotheses"
  | "actions"
  | "ttps"
  | "iocs"
  | "evidence"
  | "queries"
  | "servicenow"
  | "raw"
  | "metadata";

export const CASE_DETAIL_TABS: CaseDetailTab[] = [
  "overview",
  "hypotheses",
  "actions",
  "ttps",
  "iocs",
  "evidence",
  "queries",
  "servicenow",
  "raw",
  "metadata",
];

export function parseCaseDetailTab(value: string | null): CaseDetailTab | null {
  if (!value) return null;
  return CASE_DETAIL_TABS.includes(value as CaseDetailTab)
    ? (value as CaseDetailTab)
    : null;
}
