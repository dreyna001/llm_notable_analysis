import { describe, expect, it } from "vitest";
import {
  formatChatUnavailableReason,
  resolveChatUnavailableReason,
} from "./chatDependencyStatus";

describe("formatChatUnavailableReason", () => {
  it("names a single unavailable dependency", () => {
    expect(
      formatChatUnavailableReason({
        embeddings: "ready",
        archive_retrieval: "ready",
        llm_gateway: "unavailable",
      }),
    ).toBe("Case chat is unavailable: LLM gateway is down.");
  });

  it("lists every unavailable dependency without or", () => {
    expect(
      formatChatUnavailableReason({
        embeddings: "unavailable",
        archive_retrieval: "unavailable",
        llm_gateway: "unavailable",
      }),
    ).toBe(
      "Case chat is unavailable: Embeddings, Archive retrieval, LLM gateway are down.",
    );
  });
});

describe("resolveChatUnavailableReason", () => {
  it("prefers structured dependency status over legacy text", () => {
    expect(
      resolveChatUnavailableReason({
        chat_degraded_reason:
          "Case chat is temporarily unavailable. Embeddings, archive retrieval, or the LLM may be down.",
        chat_dependency_status: {
          embeddings: "ready",
          archive_retrieval: "ready",
          llm_gateway: "unavailable",
        },
      }),
    ).toBe("Case chat is unavailable: LLM gateway is down.");
  });
});
