import { describe, expect, it } from "vitest";
import { retrievalStatusLabel } from "./retrievalStatus";

describe("retrievalStatusLabel", () => {
  it("maps known retrieval statuses to analyst-readable labels", () => {
    expect(retrievalStatusLabel("ready")).toBe("Indexed");
    expect(retrievalStatusLabel("pending")).toBe("Indexing pending");
    expect(retrievalStatusLabel("failed")).toBe("Indexing failed");
    expect(retrievalStatusLabel("not_indexed")).toBe("Not indexed");
  });

  it("falls back for unknown statuses", () => {
    expect(retrievalStatusLabel("custom_state")).toBe("custom state");
    expect(retrievalStatusLabel(null)).toBe("Loading");
  });
});
