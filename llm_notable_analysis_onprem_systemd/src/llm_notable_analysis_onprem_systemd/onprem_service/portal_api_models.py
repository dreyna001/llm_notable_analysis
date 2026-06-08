"""Pydantic response models for the analyst portal HTTP API."""

from __future__ import annotations

from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict

ChatMode = Literal["selected_case", "global_archive"]

ModelT = TypeVar("ModelT", bound=BaseModel)


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str


class PortalCapabilitiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_qa_enabled: bool
    global_retrieval_enabled: bool
    chat_history_enabled: bool
    general_knowledge_enabled: bool
    max_question_chars: int
    max_answer_tokens: int
    max_chat_sessions_per_user: int
    case_retention_days: int


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


class CaseListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CaseSummaryResponse]
    limit: int
    offset: int
    has_more: bool


class CaseDetailMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    processed_at: str
    expires_at: str
    retrieval_status: str
    source_completeness: str
    archive_notices: list[str] | None = None


class CaseDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    metadata: CaseDetailMetadataResponse
    alert_payload: dict[str, Any]
    analysis: dict[str, Any] | None
    report_md_path: str | None
    report_html_path: str | None


class ChatResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    answer_status: str
    session_id: str | None = None


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
