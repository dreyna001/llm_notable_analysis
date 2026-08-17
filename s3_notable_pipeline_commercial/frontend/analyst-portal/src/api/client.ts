import {
  INVALID_RESPONSE_MESSAGE,
  parseCaseDetail,
  parseCaseListResponse,
  parseCaseRawSectionResponse,
  parseChatResponse,
  parseChatSessionMessagesResponse,
  parseChatSessionsResponse,
  parseDeleteChatSessionResponse,
  parseDeleteLastChatTurnResponse,
  parseHealthResponse,
  parsePortalCapabilities,
} from "./responseSchemas";
import { portalAuthMode } from "../auth/authConfig";
import type {
  CaseDetail,
  CaseListCursor,
  CaseListResponse,
  CaseRawSection,
  CaseRawSectionResponse,
  ChatRequest,
  ChatResponse,
  ChatSessionMessagesResponse,
  ChatSessionsResponse,
  PortalCapabilities,
} from "../types";

export type ApiErrorKind = "cancelled" | "timeout" | "http" | "invalid_response";
export type PortalAuthErrorKind = "unauthorized" | "forbidden";
type PortalTokenProvider = () => Promise<string>;
type PortalAuthErrorHandler = (kind: PortalAuthErrorKind) => void;

export const INVALID_RESPONSE_STATUS = 502;
export const PORTAL_AUTH_TOKEN_STORAGE_KEY = "notable.portal.jwt";

let portalTokenProvider: PortalTokenProvider | null = null;
let portalAuthErrorHandler: PortalAuthErrorHandler | null = null;

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

export function isCancelledRequest(
  error: unknown,
  signal?: AbortSignal,
): boolean {
  if (signal?.aborted) {
    return true;
  }
  return error instanceof ApiError && error.kind === "cancelled";
}

type ResponseParser<T> = (value: unknown) => T | null;

async function readValidatedJson<T>(
  response: Response,
  parse: ResponseParser<T>,
): Promise<T> {
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown; error?: unknown };
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (typeof body.error === "string") {
        detail = body.error;
      } else if (body.detail != null) {
        detail = JSON.stringify(body.detail);
      } else if (body.error != null) {
        detail = JSON.stringify(body.error);
      }
    } catch {
      // ignore parse errors
    }
    throw new ApiError(response.status, detail);
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiError(
      INVALID_RESPONSE_STATUS,
      INVALID_RESPONSE_MESSAGE,
      "invalid_response",
    );
  }

  const parsed = parse(body);
  if (parsed === null) {
    throw new ApiError(
      INVALID_RESPONSE_STATUS,
      INVALID_RESPONSE_MESSAGE,
      "invalid_response",
    );
  }
  return parsed;
}

type ApiFetchOptions = RequestInit & {
  timeoutMs?: number;
};

const DEFAULT_TIMEOUT_MS = 30_000;
const CHAT_TIMEOUT_MS = 270_000;

function portalApiBaseUrl(): string {
  return String(import.meta.env.VITE_PORTAL_API_BASE_URL ?? "").replace(/\/+$/, "");
}

function apiUrl(path: RequestInfo | URL): RequestInfo | URL {
  if (typeof path !== "string" || !path.startsWith("/")) {
    return path;
  }
  const baseUrl = portalApiBaseUrl();
  return baseUrl ? `${baseUrl}${path}` : path;
}

export function setPortalAuthToken(token: string): void {
  window.sessionStorage.setItem(PORTAL_AUTH_TOKEN_STORAGE_KEY, token.trim());
}

export function clearPortalAuthToken(): void {
  window.sessionStorage.removeItem(PORTAL_AUTH_TOKEN_STORAGE_KEY);
  window.localStorage.removeItem(PORTAL_AUTH_TOKEN_STORAGE_KEY);
}

export function setPortalTokenProvider(provider: PortalTokenProvider | null): void {
  portalTokenProvider = provider;
}

export function setPortalAuthErrorHandler(
  handler: PortalAuthErrorHandler | null,
): void {
  portalAuthErrorHandler = handler;
}

function manualPortalAuthToken(): string {
  return (
    window.sessionStorage.getItem(PORTAL_AUTH_TOKEN_STORAGE_KEY) ||
    window.localStorage.getItem(PORTAL_AUTH_TOKEN_STORAGE_KEY) ||
    ""
  ).trim();
}

async function portalAuthToken(): Promise<string> {
  if (portalTokenProvider) {
    return (await portalTokenProvider()).trim();
  }
  if (portalAuthMode() !== "manual") {
    return "";
  }
  return manualPortalAuthToken();
}

