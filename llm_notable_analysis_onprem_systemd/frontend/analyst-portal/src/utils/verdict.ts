export type VerdictTone = "malicious" | "benign" | "unknown";

// Deterministic verdict -> threat color. Red is most malicious, green is least
// malicious; unknown verdicts stay amber. Shared by case detail and attach UI.
export const VERDICT_COLOR: Record<VerdictTone, string> = {
  malicious: "#f87171",
  benign: "#4ade80",
  unknown: "#fbbf24",
};

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

export function verdictColor(verdict: unknown): string {
  return VERDICT_COLOR[verdictTone(verdict)];
}
