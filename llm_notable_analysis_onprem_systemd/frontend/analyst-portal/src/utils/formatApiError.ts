import { ApiError } from "../api/client";

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
