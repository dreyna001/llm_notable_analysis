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

export function resolveCaseDetailTab(
  tabParam: string | null,
  availableTabs: readonly CaseDetailTab[],
): CaseDetailTab {
  const fallback = availableTabs[0] ?? "overview";
  const parsed = parseCaseDetailTab(tabParam);
  if (!parsed) return fallback;
  return availableTabs.includes(parsed) ? parsed : fallback;
}

export function caseDetailTabNeedsUrlCleanup(
  tabParam: string | null,
  availableTabs: readonly CaseDetailTab[],
): boolean {
  if (!tabParam) return false;
  const parsed = parseCaseDetailTab(tabParam);
  return !parsed || !availableTabs.includes(parsed);
}
