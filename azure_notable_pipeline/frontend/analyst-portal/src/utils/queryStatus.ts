/** Maps stored investigation query status values into analyst-readable labels. */
export function queryStatusLabel(status: string | null | undefined): string {
  if (!status) {
    return "Unknown";
  }
  const normalized = status.trim().toLowerCase();
  const labels: Record<string, string> = {
    executed: "Executed",
    success: "Executed",
    denied: "Denied",
    failed: "Failed",
    skipped: "Skipped",
    attempted: "Attempted",
    not_run: "Not run",
    unknown: "Unknown",
  };
  return labels[normalized] ?? normalized.replace(/_/g, " ");
}
