import type { ChatContextUsage } from "../types";

export const SEGMENT_COLORS: Record<string, string> = {
  system_prompt: "bg-muted-foreground/70",
  current_case: "bg-sky-500",
  knowledge_base: "bg-emerald-500",
  closed_ticket: "bg-violet-500",
  conversation: "bg-blue-400",
};

export function formatTokenCount(tokens: number): string {
  if (tokens >= 1_000_000) {
    return `${(tokens / 1_000_000).toFixed(1)}M`;
  }
  if (tokens >= 1_000) {
    return `${(tokens / 1_000).toFixed(1)}K`;
  }
  return String(tokens);
}

export function questionBlockChars(
  question: string,
  kind: ChatContextUsage["kind"] = "case_grounded",
): number {
  const trimmed = question.trim();
  if (!trimmed) {
    return 0;
  }
  const block =
    "QUESTION_JSON:\n".length + JSON.stringify(trimmed).length;
  return kind === "case_grounded" ? block + 2 : block;
}

export function estimateTokensFromChars(
  charCount: number,
  charsPerToken = 4.38,
): number {
  if (charCount <= 0) {
    return 0;
  }
  return Math.max(1, Math.round(charCount / charsPerToken));
}

export function adjustContextUsageForDraft(
  usage: ChatContextUsage,
  draftQuestion: string,
): ChatContextUsage {
  const trimmed = draftQuestion.trim();
  if (!trimmed) {
    return usage;
  }

  const conversationSegment = usage.segments.find(
    (segment) => segment.id === "conversation",
  );
  if (!conversationSegment) {
    return usage;
  }

  const draftQuestionChars = questionBlockChars(trimmed, usage.kind);
  const baselineQuestionChars = usage.current_question_chars;
  const deltaChars = draftQuestionChars - baselineQuestionChars;
  if (deltaChars === 0) {
    return usage;
  }

  const deltaTokens = estimateTokensFromChars(
    Math.abs(deltaChars),
    usage.chars_per_token_estimate,
  );
  const signedDeltaTokens = deltaChars >= 0 ? deltaTokens : -deltaTokens;
  const promptTokens = Math.max(0, usage.prompt_tokens + signedDeltaTokens);
  const limitTokens = Math.max(usage.context_limit_tokens, 1);
  const utilizationPct = Math.min(
    100,
    Math.round((promptTokens / limitTokens) * 100),
  );
  const nextConversationChars = Math.max(
    0,
    conversationSegment.chars + deltaChars,
  );
  const nextConversationTokens = estimateTokensFromChars(
    nextConversationChars,
    usage.chars_per_token_estimate,
  );

  return {
    ...usage,
    prompt_chars: Math.max(0, usage.prompt_chars + deltaChars),
    prompt_tokens: promptTokens,
    utilization_pct: utilizationPct,
    current_question_chars: draftQuestionChars,
    segments: usage.segments.map((segment) =>
      segment.id === "conversation"
        ? {
            ...segment,
            chars: nextConversationChars,
            tokens: nextConversationTokens,
          }
        : segment,
    ),
  };
}
