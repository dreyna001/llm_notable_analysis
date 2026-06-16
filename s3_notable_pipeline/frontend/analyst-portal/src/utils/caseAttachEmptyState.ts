export type CaseAttachEmptyStateContent = {
  title: string;
  description: string;
};

export function resolveCaseAttachEmptyState(
  query: string,
): CaseAttachEmptyStateContent {
  const trimmed = query.trim();
  if (trimmed) {
    return {
      title: "No cases match your search",
      description:
        "Try a different case ID or alert name, or browse the full case index.",
    };
  }

  return {
    title: "No cases available yet",
    description:
      "Cases appear here after analyzer processing. Browse the case index for retained summaries.",
  };
}
