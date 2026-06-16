import { describe, expect, it } from "vitest";
import {
  interpretationAssessmentLabel,
  interpretationDeltaLabel,
} from "./interpretationStatus";

describe("interpretationStatus labels", () => {
  it("maps interpretation assessments", () => {
    expect(interpretationAssessmentLabel("supports")).toBe("Supports hypothesis");
    expect(interpretationAssessmentLabel("weakens")).toBe("Weakens hypothesis");
  });

  it("maps confidence deltas", () => {
    expect(interpretationDeltaLabel("increase")).toBe("Confidence increased");
    expect(interpretationDeltaLabel("unchanged")).toBe("No change");
  });
});
