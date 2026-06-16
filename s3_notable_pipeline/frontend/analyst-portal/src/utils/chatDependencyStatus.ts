import type { ChatDependencyStatus } from "../types";

const CHAT_DEPENDENCY_LABELS: Record<keyof ChatDependencyStatus, string> = {
  embeddings: "Embeddings",
  archive_retrieval: "Archive retrieval",
  llm_gateway: "LLM gateway",
};

export function formatChatUnavailableReason(
  status: ChatDependencyStatus | null | undefined,
): string | null {
  if (!status) {
    return null;
  }

  const down = (
    Object.keys(CHAT_DEPENDENCY_LABELS) as Array<keyof ChatDependencyStatus>
  ).filter((key) => status[key] === "unavailable");

  if (!down.length) {
    return null;
  }

  const labels = down.map((key) => CHAT_DEPENDENCY_LABELS[key]);
  if (labels.length === 1) {
    return `Case chat is unavailable: ${labels[0]} is down.`;
  }
  return `Case chat is unavailable: ${labels.join(", ")} are down.`;
}

export function resolveChatUnavailableReason(
  capabilities: {
    chat_degraded_reason?: string | null;
    chat_dependency_status?: ChatDependencyStatus | null;
  } | null,
): string {
  return (
    formatChatUnavailableReason(capabilities?.chat_dependency_status) ??
    capabilities?.chat_degraded_reason ??
    "Case chat is temporarily unavailable."
  );
}
