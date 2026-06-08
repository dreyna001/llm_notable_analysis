/** Maps stored retrieval_status values into analyst-readable labels. */
export function retrievalStatusLabel(status: string | null | undefined): string {
  if (!status) {
    return "Loading";
  }
  const labels: Record<string, string> = {
    ready: "Indexed",
    pending: "Indexing pending",
    failed: "Indexing failed",
    not_indexed: "Not indexed",
  };
  return labels[status] ?? status.replace(/_/g, " ");
}
