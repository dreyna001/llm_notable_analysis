export type CaseSummary = {
  case_id: string;
  processed_at: string | null;
  expires_at: string | null;
  verdict: string | null;
  confidence: number | null;
  search_name: string | null;
  retrieval_status: string;
  source_completeness: string;
  archive_notices?: string[];
};

export type CaseListCursor = {
  processed_at: string;
  case_id: string;
};

export type CaseListResponse = {
  items: CaseSummary[];
  limit: number;
  has_more: boolean;
  next_cursor: CaseListCursor | null;
};

export type CaseDetailContentBounds = {
  alert_payload_truncated: boolean;
  analysis_truncated: boolean;
  alert_payload_total_keys: number;
  analysis_total_keys: number;
  raw_sections: Array<"alert_payload" | "analysis">;
};

export type CaseDetail = {
  case_id: string;
  metadata: {
    processed_at: string | null;
    expires_at: string | null;
    retrieval_status: string;
    source_completeness: string;
    archive_notices?: string[];
  };
  alert_payload: Record<string, unknown>;
  analysis: Record<string, unknown> | null;
  report_md_path: string | null;
  report_html_path: string | null;
  content_bounds: CaseDetailContentBounds;
};

export type CaseRawSection = "alert_payload" | "analysis";

export type CaseRawSectionResponse = {
  case_id: string;
  section: CaseRawSection;
  offset: number;
  limit: number;
  has_more: boolean;
  total_keys: number;
  items: Record<string, unknown>;
};

export type ChatMode = "selected_case";

export type ChatImageMediaType =
  | "image/png"
  | "image/jpeg"
  | "image/webp"
  | "image/gif";

export type ChatImagePayload = {
  media_type: ChatImageMediaType;
  data_base64: string;
};

export type ChatRequest = {
  mode: ChatMode;
  question: string;
  selected_case_id?: string;
  session_id?: string | null;
  images?: ChatImagePayload[];
};

export type ChatContextUsageSegment = {
  id: string;
  label: string;
  chars: number;
  tokens: number;
};

export type ChatContextUsage = {
  kind: "case_grounded" | "general_knowledge";
  prompt_chars: number;
  prompt_tokens: number;
  context_limit_tokens: number;
  utilization_pct: number;
  segments: ChatContextUsageSegment[];
  estimate_method: "chars_per_token" | "tiktoken";
  chars_per_token_estimate: number;
  current_question_chars: number;
};

export type ChatResponse = {
  answer: string;
  answer_status: "answered" | "unknown" | "refused" | string;
  session_id: string | null;
  context_usage?: ChatContextUsage | null;
};

export type ChatSessionSummary = {
  session_id: string;
  title: string;
  updated_at: string | null;
  mode: ChatMode;
  selected_case_id: string | null;
};

export type ChatSessionsResponse = {
  history_enabled: boolean;
  items: ChatSessionSummary[];
};

export type ChatSessionMessage = {
  role: string;
  content: string;
  created_at: string | null;
  answer_status?: ChatResponse["answer_status"] | null;
};

export type ChatSessionMessagesResponse = {
  session_id: string;
  mode: ChatMode;
  selected_case_id: string | null;
  messages: ChatSessionMessage[];
};

export type ChatDependencyStatus = {
  embeddings: "ready" | "unavailable";
  archive_retrieval: "ready" | "unavailable";
  llm_gateway: "ready" | "unavailable";
};

export type PortalCapabilities = {
  case_qa_enabled: boolean;
  chat_history_enabled: boolean;
  general_knowledge_enabled: boolean;
  max_question_chars: number;
  max_answer_tokens: number;
  model_context_tokens: number;
  max_chat_sessions_per_user?: number;
  case_retention_days?: number;
  chat_ready: boolean;
  chat_dependency_status?: ChatDependencyStatus | null;
  chat_degraded_reason?: string | null;
  chat_images_enabled?: boolean;
  max_chat_images?: number;
  max_chat_image_bytes?: number;
};
