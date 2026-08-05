import { makeApi, Zodios, type ZodiosOptions } from "@zodios/core";
import { z } from "zod";

const ChatDependencyStatusResponse = z.object({
  archive_retrieval: z.enum(["ready", "unavailable"]),
  embeddings: z.enum(["ready", "unavailable"]),
  llm_gateway: z.enum(["ready", "unavailable"]),
});
const PortalCapabilitiesResponse = z.object({
  case_qa_enabled: z.boolean(),
  case_retention_days: z.number().int(),
  chat_degraded_reason: z.union([z.string(), z.null()]).optional(),
  chat_dependency_status: z
    .union([ChatDependencyStatusResponse, z.null()])
    .optional(),
  chat_history_enabled: z.boolean(),
  chat_images_enabled: z.boolean().optional().default(false),
  chat_ready: z.boolean(),
  general_knowledge_enabled: z.boolean(),
  max_answer_tokens: z.number().int(),
  max_chat_image_bytes: z.number().int().optional().default(750000),
  max_chat_images: z.number().int().optional().default(1),
  max_chat_sessions_per_user: z.number().int(),
  max_question_chars: z.number().int(),
  model_context_tokens: z.number().int(),
});
const limit = z.union([z.string(), z.null()]).optional();
const CaseSummaryResponse = z.object({
  archive_notices: z.union([z.array(z.string()), z.null()]).optional(),
  case_id: z.string(),
  confidence: z.union([z.number(), z.null()]),
  expires_at: z.string(),
  processed_at: z.string(),
  retrieval_status: z.string(),
  search_name: z.union([z.string(), z.null()]),
  source_completeness: z.string(),
  verdict: z.union([z.string(), z.null()]),
});
const CaseListCursorResponse = z.object({
  case_id: z.string(),
  processed_at: z.string(),
});
const CaseListResponse = z.object({
  has_more: z.boolean(),
  items: z.array(CaseSummaryResponse),
  limit: z.number().int(),
  next_cursor: z.union([CaseListCursorResponse, z.null()]).optional(),
});
const ValidationError = z
  .object({
    loc: z.array(z.union([z.string(), z.number()])),
    msg: z.string(),
    type: z.string(),
  })
  .passthrough();
const HTTPValidationError = z
  .object({ detail: z.array(ValidationError) })
  .partial()
  .passthrough();
const CaseDetailContentBoundsResponse = z.object({
  alert_payload_total_keys: z.number().int(),
  alert_payload_truncated: z.boolean(),
  analysis_total_keys: z.number().int(),
  analysis_truncated: z.boolean(),
  raw_sections: z.array(z.string()),
});
const CaseDetailMetadataResponse = z.object({
  archive_notices: z.union([z.array(z.string()), z.null()]).optional(),
  expires_at: z.string(),
  processed_at: z.string(),
  retrieval_status: z.string(),
  source_completeness: z.string(),
});
const CaseDetailResponse = z.object({
  alert_payload: z.object({}).partial().passthrough(),
  analysis: z.union([z.object({}).partial().passthrough(), z.null()]),
  case_id: z.string(),
  content_bounds: CaseDetailContentBoundsResponse,
  metadata: CaseDetailMetadataResponse,
  report_html_path: z.union([z.string(), z.null()]),
  report_md_path: z.union([z.string(), z.null()]),
});
const CaseRawSectionResponse = z.object({
  case_id: z.string(),
  has_more: z.boolean(),
  items: z.object({}).partial().passthrough(),
  limit: z.number().int(),
  offset: z.number().int(),
  section: z.enum(["alert_payload", "analysis"]),
  total_keys: z.number().int(),
});
const ChatContextUsageSegmentResponse = z.object({
  chars: z.number().int(),
  id: z.string(),
  label: z.string(),
  tokens: z.number().int(),
});
const ChatContextUsageResponse = z.object({
  chars_per_token_estimate: z.number(),
  context_limit_tokens: z.number().int(),
  current_question_chars: z.number().int(),
  estimate_method: z.enum(["chars_per_token", "tiktoken"]),
  kind: z.enum(["case_grounded", "general_knowledge"]),
  prompt_chars: z.number().int(),
  prompt_tokens: z.number().int(),
  segments: z.array(ChatContextUsageSegmentResponse),
  utilization_pct: z.number().int(),
});
const ChatResponseModel = z.object({
  answer: z.string(),
  answer_status: z.string(),
  context_usage: z.union([ChatContextUsageResponse, z.null()]).optional(),
  session_id: z.union([z.string(), z.null()]).optional(),
});
const ChatSessionSummaryResponse = z.object({
  mode: z.string(),
  selected_case_id: z.union([z.string(), z.null()]),
  session_id: z.string(),
  title: z.string(),
  updated_at: z.union([z.string(), z.null()]),
});
const ChatSessionsResponse = z.object({
  history_enabled: z.boolean(),
  items: z.array(ChatSessionSummaryResponse),
});
const DeleteChatSessionResponse = z.object({
  deleted: z.boolean(),
  session_id: z.string(),
});
const ChatSessionMessageResponse = z.object({
  answer_status: z.union([z.string(), z.null()]).optional(),
  content: z.string(),
  created_at: z.union([z.string(), z.null()]),
  role: z.string(),
});
const ChatSessionMessagesResponse = z.object({
  messages: z.array(ChatSessionMessageResponse),
  mode: z.string(),
  selected_case_id: z.union([z.string(), z.null()]),
  session_id: z.string(),
});
const expected_message_count = z.union([z.number(), z.null()]).optional();
const DeleteLastChatTurnResponse = z.object({
  deleted: z.boolean(),
  deleted_messages: z.number().int(),
  session_id: z.string(),
});
const HealthResponse = z.object({ status: z.string() });

