"""Approval-gated writeback orchestration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import WritebackDraft, WritebackResult
from .validators import normalize_optional_string, require_bool
from .vocabulary import WritebackStatus


class WritebackAdapter(Protocol):
    """Adapter seam for approved downstream writeback operations."""

    def write(self, draft: WritebackDraft) -> WritebackResult:
        """Write one already-approved draft to a downstream system."""


@dataclass(slots=True)
class WritebackApproval:
    """Runtime approval state for one writeback attempt."""

    approved: bool
    approved_by: str | None = None
    approval_ref: str | None = None

    def __post_init__(self) -> None:
        """Validate approval fields."""
        self.approved = require_bool(self.approved, "approved")
        self.approved_by = normalize_optional_string(self.approved_by, "approved_by")
        self.approval_ref = normalize_optional_string(self.approval_ref, "approval_ref")
        if self.approved and self.approved_by is None:
            raise ValueError("Approved writeback requires approved_by.")
        if self.approved and self.approval_ref is None:
            raise ValueError("Approved writeback requires approval_ref.")


def execute_writeback_with_approval(
    *,
    draft: WritebackDraft,
    adapter: WritebackAdapter,
    approval: WritebackApproval,
) -> WritebackResult:
    """Execute writeback only when explicit runtime approval is present."""
    if not isinstance(draft, WritebackDraft):
        raise ValueError("Field 'draft' must be WritebackDraft.")
    if not isinstance(approval, WritebackApproval):
        raise ValueError("Field 'approval' must be WritebackApproval.")

    if not approval.approved:
        return WritebackResult(
            status=WritebackStatus.DENIED,
            target_system=draft.target_system,
            external_id=draft.external_ref,
            message="Writeback denied because explicit runtime approval is missing.",
            metadata={"target_operation": draft.target_operation},
        )

    result = adapter.write(draft)
    if not isinstance(result, WritebackResult):
        raise ValueError("Writeback adapter must return WritebackResult.")
    result.metadata = {
        **result.metadata,
        "approved_by": approval.approved_by,
        "approval_ref": approval.approval_ref,
    }
    return result
