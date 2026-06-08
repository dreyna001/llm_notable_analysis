import { describe, expect, it } from "vitest";
import { ApiError, INVALID_RESPONSE_STATUS } from "../api/client";
import {
  CHAT_CANCELLED_MESSAGE,
  CHAT_CASE_NOT_FOUND_MESSAGE,
  CHAT_CASE_REQUIRED_MESSAGE,
  CHAT_CONCURRENCY_LIMIT_MESSAGE,
  CHAT_INVALID_RESPONSE_MESSAGE,
  CHAT_LLM_RATE_LIMIT_MESSAGE,
  CHAT_SESSION_SCOPE_MISMATCH_MESSAGE,
  CHAT_TIMEOUT_MESSAGE,
  CHAT_UNAVAILABLE_MESSAGE,
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

describe("formatChatApiError", () => {
  it("formats concurrency, session, and transport guidance", () => {
    expect(
      formatChatApiError(
        new ApiError(
          429,
          "Too many chat requests are already running. Try again shortly.",
        ),
      ),
    ).toBe(CHAT_CONCURRENCY_LIMIT_MESSAGE);

    expect(
      formatChatApiError(
        new ApiError(400, "session_id scope does not match the chat request."),
      ),
    ).toBe(CHAT_SESSION_SCOPE_MISMATCH_MESSAGE);

    expect(
      formatChatApiError(new ApiError(0, "Request timed out.", "timeout")),
    ).toBe(CHAT_TIMEOUT_MESSAGE);

    expect(
      formatChatApiError(
        new ApiError(504, "LLM request timed out. Try again or ask a shorter question."),
      ),
    ).toBe(CHAT_TIMEOUT_MESSAGE);

    expect(
      formatChatApiError(
        new ApiError(429, "LLM rate limit reached. Try again shortly."),
      ),
    ).toBe(CHAT_LLM_RATE_LIMIT_MESSAGE);

    expect(
      formatChatApiError(new ApiError(0, "Request cancelled.", "cancelled")),
    ).toBe(CHAT_CANCELLED_MESSAGE);
  });

  it("formats case, availability, and validation guidance", () => {
    expect(formatChatApiError(new ApiError(404, "Case not found."))).toBe(
      CHAT_CASE_NOT_FOUND_MESSAGE,
    );

    expect(
      formatChatApiError(new ApiError(503, "Case chat unavailable.")),
    ).toBe(CHAT_UNAVAILABLE_MESSAGE);

    expect(
      formatChatApiError(
        new ApiError(
          INVALID_RESPONSE_STATUS,
          "Portal API returned an unexpected response.",
          "invalid_response",
        ),
      ),
    ).toBe(CHAT_INVALID_RESPONSE_MESSAGE);

    expect(
      formatChatApiError(
        new ApiError(400, "selected_case_id is required for this mode."),
      ),
    ).toBe(CHAT_CASE_REQUIRED_MESSAGE);

    expect(formatChatApiError(new ApiError(500, "Internal server error."))).toBe(
      CHAT_UNAVAILABLE_MESSAGE,
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
});