export const schemas = {
  ChatDependencyStatusResponse,
  PortalCapabilitiesResponse,
  limit,
  CaseSummaryResponse,
  CaseListCursorResponse,
  CaseListResponse,
  ValidationError,
  HTTPValidationError,
  CaseDetailContentBoundsResponse,
  CaseDetailMetadataResponse,
  CaseDetailResponse,
  CaseRawSectionResponse,
  ChatContextUsageSegmentResponse,
  ChatContextUsageResponse,
  ChatResponseModel,
  ChatSessionSummaryResponse,
  ChatSessionsResponse,
  DeleteChatSessionResponse,
  ChatSessionMessageResponse,
  ChatSessionMessagesResponse,
  expected_message_count,
  DeleteLastChatTurnResponse,
  HealthResponse,
};

const endpoints = makeApi([
  {
    method: "get",
    path: "/api/capabilities",
    alias: "api_capabilities_api_capabilities_get",
    requestFormat: "json",
    response: PortalCapabilitiesResponse,
  },
  {
    method: "get",
    path: "/api/cases",
    alias: "api_list_cases_api_cases_get",
    requestFormat: "json",
    parameters: [
      {
        name: "limit",
        type: "Query",
        schema: limit,
      },
      {
        name: "cursor_processed_at",
        type: "Query",
        schema: limit,
      },
      {
        name: "cursor_case_id",
        type: "Query",
        schema: limit,
      },
      {
        name: "start",
        type: "Query",
        schema: limit,
      },
      {
        name: "end",
        type: "Query",
        schema: limit,
      },
      {
        name: "start_date",
        type: "Query",
        schema: limit,
      },
      {
        name: "end_date",
        type: "Query",
        schema: limit,
      },
      {
        name: "verdict",
        type: "Query",
        schema: limit,
      },
      {
        name: "search_name",
        type: "Query",
        schema: limit,
      },
    ],
    response: CaseListResponse,
    errors: [
      {
        status: 422,
        description: `Validation Error`,
        schema: HTTPValidationError,
      },
    ],
  },
  {
    method: "get",
    path: "/api/cases/:case_id",
    alias: "api_get_case_api_cases__case_id__get",
    requestFormat: "json",
    parameters: [
      {
        name: "case_id",
        type: "Path",
        schema: z.string(),
      },
    ],
    response: CaseDetailResponse,
    errors: [
      {
        status: 422,
        description: `Validation Error`,
        schema: HTTPValidationError,
      },
    ],
  },
  {
    method: "get",
    path: "/api/cases/:case_id/raw/:section",
    alias: "api_get_case_raw_section_api_cases__case_id__raw__section__get",
    requestFormat: "json",
    parameters: [
      {
        name: "case_id",
        type: "Path",
        schema: z.string(),
      },
      {
        name: "section",
        type: "Path",
        schema: z.string(),
      },
      {
        name: "offset",
        type: "Query",
        schema: limit,
      },
      {
        name: "limit",
        type: "Query",
        schema: limit,
      },
      {
        name: "key",
        type: "Query",
        schema: limit,
      },
    ],
    response: CaseRawSectionResponse,
    errors: [
      {
        status: 422,
        description: `Validation Error`,
        schema: HTTPValidationError,
      },
    ],
  },
  {
    method: "post",
    path: "/api/chat",
    alias: "api_chat_api_chat_post",
    requestFormat: "json",
    parameters: [
      {
        name: "body",
        type: "Body",
        schema: z
          .object({
            client_request_id: z
              .string()
              .min(8)
              .max(128)
              .regex(/^[A-Za-z0-9._-]+$/)
              .optional(),
            mode: z.literal("selected_case").optional(),
            question: z.string().min(1),
            selected_case_id: z.string(),
            session_id: z.union([z.string(), z.null()]).optional(),
          })
          .passthrough(),
      },
    ],
    response: ChatResponseModel,
    errors: [
      {
        status: 422,
        description: `Validation Error`,
        schema: HTTPValidationError,
      },
    ],
  },
  {
    method: "get",
    path: "/api/chat/sessions",
    alias: "api_list_chat_sessions_api_chat_sessions_get",
    requestFormat: "json",
    parameters: [
      {
        name: "limit",
        type: "Query",
        schema: limit,
      },
    ],
    response: ChatSessionsResponse,
    errors: [
      {
        status: 422,
        description: `Validation Error`,
        schema: HTTPValidationError,
      },
    ],
  },
  {
    method: "delete",
    path: "/api/chat/sessions/:session_id",
    alias: "api_delete_chat_session_api_chat_sessions__session_id__delete",
    requestFormat: "json",
    parameters: [
      {
        name: "session_id",
        type: "Path",
        schema: z.string(),
      },
    ],
    response: DeleteChatSessionResponse,
    errors: [
      {
        status: 422,
        description: `Validation Error`,
        schema: HTTPValidationError,
      },
    ],
  },
  {
    method: "get",
    path: "/api/chat/sessions/:session_id/messages",
    alias:
      "api_get_chat_session_messages_api_chat_sessions__session_id__messages_get",
    requestFormat: "json",
    parameters: [
      {
        name: "session_id",
        type: "Path",
        schema: z.string(),
      },
    ],
    response: ChatSessionMessagesResponse,
    errors: [
      {
        status: 422,
        description: `Validation Error`,
        schema: HTTPValidationError,
      },
    ],
  },
  {
    method: "delete",
    path: "/api/chat/sessions/:session_id/turns/last",
    alias:
      "api_delete_last_chat_turn_api_chat_sessions__session_id__turns_last_delete",
    requestFormat: "json",
    parameters: [
      {
        name: "session_id",
        type: "Path",
        schema: z.string(),
      },
      {
        name: "expected_message_count",
        type: "Query",
        schema: expected_message_count,
      },
    ],
    response: DeleteLastChatTurnResponse,
    errors: [
      {
        status: 422,
        description: `Validation Error`,
        schema: HTTPValidationError,
      },
    ],
  },
  {
    method: "get",
    path: "/api/diagnostics/chat-readiness",
    alias: "api_chat_readiness_api_diagnostics_chat_readiness_get",
    requestFormat: "json",
    response: z.unknown(),
  },
  {
    method: "get",
    path: "/health",
    alias: "health_health_get",
    description: `Liveness probe for load balancers; intentionally minimal and unauthenticated.`,
    requestFormat: "json",
    response: z.object({ status: z.string() }),
  },
  {
    method: "get",
    path: "/ready",
    alias: "ready_ready_get",
    description: `Archive readiness for load balancers; does not probe chat LLM dependencies.`,
    requestFormat: "json",
    response: z.unknown(),
  },
]);

export const api = new Zodios(endpoints);

export function createApiClient(baseUrl: string, options?: ZodiosOptions) {
  return new Zodios(baseUrl, endpoints, options);
}
