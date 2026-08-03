import { describe, expect, it } from "vitest";
import { sourceCompletenessLabel } from "./sourceCompleteness";

describe("sourceCompletenessLabel", () => {
  it("maps known completeness values to analyst-readable labels", () => {
    expect(sourceCompletenessLabel("complete")).toBe("Complete");
    expect(sourceCompletenessLabel("missing_analysis")).toBe(
      "Structured analysis missing",
    );
    expect(sourceCompletenessLabel("missing_alert")).toBe("Alert payload missing");
    expect(sourceCompletenessLabel("markdown_only")).toBe("Markdown report only");
  });

  it("falls back for unknown values", () => {
    expect(sourceCompletenessLabel("custom_state")).toBe("custom state");
    expect(sourceCompletenessLabel(null)).toBe("Loading");
  });
});
