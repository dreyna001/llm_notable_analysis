export type CasesListFilters = {
  start_date: string;
  end_date: string;
  verdict: string;
  case_id: string;
  search_name: string;
};

export type CasesEmptyStateAction = "clear_filters" | "clear_case_id";

export type CasesEmptyStateContent = {
  title: string;
  description: string;
  action?: CasesEmptyStateAction;
};

export function casesListHasActiveFilters(filters: CasesListFilters): boolean {
  return Boolean(
    filters.case_id.trim() ||
      filters.search_name.trim() ||
      filters.verdict.trim() ||
      filters.start_date.trim() ||
      filters.end_date.trim(),
  );
}

export function resolveCasesEmptyState(
  filters: CasesListFilters,
): CasesEmptyStateContent {
  const caseId = filters.case_id.trim();
  if (caseId) {
    return {
      title: "No case matches this ID",
      description:
        "Check the case ID spelling or remove it to browse all cases.",
      action: "clear_case_id",
    };
  }

  if (casesListHasActiveFilters(filters)) {
    return {
      title: "No cases match these filters",
      description:
        "Clear filters or widen the date range to see more retained cases.",
      action: "clear_filters",
    };
  }

  return {
    title: "No cases yet",
    description:
      "Cases appear here after analyzer processing and the retention window.",
  };
}
