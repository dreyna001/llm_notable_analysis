import { describe, expect, it } from "vitest";
import { VERDICT_COLOR, verdictColor } from "./verdict";

describe("verdictColor", () => {
  it("maps malicious verdicts to red", () => {
    expect(verdictColor("likely_malicious")).toBe(VERDICT_COLOR.malicious);
    expect(verdictColor("true_positive")).toBe(VERDICT_COLOR.malicious);
  });

  it("maps benign verdicts to green", () => {
    expect(verdictColor("likely_benign")).toBe(VERDICT_COLOR.benign);
    expect(verdictColor("false_positive")).toBe(VERDICT_COLOR.benign);
  });

  it("maps unknown or missing verdicts to amber", () => {
    expect(verdictColor("unknown")).toBe(VERDICT_COLOR.unknown);
    expect(verdictColor(null)).toBe(VERDICT_COLOR.unknown);
    expect(verdictColor(undefined)).toBe(VERDICT_COLOR.unknown);
  });
});
