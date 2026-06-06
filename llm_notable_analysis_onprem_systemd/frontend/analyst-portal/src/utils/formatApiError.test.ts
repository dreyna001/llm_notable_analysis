import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { formatApiError } from "./formatApiError";

describe("formatApiError", () => {
  it("omits status prefix for cancelled requests", () => {
    expect(
      formatApiError(new ApiError(0, "Request cancelled.", "cancelled")),
    ).toBe("Request cancelled.");
  });

  it("omits status prefix for timed out requests", () => {
    expect(
      formatApiError(new ApiError(0, "Request timed out.", "timeout")),
    ).toBe("Request timed out.");
  });

  it("includes status code for HTTP errors", () => {
    expect(formatApiError(new ApiError(404, "Case not found."))).toBe(
      "404: Case not found.",
    );
  });
});
