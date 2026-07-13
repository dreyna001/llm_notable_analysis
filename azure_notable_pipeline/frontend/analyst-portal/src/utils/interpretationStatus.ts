/** Maps interpretation assessment enums into analyst-readable labels. */
export function interpretationAssessmentLabel(
  assessment: string | null | undefined,
): string {
  if (!assessment) {
    return "Unknown";
  }
  const normalized = assessment.trim().toLowerCase();
  const labels: Record<string, string> = {
    supports: "Supports hypothesis",
    weakens: "Weakens hypothesis",
    inconclusive: "Inconclusive",
    unknown: "Unknown",
  };
  return labels[normalized] ?? normalized.replace(/_/g, " ");
}

/** Maps interpretation confidence_delta enums into analyst-readable labels. */
export function interpretationDeltaLabel(delta: string | null | undefined): string {
  if (!delta) {
    return "Unknown";
  }
  const normalized = delta.trim().toLowerCase();
  const labels: Record<string, string> = {
    increase: "Confidence increased",
    decrease: "Confidence decreased",
    unchanged: "No change",
    unknown: "Unknown",
  };
  return labels[normalized] ?? normalized.replace(/_/g, " ");
}
