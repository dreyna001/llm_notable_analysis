export type VerdictTone = "malicious" | "benign" | "unknown";

export function normalizeVerdict(verdict: unknown): string {
  const text = String(verdict ?? "").toLowerCase().replace(/[\s-]+/g, "_");
  if (text.includes("malicious") || text.includes("true_positive")) {
    return "likely_malicious";
  }
  if (text.includes("benign") || text.includes("false_positive")) {
    return "likely_benign";
  }
  return "unknown";
}

export function verdictLabel(verdict: unknown): string {
  const labels: Record<string, string> = {
    likely_malicious: "Likely malicious",
    likely_benign: "Likely benign",
    unknown: "Unknown",
  };
  return labels[normalizeVerdict(verdict)];
}

export function verdictTone(verdict: unknown): VerdictTone {
  switch (normalizeVerdict(verdict)) {
    case "likely_malicious":
      return "malicious";
    case "likely_benign":
      return "benign";
    default:
      return "unknown";
  }
}
