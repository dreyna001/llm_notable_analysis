"""Approval-gated ServiceNow incident creation adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from updated_notable_analysis.core.models import WritebackDraft, WritebackResult
from updated_notable_analysis.core.validators import (
    normalize_mapping,
    normalize_optional_string,
    require_int_gt_zero,
)
from updated_notable_analysis.core.vocabulary import WritebackStatus


class ServiceNowIncidentTransport(Protocol):
    """Minimal transport contract for creating ServiceNow incidents."""

    def create_incident(
        self,
        *,
        payload: Mapping[str, Any],
        timeout_seconds: int,
    ) -> Mapping[str, Any]:
        """Create one ServiceNow incident from an approved draft payload."""


@dataclass(slots=True)
class ServiceNowIncidentCreateAdapter:
    """Create ServiceNow incidents from approved incident draft writebacks."""

    transport: ServiceNowIncidentTransport
    timeout_seconds: int = 15

    def __post_init__(self) -> None:
        """Validate adapter configuration."""
        if not hasattr(self.transport, "create_incident"):
            raise ValueError("Field 'transport' must provide create_incident(...).")
        self.timeout_seconds = require_int_gt_zero(self.timeout_seconds, "timeout_seconds")

    def write(self, draft: WritebackDraft) -> WritebackResult:
        """Create one ServiceNow incident from an approved draft."""
        _validate_servicenow_incident_draft(draft)
        payload = _build_create_payload(draft)
        response = self.transport.create_incident(
            payload=payload,
            timeout_seconds=self.timeout_seconds,
        )
        if not isinstance(response, Mapping):
            raise ValueError("ServiceNow incident transport must return a mapping.")
        return _normalize_create_response(response, draft)


def _validate_servicenow_incident_draft(draft: WritebackDraft) -> None:
    """Validate ServiceNow-create-specific draft requirements."""
    if not isinstance(draft, WritebackDraft):
        raise ValueError("Field 'draft' must be WritebackDraft.")
    if draft.target_system.lower() != "servicenow":
        raise ValueError("ServiceNow create adapter only supports target_system='servicenow'.")
    if draft.target_operation.lower() != "incident_draft":
        raise ValueError("ServiceNow create adapter requires target_operation='incident_draft'.")
    if not draft.fields:
        raise ValueError("ServiceNow create adapter requires draft fields.")
    if draft.fields.get("draft_only") is not True:
        raise ValueError("ServiceNow create adapter requires draft_only=True fields.")


def _build_create_payload(draft: WritebackDraft) -> dict[str, Any]:
    """Build a ServiceNow incident create payload from a validated draft."""
    payload = dict(draft.fields)
    payload.pop("draft_only", None)
    payload["short_description"] = draft.summary
    payload["description"] = draft.body
    if draft.routing_key is not None:
        payload["assignment_group"] = draft.routing_key
    if draft.external_ref is not None:
        payload["correlation_id"] = draft.external_ref
    payload["correlation_display"] = "updated_notable_analysis"
    return payload


def _normalize_create_response(
    response: Mapping[str, Any], draft: WritebackDraft
) -> WritebackResult:
    """Normalize ServiceNow create response into WritebackResult."""
    response_dict = dict(response)
    raw_status = normalize_optional_string(response_dict.get("status"), "status") or "success"
    if raw_status not in {WritebackStatus.SUCCESS.value, WritebackStatus.ERROR.value}:
        raise ValueError("ServiceNow create response status must be success or error.")

    sys_id = normalize_optional_string(response_dict.get("sys_id"), "sys_id")
    number = normalize_optional_string(response_dict.get("number"), "number")
    message = normalize_optional_string(response_dict.get("message"), "message")
    metadata = normalize_mapping(response_dict.get("metadata"), "metadata")
    metadata["adapter"] = "servicenow_incident_create"
    metadata["target_operation"] = "incident_create"
    metadata["source_draft_operation"] = draft.target_operation
    if draft.external_ref is not None:
        metadata["source_record_ref"] = draft.external_ref
    if number is not None:
        metadata["number"] = number
    if sys_id is not None:
        metadata["sys_id"] = sys_id

    return WritebackResult(
        status=raw_status,
        target_system="servicenow",
        external_id=sys_id or number or draft.external_ref,
        message=message or _default_message(raw_status),
        metadata=metadata,
    )


def _default_message(status: str) -> str:
    """Return a default ServiceNow create result message."""
    if status == WritebackStatus.ERROR.value:
        return "ServiceNow incident creation failed."
    return "ServiceNow incident created."
