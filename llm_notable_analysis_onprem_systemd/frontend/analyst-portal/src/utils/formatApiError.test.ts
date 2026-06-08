import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import {
  CHAT_CONCURRENCY_LIMIT_MESSAGE,
  formatApiError,
  formatChatApiError,
  isChatConcurrencyLimit,
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

describe("chat concurrency limit", () => {
  const busy = new ApiError(
    429,
    "Too many chat requests are already running. Try again shortly.",
  );

  it("detects portal chat concurrency errors", () => {
    expect(isChatConcurrencyLimit(busy)).toBe(true);
  });

  it("formats retry guidance instead of a raw 429 prefix", () => {
    expect(formatChatApiError(busy)).toBe(CHAT_CONCURRENCY_LIMIT_MESSAGE);
  });

  it("keeps generic formatting for non-chat callers", () => {
    expect(formatApiError(busy)).toBe(
      "429: Too many chat requests are already running. Try again shortly.",
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
