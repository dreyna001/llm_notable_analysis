import { describe, expect, it } from "vitest";
import { answerStatusLabel, shouldShowAnswerStatus } from "./answerStatus";

describe("answerStatusLabel", () => {
  it("maps known chat answer statuses", () => {
    expect(answerStatusLabel("answered")).toBe("Answered");
    expect(answerStatusLabel("unknown")).toBe("Insufficient evidence");
    expect(answerStatusLabel("refused")).toBe("Refused");
  });

  it("shows only non-answered statuses in the UI", () => {
    expect(shouldShowAnswerStatus("answered")).toBe(false);
    expect(shouldShowAnswerStatus("unknown")).toBe(true);
    expect(shouldShowAnswerStatus("refused")).toBe(true);
  });
});
