"""Pydantic response models for the AWS analyst portal API."""

from __future__ import annotations

from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict

ModelT = TypeVar("ModelT", bound=BaseModel)

ChatMode = Literal["selected_case"]


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str


class ChatDependencyStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    embeddings: Literal["ready", "unavailable"]
    archive_retrieval: Literal["ready", "unavailable"]
    llm_gateway: Literal["ready", "unavailable"]


class ChatContextUsageSegmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    chars: int
    tokens: int


class ChatContextUsageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["case_grounded", "general_knowledge"]
    prompt_chars: int
    prompt_tokens: int
    context_limit_tokens: int
    utilization_pct: int
    segments: list[ChatContextUsageSegmentResponse]
    estimate_method: Literal["chars_per_token", "tiktoken"]
    chars_per_token_estimate: float
    current_question_chars: int


class PortalCapabilitiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_qa_enabled: bool
    chat_history_enabled: bool
    general_knowledge_enabled: bool
    max_question_chars: int
    max_answer_tokens: int
    model_context_tokens: int
    max_chat_sessions_per_user: int
    case_retention_days: int
    chat_ready: bool
    chat_images_enabled: bool = False
    max_chat_image_bytes: int = 750_000
    max_chat_images: int = 1
    chat_dependency_status: ChatDependencyStatusResponse | None = None
    chat_degraded_reason: str | None = None


class CaseSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    processed_at: str
    expires_at: str
    verdict: str | None
    confidence: float | None
    search_name: str | None
    retrieval_status: str
    source_completeness: str
    archive_notices: list[str] | None = None


class CaseListCursorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    processed_at: str
    case_id: str


class CaseListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CaseSummaryResponse]
    limit: int
    has_more: bool
    next_cursor: CaseListCursorResponse | None = None


class CaseDetailMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    processed_at: str
    expires_at: str
    retrieval_status: str
    source_completeness: str
    archive_notices: list[str] | None = None


class CaseDetailContentBoundsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alert_payload_truncated: bool
    analysis_truncated: bool
    alert_payload_total_keys: int
    analysis_total_keys: int
    raw_sections: list[str]


class CaseDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    metadata: CaseDetailMetadataResponse
    alert_payload: dict[str, Any]
    analysis: dict[str, Any] | None
    report_md_path: str | None
    report_html_path: str | None
    content_bounds: CaseDetailContentBoundsResponse


class CaseRawSectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    section: Literal["alert_payload", "analysis"]
    offset: int
    limit: int
    has_more: bool
    total_keys: int
    items: dict[str, Any]


class ChatResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    answer_status: str
    session_id: str | None = None
    context_usage: ChatContextUsageResponse | None = None


class ChatSessionSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    title: str
    updated_at: str | None
    mode: ChatMode
    selected_case_id: str | None


class ChatSessionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    history_enabled: bool
    items: list[ChatSessionSummaryResponse]


class ChatSessionMessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    content: str
    created_at: str | None
    answer_status: str | None = None


class ChatSessionMessagesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    mode: ChatMode
    selected_case_id: str | None
    messages: list[ChatSessionMessageResponse]


class DeleteChatSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deleted: bool
    session_id: str


class DeleteLastChatTurnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deleted: bool
    session_id: str
    deleted_messages: int


def portal_response(model: type[ModelT], payload: Any) -> ModelT:
    """Validate a portal JSON payload against its response model."""

    return model.model_validate(payload)
