import { describe, expect, it } from "vitest";
import {
  adjustContextUsageForDraft,
  estimateTokensFromChars,
  formatTokenCount,
  questionBlockChars,
} from "./contextUsage";
import type { ChatContextUsage } from "../types";

const sampleUsage: ChatContextUsage = {
  kind: "case_grounded",
  prompt_chars: 4000,
  prompt_tokens: 1000,
  context_limit_tokens: 128000,
  utilization_pct: 1,
  estimate_method: "chars_per_token",
  chars_per_token_estimate: 4.38,
  current_question_chars: questionBlockChars("What happened?", "case_grounded"),
  segments: [
    {
      id: "system_prompt",
      label: "System prompt",
      chars: 2000,
      tokens: 500,
    },
    {
      id: "conversation",
      label: "Conversation",
      chars: 40,
      tokens: 10,
    },
  ],
};

describe("formatTokenCount", () => {
  it("formats thousands with one decimal when under 10K", () => {
    expect(formatTokenCount(166000)).toBe("166.0K");
    expect(formatTokenCount(9000)).toBe("9.0K");
  });

  it("formats small counts without suffix", () => {
    expect(formatTokenCount(470)).toBe("470");
  });
});

describe("estimateTokensFromChars", () => {
  it("rounds char counts to token estimates", () => {
    expect(estimateTokensFromChars(0)).toBe(0);
    expect(estimateTokensFromChars(1)).toBe(1);
    expect(estimateTokensFromChars(9)).toBe(2);
  });
});

describe("adjustContextUsageForDraft", () => {
  it("updates conversation segment and totals when the draft changes", () => {
    const adjusted = adjustContextUsageForDraft(
      sampleUsage,
      "What changed in this case since the last review?",
    );
    const conversation = adjusted.segments.find(
      (segment) => segment.id === "conversation",
    );
    expect(conversation?.chars).toBeGreaterThan(
      sampleUsage.segments[1]?.chars ?? 0,
    );
    expect(adjusted.prompt_tokens).toBeGreaterThan(sampleUsage.prompt_tokens);
    expect(adjusted.current_question_chars).toBeGreaterThan(
      sampleUsage.current_question_chars,
    );
  });

  it("returns the original usage when the draft is empty", () => {
    expect(adjustContextUsageForDraft(sampleUsage, "   ")).toEqual(sampleUsage);
  });
});
