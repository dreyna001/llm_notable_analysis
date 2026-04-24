"""Deterministic validation helpers for shared core contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence, TypeVar

from .vocabulary import EvidenceType

E = TypeVar("E", bound=Enum)


def require_non_empty_string(value: Any, field_name: str) -> str:
    """Validate a required non-empty string value."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Field {field_name!r} must be a non-empty string.")
    return value.strip()


def normalize_optional_string(value: Any, field_name: str) -> str | None:
    """Validate and normalize an optional string."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Field {field_name!r} must be a string when present.")
    stripped = value.strip()
    return stripped or None


def require_bool(value: Any, field_name: str) -> bool:
    """Validate a required boolean value."""
    if not isinstance(value, bool):
        raise ValueError(f"Field {field_name!r} must be a boolean.")
    return value


def require_int_gt_zero(value: Any, field_name: str) -> int:
    """Validate a required positive integer value."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"Field {field_name!r} must be an integer greater than zero.")
    return value


def normalize_optional_non_negative_int(value: Any, field_name: str) -> int | None:
    """Validate an optional non-negative integer value."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Field {field_name!r} must be a non-negative integer when present.")
    return value


def parse_datetime(value: Any, field_name: str) -> datetime:
    """Validate and parse datetime from datetime or ISO 8601 string."""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Field {field_name!r} must be a datetime or ISO 8601 string.")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Field {field_name!r} must be a valid ISO 8601 datetime.") from exc


def parse_enum(value: Any, enum_type: type[E], field_name: str) -> E:
    """Validate and parse enum from enum instance or string value."""
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value)
        except ValueError as exc:
            allowed = ", ".join(member.value for member in enum_type)
            raise ValueError(
                f"Field {field_name!r} must be one of: {allowed}."
            ) from exc
    raise ValueError(f"Field {field_name!r} must be {enum_type.__name__} or str.")


def normalize_string_list(
    values: Any, field_name: str, *, allow_empty: bool = True
) -> tuple[str, ...]:
    """Validate and normalize an iterable of strings."""
    if values is None:
        return ()
    if not isinstance(values, Iterable) or isinstance(values, (str, bytes)):
        raise ValueError(f"Field {field_name!r} must be a list-like of strings.")

    normalized = tuple(str(item).strip() for item in values if str(item).strip())
    if not allow_empty and not normalized:
        raise ValueError(f"Field {field_name!r} must contain at least one value.")
    return normalized


def normalize_mapping(value: Any, field_name: str) -> dict[str, Any]:
    """Validate and normalize mapping values into plain dictionaries."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"Field {field_name!r} must be a mapping.")
    return dict(value)


def validate_query_plan_contract(query_plan: Any) -> None:
    """Validate the core query-plan contract shape."""
    from .models import QueryPlan

    if not isinstance(query_plan, QueryPlan):
        raise ValueError("Query plan contract expects QueryPlan.")
    # Construction-level validation on QueryPlan already enforces required fields.


def validate_writeback_draft_contract(writeback_draft: Any) -> None:
    """Validate the writeback-draft contract shape."""
    from .models import WritebackDraft

    if not isinstance(writeback_draft, WritebackDraft):
        raise ValueError("Writeback draft contract expects WritebackDraft.")
    # Construction-level validation on WritebackDraft already enforces required fields.


def validate_analysis_report_contract(report: Any) -> None:
    """Validate the analysis-report contract shape and evidence section semantics."""
    from .models import AnalysisReport

    if not isinstance(report, AnalysisReport):
        raise ValueError("Analysis report contract expects AnalysisReport.")

    if not report.evidence_sections:
        raise ValueError("Analysis report must include at least one evidence section.")

    for section in report.evidence_sections:
        evidence_type = parse_enum(section.evidence_type, EvidenceType, "evidence_type")
        if evidence_type not in {
            EvidenceType.ALERT_DIRECT,
            EvidenceType.ADVISORY_CONTEXT,
            EvidenceType.QUERY_RESULT,
            EvidenceType.WORKFLOW_REPORTED,
            EvidenceType.OPERATOR_DECLARED,
        }:
            raise ValueError(f"Unsupported evidence type in report section: {evidence_type}")


def ensure_no_overlap(
    left: Sequence[Any], right: Sequence[Any], *, field_name: str
) -> None:
    """Raise when two sequences contain overlapping entries."""
    overlap = set(left).intersection(right)
    if overlap:
        overlap_str = ", ".join(sorted(str(item) for item in overlap))
        raise ValueError(f"Field {field_name!r} has overlapping values: {overlap_str}")

