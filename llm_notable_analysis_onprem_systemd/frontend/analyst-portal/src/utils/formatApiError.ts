import { ApiError, INVALID_RESPONSE_STATUS } from "../api/client";

const CHAT_SESSION_SCOPE_MISMATCH_SNIPPET = "session_id scope does not match";
const CHAT_SELECTED_CASE_REQUIRED_SNIPPET = "selected_case_id is required";

export const CHAT_CONCURRENCY_LIMIT_MESSAGE =
  "The portal is busy handling other chat requests. Wait a moment and try again.";

export const CHAT_SESSION_SCOPE_MISMATCH_MESSAGE =
  "This chat no longer matches the selected case or mode. Your next message will start a fresh server session.";

export const CHAT_TIMEOUT_MESSAGE =
  "The chat request timed out. Wait a moment and try again, or ask a shorter question.";

export const CHAT_CANCELLED_MESSAGE =
  "Response stopped. Send a new question when you are ready.";

export const CHAT_CASE_NOT_FOUND_MESSAGE =
  "The attached case was not found. Attach another case or browse the case index.";

export const CHAT_UNAVAILABLE_MESSAGE =
  "Chat is temporarily unavailable. Wait a moment and try again.";

export const CHAT_INVALID_RESPONSE_MESSAGE =
  "The portal returned an unexpected response. Try again.";

export const CHAT_CASE_REQUIRED_MESSAGE =
  "Attach a case before asking in selected-case mode.";

export function isChatConcurrencyLimit(err: unknown): boolean {
  return err instanceof ApiError && err.status === 429;
}

export function isChatSessionScopeMismatch(err: unknown): boolean {
  return (
    err instanceof ApiError &&
    err.status === 400 &&
    err.message.includes(CHAT_SESSION_SCOPE_MISMATCH_SNIPPET)
  );
}

export function isChatTimeout(err: unknown): boolean {
  return err instanceof ApiError && err.kind === "timeout";
}

export function isChatCancelled(err: unknown): boolean {
  return err instanceof ApiError && err.kind === "cancelled";
}

export function isChatCaseNotFound(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404;
}

export function isChatUnavailable(err: unknown): boolean {
  return err instanceof ApiError && err.status === 503;
}

export function isChatInvalidResponse(err: unknown): boolean {
  return (
    err instanceof ApiError &&
    (err.kind === "invalid_response" || err.status === INVALID_RESPONSE_STATUS)
  );
}

export function isChatSelectedCaseRequired(err: unknown): boolean {
  return (
    err instanceof ApiError &&
    err.status === 400 &&
    err.message.includes(CHAT_SELECTED_CASE_REQUIRED_SNIPPET)
  );
}

/** Format API errors for UI; omit a misleading "0:" prefix for transport failures. */
export function formatApiError(err: unknown, fallback = "Unknown error"): string {
  if (err instanceof ApiError) {
    if (err.status === 0) {
      return err.message;
    }
    return `${err.status}: ${err.message}`;
  }
  if (err instanceof Error) {
    return err.message;
  }
  return fallback;
}

/** Format chat POST errors with recovery guidance for known portal failures. */
export function formatChatApiError(err: unknown, fallback = "Unknown error"): string {
  if (isChatCancelled(err)) {
    return CHAT_CANCELLED_MESSAGE;
  }
  if (isChatTimeout(err)) {
    return CHAT_TIMEOUT_MESSAGE;
  }
  if (isChatConcurrencyLimit(err)) {
    return CHAT_CONCURRENCY_LIMIT_MESSAGE;
  }
  if (isChatSessionScopeMismatch(err)) {
    return CHAT_SESSION_SCOPE_MISMATCH_MESSAGE;
  }
  if (isChatCaseNotFound(err)) {
    return CHAT_CASE_NOT_FOUND_MESSAGE;
  }
  if (isChatUnavailable(err)) {
    return CHAT_UNAVAILABLE_MESSAGE;
  }
  if (isChatInvalidResponse(err)) {
    return CHAT_INVALID_RESPONSE_MESSAGE;
  }
  if (isChatSelectedCaseRequired(err)) {
    return CHAT_CASE_REQUIRED_MESSAGE;
  }
  if (err instanceof ApiError && err.status >= 500) {
    return CHAT_UNAVAILABLE_MESSAGE;
  }
  return formatApiError(err, fallback);
}
