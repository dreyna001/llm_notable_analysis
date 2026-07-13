import { describe, expect, it } from "vitest";
import {
  normalizeUtcFilterDate,
  processedAtMatchesUtcDateRange,
} from "./utcDateFilter";

describe("utcDateFilter", () => {
  it("normalizes date input values to YYYY-MM-DD", () => {
    expect(normalizeUtcFilterDate("2026-06-04")).toBe("2026-06-04");
    expect(normalizeUtcFilterDate("2026-06-04T12:00:00.000Z")).toBe("2026-06-04");
    expect(normalizeUtcFilterDate("")).toBe("");
    expect(normalizeUtcFilterDate("06/04/2026")).toBe("");
  });

  it("allows all rows when no date filters are set", () => {
    expect(processedAtMatchesUtcDateRange(undefined, "", "")).toBe(true);
  });

  it("matches processed_at against inclusive UTC calendar days", () => {
    expect(
      processedAtMatchesUtcDateRange(
        "2026-06-04T00:00:00Z",
        "2026-06-04",
        "2026-06-04",
      ),
    ).toBe(true);
    expect(
      processedAtMatchesUtcDateRange(
        "2026-06-04T23:59:59.999Z",
        "2026-06-04",
        "2026-06-04",
      ),
    ).toBe(true);
    expect(
      processedAtMatchesUtcDateRange(
        "2026-06-03T23:59:59Z",
        "2026-06-04",
        "2026-06-04",
      ),
    ).toBe(false);
    expect(
      processedAtMatchesUtcDateRange(
        "2026-06-05T00:00:00Z",
        "2026-06-04",
        "2026-06-04",
      ),
    ).toBe(false);
  });
});
