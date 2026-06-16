import { describe, expect, it } from "vitest";
import { queryStatusLabel } from "./queryStatus";

describe("queryStatusLabel", () => {
  it("maps known query statuses", () => {
    expect(queryStatusLabel("executed")).toBe("Executed");
    expect(queryStatusLabel("denied")).toBe("Denied");
    expect(queryStatusLabel("skipped")).toBe("Skipped");
    expect(queryStatusLabel("not_run")).toBe("Not run");
  });
});
