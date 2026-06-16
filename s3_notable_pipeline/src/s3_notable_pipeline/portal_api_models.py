"""Pydantic response models for the AWS analyst portal API."""

from __future__ import annotations

from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict

ModelT = TypeVar("ModelT", bound=BaseModel)


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str


class ChatDependencyStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    embeddings: Literal["ready", "unavailable"]
    archive_retrieval: Literal["ready", "unavailable"]
    llm_gateway: Literal["ready", "unavailable"]


class PortalCapabilitiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_qa_enabled: bool
    chat_history_enabled: bool
    general_knowledge_enabled: bool
    max_question_chars: int
    max_answer_tokens: int
    max_chat_sessions_per_user: int
    case_retention_days: int
    chat_ready: bool
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


def portal_response(model: type[ModelT], payload: Any) -> ModelT:
    """Validate a portal JSON payload against its response model."""

    return model.model_validate(payload)
