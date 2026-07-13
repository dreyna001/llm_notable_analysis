/** Maps stored source_completeness values into analyst-readable labels. */
export function sourceCompletenessLabel(
  value: string | null | undefined,
): string {
  if (!value) {
    return "Loading";
  }
  const labels: Record<string, string> = {
    complete: "Complete",
    missing_analysis: "Structured analysis missing",
    missing_alert: "Alert payload missing",
    markdown_only: "Markdown report only",
  };
  return labels[value] ?? value.replace(/_/g, " ");
}
