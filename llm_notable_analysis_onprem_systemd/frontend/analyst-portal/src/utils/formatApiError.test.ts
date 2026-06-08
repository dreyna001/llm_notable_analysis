import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import {
  formatApiError,
  formatChatApiError,
  isChatSessionScopeMismatch,
} from "./formatApiError";

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

describe("chat session scope mismatch", () => {
  const mismatch = new ApiError(
    400,
    "session_id scope does not match the chat request.",
  );

  it("detects stale server session errors", () => {
    expect(isChatSessionScopeMismatch(mismatch)).toBe(true);
  });

  it("formats recovery guidance for chat POST failures", () => {
    expect(formatChatApiError(mismatch)).toBe(
      "This chat no longer matches the selected case or mode. Your next message will start a fresh server session.",
    );
  });
});
