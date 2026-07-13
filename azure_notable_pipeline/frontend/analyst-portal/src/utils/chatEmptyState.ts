import type { ChatMode } from "../types";

export type ChatEmptyStateContent = {
  title: string;
  description: string;
};

export function resolveChatEmptyState(
  mode: ChatMode,
  selectedCaseId?: string,
): ChatEmptyStateContent {
  if (mode === "selected_case" && selectedCaseId) {
    return {
      title: "Start investigating this case",
      description:
        "Ask about evidence, verdict, hypotheses, or recommended next steps.",
    };
  }

  return {
    title: "How can I help?",
    description:
      "Ask about retained cases, the knowledge base, or any technology topic.",
  };
}
