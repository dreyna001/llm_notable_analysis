import type {
  CaseDetail,
  CaseListResponse,
  CaseRawSectionResponse,
  CaseSummary,
  ChatResponse,
  ChatSessionMessage,
  ChatSessionMessagesResponse,
  ChatSessionsResponse,
  ChatSessionSummary,
  PortalCapabilities,
} from "../types";
import { schemas } from "./generated/portalSchemas";

export const INVALID_RESPONSE_MESSAGE =
  "Portal API returned an unexpected response.";

function parseWithSchema<T>(
  schema: { safeParse: (value: unknown) => { success: boolean; data?: T } },
  value: unknown,
): T | null {
  const result = schema.safeParse(value);
  if (!result.success) {
    return null;
  }
  return result.data ?? null;
}

function omitUndefinedFields<T extends Record<string, unknown>>(value: T): T {
  const entries = Object.entries(value).filter(([, fieldValue]) => fieldValue !== undefined);
  return Object.fromEntries(entries) as T;
}

export function parseCaseListResponse(value: unknown): CaseListResponse | null {
  const parsed = parseWithSchema(schemas.CaseListResponse, value);
  if (!parsed) {
    return null;
  }
  const items: CaseSummary[] = parsed.items.map((item) =>
    omitUndefinedFields({
      case_id: item.case_id,
      processed_at: item.processed_at,
      expires_at: item.expires_at,
      verdict: item.verdict,
      confidence: item.confidence,
      search_name: item.search_name,
      retrieval_status: item.retrieval_status,
      source_completeness: item.source_completeness,
      ...(item.archive_notices ? { archive_notices: item.archive_notices } : {}),
    }),
  );
  return {
    items,
    limit: parsed.limit,
    has_more: parsed.has_more,
    next_cursor: parsed.next_cursor ?? null,
  };
}

export function parseCaseDetail(value: unknown): CaseDetail | null {
  const parsed = parseWithSchema(schemas.CaseDetailResponse, value);
  if (!parsed) {
    return null;
  }
  return {
    case_id: parsed.case_id,
    metadata: omitUndefinedFields({
      processed_at: parsed.metadata.processed_at,
      expires_at: parsed.metadata.expires_at,
      retrieval_status: parsed.metadata.retrieval_status,
      source_completeness: parsed.metadata.source_completeness,
      ...(parsed.metadata.archive_notices
        ? { archive_notices: parsed.metadata.archive_notices }
        : {}),
    }),
    alert_payload: parsed.alert_payload ?? {},
    analysis: parsed.analysis,
    report_md_path: parsed.report_md_path,
    report_html_path: parsed.report_html_path,
    content_bounds: parsed.content_bounds,
  };
}

export function parseCaseRawSectionResponse(
  value: unknown,
): CaseRawSectionResponse | null {
  const parsed = parseWithSchema(schemas.CaseRawSectionResponse, value);
  if (!parsed) {
    return null;
  }
  return {
    case_id: parsed.case_id,
    section: parsed.section,
    offset: parsed.offset,
    limit: parsed.limit,
    has_more: parsed.has_more,
    total_keys: parsed.total_keys,
    items: parsed.items ?? {},
  };
}

export function parsePortalCapabilities(value: unknown): PortalCapabilities | null {
  const parsed = parseWithSchema(schemas.PortalCapabilitiesResponse, value);
  if (!parsed) {
    return null;
  }
  return {
    case_qa_enabled: parsed.case_qa_enabled,
    global_retrieval_enabled: parsed.global_retrieval_enabled,
    chat_history_enabled: parsed.chat_history_enabled,
    general_knowledge_enabled: parsed.general_knowledge_enabled,
    max_question_chars: parsed.max_question_chars,
    max_answer_tokens: parsed.max_answer_tokens,
    chat_ready: parsed.chat_ready,
    ...(parsed.chat_dependency_status
      ? { chat_dependency_status: parsed.chat_dependency_status }
      : {}),
    ...(parsed.max_chat_sessions_per_user !== undefined
      ? { max_chat_sessions_per_user: parsed.max_chat_sessions_per_user }
      : {}),
    ...(parsed.case_retention_days !== undefined
      ? { case_retention_days: parsed.case_retention_days }
      : {}),
    ...(parsed.chat_degraded_reason !== undefined
      ? { chat_degraded_reason: parsed.chat_degraded_reason }
      : {}),
  };
}

export function parseChatResponse(value: unknown): ChatResponse | null {
  const parsed = parseWithSchema(schemas.ChatResponseModel, value);
  if (!parsed) {
    return null;
  }
  return {
    answer: parsed.answer,
    answer_status: parsed.answer_status,
    session_id: parsed.session_id ?? null,
  };
}

export function parseChatSessionsResponse(
  value: unknown,
): ChatSessionsResponse | null {
  const parsed = parseWithSchema(schemas.ChatSessionsResponse, value);
  if (!parsed) {
    return null;
  }
  const items: ChatSessionSummary[] = parsed.items.map((item) => ({
    session_id: item.session_id,
    title: item.title,
    updated_at: item.updated_at,
    mode: item.mode,
    selected_case_id: item.selected_case_id,
  }));
  return {
    history_enabled: parsed.history_enabled,
    items,
  };
}

export function parseChatSessionMessagesResponse(
  value: unknown,
): ChatSessionMessagesResponse | null {
  const parsed = parseWithSchema(schemas.ChatSessionMessagesResponse, value);
  if (!parsed) {
    return null;
  }
  const messages: ChatSessionMessage[] = parsed.messages.map((item) =>
    omitUndefinedFields({
      role: item.role,
      content: item.content,
      created_at: item.created_at,
      ...(item.answer_status !== undefined ? { answer_status: item.answer_status } : {}),
    }),
  );
  return {
    session_id: parsed.session_id,
    mode: parsed.mode,
    selected_case_id: parsed.selected_case_id,
    messages,
  };
}

export function parseDeleteChatSessionResponse(
  value: unknown,
): { deleted: boolean; session_id: string } | null {
  return parseWithSchema(schemas.DeleteChatSessionResponse, value);
}

export function parseDeleteLastChatTurnResponse(
  value: unknown,
): { deleted: boolean; session_id: string; deleted_messages: number } | null {
  return parseWithSchema(schemas.DeleteLastChatTurnResponse, value);
}

export function parseHealthResponse(
  value: unknown,
): { status: string; case_retention_days?: number } | null {
  const parsed = parseWithSchema(schemas.HealthResponse, value);
  if (!parsed) {
    return null;
  }
  if (
    typeof value === "object" &&
    value !== null &&
    "case_retention_days" in value &&
    typeof (value as { case_retention_days?: unknown }).case_retention_days === "number"
  ) {
    return {
      status: parsed.status,
      case_retention_days: (value as { case_retention_days: number }).case_retention_days,
    };
  }
  return { status: parsed.status };
}
