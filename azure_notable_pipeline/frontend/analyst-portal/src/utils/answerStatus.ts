/** Maps stored chat answer_status values into analyst-readable labels. */
export function answerStatusLabel(status: string | null | undefined): string {
  if (!status) {
    return "Unknown";
  }
  const normalized = status.trim().toLowerCase();
  const labels: Record<string, string> = {
    answered: "Answered",
    unknown: "Insufficient evidence",
    refused: "Refused",
  };
  return labels[normalized] ?? normalized.replace(/_/g, " ");
}

export function shouldShowAnswerStatus(status: string | null | undefined): boolean {
  const normalized = status?.trim().toLowerCase();
  return normalized === "unknown" || normalized === "refused";
}