async function withAuthHeaders(headers: HeadersInit | undefined): Promise<Headers> {
  const merged = new Headers(headers);
  const token = await portalAuthToken();
  if (token) {
    merged.set("Authorization", `Bearer ${token}`);
  }
  return merged;
}

function notifyPortalAuthError(status: number): void {
  if (status === 401) {
    portalAuthErrorHandler?.("unauthorized");
    return;
  }
  if (status === 403) {
    portalAuthErrorHandler?.("forbidden");
  }
}

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
    const headers = await withAuthHeaders(init.headers);
    if (signal?.aborted) {
      throw new ApiError(0, "Request cancelled.", "cancelled");
    }
    const response = await fetch(apiUrl(input), {
      ...init,
      headers,
      signal: mergedSignal,
    });
    notifyPortalAuthError(response.status);
    return response;
  } catch (error) {
    if (error instanceof ApiError && error.kind === "cancelled") {
      throw error;
    }
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
  return readValidatedJson(await apiFetch("/health"), parseHealthResponse);
}

export async function fetchCapabilities(): Promise<PortalCapabilities> {
  return readValidatedJson(
    await apiFetch("/api/capabilities"),
    parsePortalCapabilities,
  );
}

export async function fetchCases(
  params?: {
    limit?: number;
    cursor?: CaseListCursor | null;
    start_date?: string;
    end_date?: string;
    verdict?: string;
    search_name?: string;
  },
  options?: { signal?: AbortSignal },
): Promise<CaseListResponse> {
  const query = new URLSearchParams();
  if (params?.limit != null) query.set("limit", String(params.limit));
  if (params?.cursor) {
    query.set("cursor_processed_at", params.cursor.processed_at);
    query.set("cursor_case_id", params.cursor.case_id);
  }
  if (params?.start_date) query.set("start_date", params.start_date);
  if (params?.end_date) query.set("end_date", params.end_date);
  if (params?.verdict) query.set("verdict", params.verdict);
  if (params?.search_name) query.set("search_name", params.search_name);
  const suffix = query.size ? `?${query}` : "";
  return readValidatedJson(
    await apiFetch(`/api/cases${suffix}`, { signal: options?.signal }),
    parseCaseListResponse,
  );
}

export async function fetchCase(
  caseId: string,
  options?: { signal?: AbortSignal },
): Promise<CaseDetail> {
  return readValidatedJson(
    await apiFetch(`/api/cases/${encodeURIComponent(caseId)}`, {
      signal: options?.signal,
    }),
    parseCaseDetail,
  );
}

export async function fetchCaseRawSection(
  caseId: string,
  section: CaseRawSection,
  params?: { offset?: number; limit?: number; key?: string },
): Promise<CaseRawSectionResponse> {
  const query = new URLSearchParams();
  if (params?.offset != null) query.set("offset", String(params.offset));
  if (params?.limit != null) query.set("limit", String(params.limit));
  if (params?.key) query.set("key", params.key);
  const suffix = query.size ? `?${query}` : "";
  return readValidatedJson(
    await apiFetch(
      `/api/cases/${encodeURIComponent(caseId)}/raw/${encodeURIComponent(section)}${suffix}`,
    ),
    parseCaseRawSectionResponse,
  );
}

export async function postChat(
  payload: ChatRequest,
  options?: { signal?: AbortSignal },
): Promise<ChatResponse> {
  return readValidatedJson(
    await apiFetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      timeoutMs: CHAT_TIMEOUT_MS,
      signal: options?.signal,
    }),
    parseChatResponse,
  );
}

export async function fetchChatSessions(limit = 50): Promise<ChatSessionsResponse> {
  const query = new URLSearchParams();
  query.set("limit", String(limit));
  return readValidatedJson(
    await apiFetch(`/api/chat/sessions?${query}`),
    parseChatSessionsResponse,
  );
}

export async function fetchChatSessionMessages(
  sessionId: string,
  options?: { signal?: AbortSignal },
): Promise<ChatSessionMessagesResponse> {
  return readValidatedJson(
    await apiFetch(`/api/chat/sessions/${encodeURIComponent(sessionId)}/messages`, {
      signal: options?.signal,
    }),
    parseChatSessionMessagesResponse,
  );
}

export async function deleteChatSession(
  sessionId: string,
): Promise<{ deleted: boolean; session_id: string }> {
  return readValidatedJson(
    await apiFetch(`/api/chat/sessions/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
    }),
    parseDeleteChatSessionResponse,
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
  return readValidatedJson(
    await apiFetch(
      `/api/chat/sessions/${encodeURIComponent(sessionId)}/turns/last${suffix}`,
      {
        method: "DELETE",
      },
    ),
    parseDeleteLastChatTurnResponse,
  );
}
