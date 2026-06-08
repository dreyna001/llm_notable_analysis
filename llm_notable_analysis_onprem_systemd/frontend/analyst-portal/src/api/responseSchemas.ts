import type {
  CaseDetail,
  CaseListResponse,
  CaseSummary,
  ChatMode,
  ChatResponse,
  ChatSessionMessage,
  ChatSessionMessagesResponse,
  ChatSessionsResponse,
  ChatSessionSummary,
  PortalCapabilities,
} from "../types";

export const INVALID_RESPONSE_MESSAGE =
  "Portal API returned an unexpected response.";

const CHAT_MODES = new Set<ChatMode>(["selected_case", "global_archive"]);

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isBoolean(value: unknown): value is boolean {
  return typeof value === "boolean";
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function parseChatMode(value: unknown): ChatMode | null {
  if (typeof value === "string" && CHAT_MODES.has(value as ChatMode)) {
    return value as ChatMode;
  }
  return null;
}

function parseNullableRecord(value: unknown): Record<string, unknown> | null {
  if (value === null) {
    return null;
  }
  return isObject(value) ? value : null;
}

function parseCaseSummary(value: unknown): CaseSummary | null {
  if (!isObject(value)) {
    return null;
  }
  if (!isString(value.case_id)) {
    return null;
  }
  if (!isNullableString(value.processed_at)) {
    return null;
  }
  if (!isNullableString(value.expires_at)) {
    return null;
  }
  if (value.verdict !== null && !isString(value.verdict)) {
    return null;
  }
  if (value.confidence !== null && !isNumber(value.confidence)) {
    return null;
  }
  if (value.search_name !== null && !isString(value.search_name)) {
    return null;
  }
  if (!isString(value.retrieval_status)) {
    return null;
  }
  if (!isString(value.source_completeness)) {
    return null;
  }
  if (value.archive_notices !== undefined && !isStringArray(value.archive_notices)) {
    return null;
  }
  return {
    case_id: value.case_id,
    processed_at: value.processed_at,
    expires_at: value.expires_at,
    verdict: value.verdict ?? null,
    confidence: value.confidence ?? null,
    search_name: value.search_name ?? null,
    retrieval_status: value.retrieval_status,
    source_completeness: value.source_completeness,
    ...(value.archive_notices ? { archive_notices: value.archive_notices } : {}),
  };
}

export function parseCaseListResponse(value: unknown): CaseListResponse | null {
  if (!isObject(value) || !Array.isArray(value.items)) {
    return null;
  }
  if (!isNumber(value.limit) || !isNumber(value.offset) || !isBoolean(value.has_more)) {
    return null;
  }
  const items: CaseSummary[] = [];
  for (const item of value.items) {
    const parsed = parseCaseSummary(item);
    if (!parsed) {
      return null;
    }
    items.push(parsed);
  }
  return {
    items,
    limit: value.limit,
    offset: value.offset,
    has_more: value.has_more,
  };
}

function parseCaseDetailMetadata(
  value: unknown,
): CaseDetail["metadata"] | null {
  if (!isObject(value)) {
    return null;
  }
  if (!isNullableString(value.processed_at)) {
    return null;
  }
  if (!isNullableString(value.expires_at)) {
    return null;
  }
  if (!isString(value.retrieval_status)) {
    return null;
  }
  if (!isString(value.source_completeness)) {
    return null;
  }
  if (value.archive_notices !== undefined && !isStringArray(value.archive_notices)) {
    return null;
  }
  return {
    processed_at: value.processed_at,
    expires_at: value.expires_at,
    retrieval_status: value.retrieval_status,
    source_completeness: value.source_completeness,
    ...(value.archive_notices ? { archive_notices: value.archive_notices } : {}),
  };
}

export function parseCaseDetail(value: unknown): CaseDetail | null {
  if (!isObject(value) || !isString(value.case_id)) {
    return null;
  }
  const metadata = parseCaseDetailMetadata(value.metadata);
  if (!metadata) {
    return null;
  }
  const alertPayload = parseNullableRecord(value.alert_payload);
  if (alertPayload === null && value.alert_payload !== null) {
    return null;
  }
  const analysis = parseNullableRecord(value.analysis);
  if (analysis === null && value.analysis !== null) {
    return null;
  }
  if (!isNullableString(value.report_md_path)) {
    return null;
  }
  if (!isNullableString(value.report_html_path)) {
    return null;
  }
  return {
    case_id: value.case_id,
    metadata,
    alert_payload: alertPayload ?? {},
    analysis,
    report_md_path: value.report_md_path,
    report_html_path: value.report_html_path,
  };
}

export function parsePortalCapabilities(value: unknown): PortalCapabilities | null {
  if (!isObject(value)) {
    return null;
  }
  if (
    !isBoolean(value.case_qa_enabled) ||
    !isBoolean(value.global_retrieval_enabled) ||
    !isBoolean(value.chat_history_enabled) ||
    !isBoolean(value.general_knowledge_enabled) ||
    !isNumber(value.max_question_chars) ||
    !isNumber(value.max_answer_tokens)
  ) {
    return null;
  }
  if (
    value.max_chat_sessions_per_user !== undefined &&
    !isNumber(value.max_chat_sessions_per_user)
  ) {
    return null;
  }
  if (value.case_retention_days !== undefined && !isNumber(value.case_retention_days)) {
    return null;
  }
  return {
    case_qa_enabled: value.case_qa_enabled,
    global_retrieval_enabled: value.global_retrieval_enabled,
    chat_history_enabled: value.chat_history_enabled,
    general_knowledge_enabled: value.general_knowledge_enabled,
    max_question_chars: value.max_question_chars,
    max_answer_tokens: value.max_answer_tokens,
    ...(value.max_chat_sessions_per_user !== undefined
      ? { max_chat_sessions_per_user: value.max_chat_sessions_per_user }
      : {}),
    ...(value.case_retention_days !== undefined
      ? { case_retention_days: value.case_retention_days }
      : {}),
  };
}

export function parseChatResponse(value: unknown): ChatResponse | null {
  if (!isObject(value)) {
    return null;
  }
  if (!isString(value.answer) || !isString(value.answer_status)) {
    return null;
  }
  if (value.session_id !== null && !isString(value.session_id)) {
    return null;
  }
  return {
    answer: value.answer,
    answer_status: value.answer_status,
    session_id: value.session_id ?? null,
  };
}

function parseChatSessionSummary(value: unknown): ChatSessionSummary | null {
  if (!isObject(value)) {
    return null;
  }
  const mode = parseChatMode(value.mode);
  if (!mode || !isString(value.session_id) || !isString(value.title)) {
    return null;
  }
  if (!isNullableString(value.updated_at)) {
    return null;
  }
  if (value.selected_case_id !== null && !isString(value.selected_case_id)) {
    return null;
  }
  return {
    session_id: value.session_id,
    title: value.title,
    updated_at: value.updated_at,
    mode,
    selected_case_id: value.selected_case_id ?? null,
  };
}

export function parseChatSessionsResponse(
  value: unknown,
): ChatSessionsResponse | null {
  if (!isObject(value) || !isBoolean(value.history_enabled) || !Array.isArray(value.items)) {
    return null;
  }
  const items: ChatSessionSummary[] = [];
  for (const item of value.items) {
    const parsed = parseChatSessionSummary(item);
    if (!parsed) {
      return null;
    }
    items.push(parsed);
  }
  return {
    history_enabled: value.history_enabled,
    items,
  };
}

function parseChatSessionMessage(value: unknown): ChatSessionMessage | null {
  if (!isObject(value)) {
    return null;
  }
  if (!isString(value.role) || !isString(value.content)) {
    return null;
  }
  if (!isNullableString(value.created_at)) {
    return null;
  }
  if (
    value.answer_status !== undefined &&
    value.answer_status !== null &&
    !isString(value.answer_status)
  ) {
    return null;
  }
  return {
    role: value.role,
    content: value.content,
    created_at: value.created_at,
    ...(value.answer_status !== undefined ? { answer_status: value.answer_status } : {}),
  };
}

export function parseChatSessionMessagesResponse(
  value: unknown,
): ChatSessionMessagesResponse | null {
  if (!isObject(value) || !isString(value.session_id) || !Array.isArray(value.messages)) {
    return null;
  }
  const mode = parseChatMode(value.mode);
  if (!mode) {
    return null;
  }
  if (value.selected_case_id !== null && !isString(value.selected_case_id)) {
    return null;
  }
  const messages: ChatSessionMessage[] = [];
  for (const item of value.messages) {
    const parsed = parseChatSessionMessage(item);
    if (!parsed) {
      return null;
    }
    messages.push(parsed);
  }
  return {
    session_id: value.session_id,
    mode,
    selected_case_id: value.selected_case_id ?? null,
    messages,
  };
}

export function parseDeleteChatSessionResponse(
  value: unknown,
): { deleted: boolean; session_id: string } | null {
  if (!isObject(value) || !isBoolean(value.deleted) || !isString(value.session_id)) {
    return null;
  }
  return {
    deleted: value.deleted,
    session_id: value.session_id,
  };
}

export function parseDeleteLastChatTurnResponse(
  value: unknown,
): { deleted: boolean; session_id: string; deleted_messages: number } | null {
  if (
    !isObject(value) ||
    !isBoolean(value.deleted) ||
    !isString(value.session_id) ||
    !isNumber(value.deleted_messages)
  ) {
    return null;
  }
  return {
    deleted: value.deleted,
    session_id: value.session_id,
    deleted_messages: value.deleted_messages,
  };
}

export function parseHealthResponse(
  value: unknown,
): { status: string; case_retention_days?: number } | null {
  if (!isObject(value) || !isString(value.status)) {
    return null;
  }
  if (value.case_retention_days !== undefined && !isNumber(value.case_retention_days)) {
    return null;
  }
  return {
    status: value.status,
    ...(value.case_retention_days !== undefined
      ? { case_retention_days: value.case_retention_days }
      : {}),
  };
}
