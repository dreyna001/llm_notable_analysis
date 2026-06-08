import { describe, expect, it } from "vitest";
import {
  casesListHasActiveFilters,
  resolveCasesEmptyState,
} from "./casesEmptyState";

describe("resolveCasesEmptyState", () => {
  it("returns case-id guidance when an exact lookup misses", () => {
    const content = resolveCasesEmptyState({
      start_date: "",
      end_date: "",
      verdict: "",
      case_id: "case-404",
      search_name: "",
    });

    expect(content.title).toBe("No case matches this ID");
    expect(content.action).toBe("clear_case_id");
  });

  it("returns filter guidance when list filters are active", () => {
    const content = resolveCasesEmptyState({
      start_date: "",
      end_date: "",
      verdict: "unknown",
      case_id: "",
      search_name: "powershell",
    });

    expect(content.title).toBe("No cases match these filters");
    expect(content.action).toBe("clear_filters");
  });

  it("returns archive guidance when no filters are active", () => {
    const content = resolveCasesEmptyState({
      start_date: "",
      end_date: "",
      verdict: "",
      case_id: "",
      search_name: "",
    });

    expect(content.title).toBe("No cases in the archive yet");
    expect(content.action).toBeUndefined();
  });
});

describe("casesListHasActiveFilters", () => {
  it("detects active filters", () => {
    expect(
      casesListHasActiveFilters({
        start_date: "",
        end_date: "",
        verdict: "",
        case_id: "",
        search_name: "alert",
      }),
    ).toBe(true);
  });
});
