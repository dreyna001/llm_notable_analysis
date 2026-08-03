import { describe, expect, it } from "vitest";
import { resolveChatEmptyState } from "./chatEmptyState";

describe("resolveChatEmptyState", () => {
  it("returns case-specific guidance when a case is attached", () => {
    const content = resolveChatEmptyState("selected_case", "case-1");

    expect(content.title).toBe("Start investigating this case");
  });

  it("returns general guidance when no case is attached", () => {
    const content = resolveChatEmptyState("selected_case");

    expect(content.title).toBe("How can I help?");
  });
});
