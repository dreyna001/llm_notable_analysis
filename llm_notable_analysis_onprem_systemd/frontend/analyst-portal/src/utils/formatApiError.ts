import { ApiError } from "../api/client";

const CHAT_SESSION_SCOPE_MISMATCH_SNIPPET = "session_id scope does not match";

export function isChatSessionScopeMismatch(err: unknown): boolean {
  return (
    err instanceof ApiError &&
    err.status === 400 &&
    err.message.includes(CHAT_SESSION_SCOPE_MISMATCH_SNIPPET)
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

/** Format chat POST errors, including recovery guidance for stale server sessions. */
export function formatChatApiError(err: unknown, fallback = "Unknown error"): string {
  if (isChatSessionScopeMismatch(err)) {
    return "This chat no longer matches the selected case or mode. Your next message will start a fresh server session.";
  }
  return formatApiError(err, fallback);
}
