import type {
  CaseDetail,
  CaseListResponse,
  ChatRequest,
  ChatResponse,
  ChatSessionMessagesResponse,
  ChatSessionsResponse,
  PortalCapabilities,
} from "../types";

export type ApiErrorKind = "cancelled" | "timeout" | "http";

export class ApiError extends Error {
  status: number;
  kind: ApiErrorKind;

  constructor(status: number, message: string, kind: ApiErrorKind = "http") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.kind = kind;
  }
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (body.detail != null) {
        detail = JSON.stringify(body.detail);
      }
    } catch {
      // ignore parse errors
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

type ApiFetchOptions = RequestInit & {
  timeoutMs?: number;
};

const DEFAULT_TIMEOUT_MS = 30_000;
const CHAT_TIMEOUT_MS = 270_000;

function mergeAbortSignals(
  timeoutMs: number,
  callerSignal?: AbortSignal,
): { signal: AbortSignal; cleanup: () => void } {
  const timeoutController = new AbortController();
  const timeout = window.setTimeout(() => timeoutController.abort(), timeoutMs);
  const cleanup = () => window.clearTimeout(timeout);

  if (!callerSignal) {
    return { signal: timeoutController.signal, cleanup };
  }

  if (typeof AbortSignal !== "undefined" && "any" in AbortSignal) {
    return {
      signal: AbortSignal.any([timeoutController.signal, callerSignal]),
      cleanup,
    };
  }

  const linked = new AbortController();
  const abortLinked = () => linked.abort();
  if (callerSignal.aborted || timeoutController.signal.aborted) {
    linked.abort();
  }
  callerSignal.addEventListener("abort", abortLinked, { once: true });
  timeoutController.signal.addEventListener("abort", abortLinked, { once: true });
  return {
    signal: linked.signal,
    cleanup: () => {
      cleanup();
      callerSignal.removeEventListener("abort", abortLinked);
      timeoutController.signal.removeEventListener("abort", abortLinked);
    },
  };
}

async function apiFetch(
  input: RequestInfo | URL,
  { timeoutMs = DEFAULT_TIMEOUT_MS, signal, ...init }: ApiFetchOptions = {},
): Promise<Response> {
  const { signal: mergedSignal, cleanup } = mergeAbortSignals(
    timeoutMs,
    signal ?? undefined,
  );
  try {
    return await fetch(input, {
      ...init,
      signal: mergedSignal,
    });
  } catch (error) {
    if (signal?.aborted) {
      throw new ApiError(0, "Request cancelled.", "cancelled");
    }
    if (mergedSignal.aborted) {
      throw new ApiError(0, "Request timed out.", "timeout");
    }
    throw error;
  } finally {
    cleanup();
  }
}

export async function fetchHealth(): Promise<{
  status: string;
  case_retention_days?: number;
}> {
  return readJson(await apiFetch("/health"));
}

export async function fetchCapabilities(): Promise<PortalCapabilities> {
  return readJson(await apiFetch("/api/capabilities"));
}

export async function fetchCases(params?: {
  limit?: number;
  offset?: number;
  start_date?: string;
  end_date?: string;
  verdict?: string;
  search_name?: string;
}): Promise<CaseListResponse> {
  const query = new URLSearchParams();
  if (params?.limit != null) query.set("limit", String(params.limit));
  if (params?.offset != null) query.set("offset", String(params.offset));
  if (params?.start_date) query.set("start_date", params.start_date);
  if (params?.end_date) query.set("end_date", params.end_date);
  if (params?.verdict) query.set("verdict", params.verdict);
  if (params?.search_name) query.set("search_name", params.search_name);
  const suffix = query.size ? `?${query}` : "";
  return readJson(await apiFetch(`/api/cases${suffix}`));
}

export async function fetchCase(caseId: string): Promise<CaseDetail> {
  return readJson(await apiFetch(`/api/cases/${encodeURIComponent(caseId)}`));
}

export async function postChat(
  payload: ChatRequest,
  options?: { signal?: AbortSignal },
): Promise<ChatResponse> {
  return readJson(
    await apiFetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      timeoutMs: CHAT_TIMEOUT_MS,
      signal: options?.signal,
    }),
  );
}

export async function fetchChatSessions(limit = 50): Promise<ChatSessionsResponse> {
  const query = new URLSearchParams();
  query.set("limit", String(limit));
  return readJson(await apiFetch(`/api/chat/sessions?${query}`));
}

export async function fetchChatSessionMessages(
  sessionId: string,
  options?: { signal?: AbortSignal },
): Promise<ChatSessionMessagesResponse> {
  return readJson(
    await apiFetch(`/api/chat/sessions/${encodeURIComponent(sessionId)}/messages`, {
      signal: options?.signal,
    }),
  );
}

export async function deleteChatSession(
  sessionId: string,
): Promise<{ deleted: boolean; session_id: string }> {
  return readJson(
    await apiFetch(`/api/chat/sessions/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
    }),
  );
}

export async function deleteLastChatTurn(
  sessionId: string,
  options?: { expectedMessageCount?: number },
): Promise<{ deleted: boolean; session_id: string; deleted_messages: number }> {
  const query = new URLSearchParams();
  if (options?.expectedMessageCount != null) {
    query.set("expected_message_count", String(options.expectedMessageCount));
  }
  const suffix = query.size ? `?${query}` : "";
  return readJson(
    await apiFetch(
      `/api/chat/sessions/${encodeURIComponent(sessionId)}/turns/last${suffix}`,
      {
        method: "DELETE",
      },
    ),
  );
}
