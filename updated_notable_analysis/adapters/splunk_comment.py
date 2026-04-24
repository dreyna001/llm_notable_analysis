"""Splunk notable-comment writeback adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from updated_notable_analysis.core.models import WritebackDraft, WritebackResult
from updated_notable_analysis.core.validators import (
    normalize_mapping,
    normalize_optional_string,
    require_int_gt_zero,
    require_non_empty_string,
)
from updated_notable_analysis.core.vocabulary import WritebackStatus


class SplunkCommentTransport(Protocol):
    """Minimal transport contract for bounded Splunk notable comments."""

    def post_comment(
        self,
        *,
        notable_id: str,
        comment: str,
        timeout_seconds: int,
        metadata: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Post one comment to a configured Splunk notable target."""


@dataclass(slots=True)
class SplunkCommentWritebackAdapter:
    """Write approved bounded comments to Splunk notable events."""

    transport: SplunkCommentTransport
    max_comment_chars: int = 4000
    timeout_seconds: int = 10

    def __post_init__(self) -> None:
        """Validate adapter configuration."""
        if not hasattr(self.transport, "post_comment"):
            raise ValueError("Field 'transport' must provide post_comment(...).")
        self.max_comment_chars = require_int_gt_zero(self.max_comment_chars, "max_comment_chars")
        self.timeout_seconds = require_int_gt_zero(self.timeout_seconds, "timeout_seconds")

    def write(self, draft: WritebackDraft) -> WritebackResult:
        """Write one approved Splunk notable comment draft."""
        _validate_splunk_comment_draft(draft, self.max_comment_chars)
        notable_id = require_non_empty_string(draft.external_ref, "external_ref")
        metadata = {
            **draft.fields,
            "routing_key": draft.routing_key,
            "target_operation": draft.target_operation,
            "summary": draft.summary,
        }
        response = self.transport.post_comment(
            notable_id=notable_id,
            comment=draft.body,
            timeout_seconds=self.timeout_seconds,
            metadata=metadata,
        )
        if not isinstance(response, Mapping):
            raise ValueError("Splunk comment transport must return a mapping.")
        return _normalize_transport_response(response, notable_id)


def _validate_splunk_comment_draft(draft: WritebackDraft, max_comment_chars: int) -> None:
    """Validate Splunk-comment-specific writeback bounds."""
    if not isinstance(draft, WritebackDraft):
        raise ValueError("Field 'draft' must be WritebackDraft.")
    if draft.target_system.lower() != "splunk":
        raise ValueError("Splunk comment adapter only supports target_system='splunk'.")
    if draft.target_operation.lower() != "notable_comment":
        raise ValueError("Splunk comment adapter requires target_operation='notable_comment'.")
    if draft.external_ref is None:
        raise ValueError("Splunk comment drafts require external_ref notable id.")
    if len(draft.body) > max_comment_chars:
        raise ValueError("Splunk comment draft body exceeds max_comment_chars.")


def _normalize_transport_response(
    response: Mapping[str, Any], notable_id: str
) -> WritebackResult:
    """Normalize Splunk comment transport response into WritebackResult."""
    response_dict = dict(response)
    raw_status = normalize_optional_string(response_dict.get("status"), "status") or "success"
    if raw_status not in {WritebackStatus.SUCCESS.value, WritebackStatus.ERROR.value}:
        raise ValueError("Splunk comment response status must be success or error.")

    comment_id = normalize_optional_string(response_dict.get("comment_id"), "comment_id")
    message = normalize_optional_string(response_dict.get("message"), "message")
    metadata = normalize_mapping(response_dict.get("metadata"), "metadata")
    metadata["adapter"] = "splunk_comment"
    metadata["notable_id"] = notable_id
    if comment_id is not None:
        metadata["comment_id"] = comment_id

    return WritebackResult(
        status=raw_status,
        target_system="splunk",
        external_id=comment_id or notable_id,
        message=message or "Splunk notable comment writeback completed.",
        metadata=metadata,
    )
