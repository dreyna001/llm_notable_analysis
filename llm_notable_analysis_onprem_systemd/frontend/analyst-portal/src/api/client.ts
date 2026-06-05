import type {
  CaseDetail,
  CaseListResponse,
  ChatRequest,
  ChatResponse,
  ChatSessionMessagesResponse,
  ChatSessionsResponse,
} from "../types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
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

export async function fetchHealth(): Promise<{
  status: string;
  case_retention_days?: number;
}> {
  return readJson(await fetch("/health"));
}

export async function fetchCases(params?: {
  limit?: number;
  offset?: number;
  start?: string;
  end?: string;
  verdict?: string;
  search_name?: string;
}): Promise<CaseListResponse> {
  const query = new URLSearchParams();
  if (params?.limit != null) query.set("limit", String(params.limit));
  if (params?.offset != null) query.set("offset", String(params.offset));
  if (params?.start) query.set("start", params.start);
  if (params?.end) query.set("end", params.end);
  if (params?.verdict) query.set("verdict", params.verdict);
  if (params?.search_name) query.set("search_name", params.search_name);
  const suffix = query.size ? `?${query}` : "";
  return readJson(await fetch(`/api/cases${suffix}`));
}

export async function fetchCase(caseId: string): Promise<CaseDetail> {
  return readJson(await fetch(`/api/cases/${encodeURIComponent(caseId)}`));
}

export async function postChat(payload: ChatRequest): Promise<ChatResponse> {
  return readJson(
    await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function fetchChatSessions(limit = 50): Promise<ChatSessionsResponse> {
  const query = new URLSearchParams();
  query.set("limit", String(limit));
  return readJson(await fetch(`/api/chat/sessions?${query}`));
}

export async function fetchChatSessionMessages(
  sessionId: string,
): Promise<ChatSessionMessagesResponse> {
  return readJson(
    await fetch(`/api/chat/sessions/${encodeURIComponent(sessionId)}/messages`),
  );
}

export async function deleteChatSession(
  sessionId: string,
): Promise<{ deleted: boolean; session_id: string }> {
  return readJson(
    await fetch(`/api/chat/sessions/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
    }),
  );
}
