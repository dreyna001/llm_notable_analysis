import { describe, expect, it } from "vitest";
import {
  caseDetailTabNeedsUrlCleanup,
  resolveCaseDetailTab,
  type CaseDetailTab,
} from "./caseDetailTabs";

describe("caseDetailTabs", () => {
  const available: CaseDetailTab[] = ["overview", "evidence", "raw"];

  it("falls back when tab param is missing or invalid", () => {
    expect(resolveCaseDetailTab(null, available)).toBe("overview");
    expect(resolveCaseDetailTab("not-a-tab", available)).toBe("overview");
  });

  it("keeps valid tabs that are currently available", () => {
    expect(resolveCaseDetailTab("evidence", available)).toBe("evidence");
  });

  it("flags URL cleanup when tab is unavailable", () => {
    expect(caseDetailTabNeedsUrlCleanup("hypotheses", available)).toBe(true);
    expect(caseDetailTabNeedsUrlCleanup("evidence", available)).toBe(false);
    expect(caseDetailTabNeedsUrlCleanup(null, available)).toBe(false);
  });
});
