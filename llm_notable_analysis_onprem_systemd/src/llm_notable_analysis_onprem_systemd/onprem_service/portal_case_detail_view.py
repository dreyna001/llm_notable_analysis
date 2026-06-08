"""Bounded case detail view models and paginated raw JSON helpers for the portal."""

from __future__ import annotations

import json
from typing import Any, Literal

from .case_store import CaseArchiveRecord

RawSection = Literal["alert_payload", "analysis"]

_ANALYSIS_VIEW_KEYS = frozenset(
    {
        "alert_reconciliation",
        "competing_hypotheses",
        "actions",
        "ttp_analysis",
        "ioc_extraction",
        "evidence_vs_inference",
        "query_result_section",
        "query_result_interpretation",
        "servicenow_section",
        "verdict",
        "confidence",
        "final_verdict",
    }
)
_ALERT_PRIORITY_KEYS = frozenset(
    {
        "search_name",
        "searchName",
        "rule_name",
        "rule",
        "signature",
        "title",
        "notable_id",
        "event_id",
        "finding_id",
        "risk_score",
        "riskScore",
        "threat_category",
        "alert_time",
        "user",
        "host",
        "src",
        "dest",
        "process",
    }
)

_MAX_VIEW_JSON_BYTES = 256_000
_MAX_RAW_PAGE_KEYS = 100
_DEFAULT_RAW_PAGE_KEYS = 50
_MAX_STRING_CHARS = 8_000
_MAX_LIST_ITEMS = 100
_MAX_DICT_KEYS = 200
_MAX_JSON_DEPTH = 12
_TRUNCATED_SUFFIX = "…"


def _json_byte_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("utf-8"))


def _bound_json_value(
    value: Any,
    *,
    max_string_chars: int = _MAX_STRING_CHARS,
    max_list_items: int = _MAX_LIST_ITEMS,
    max_dict_keys: int = _MAX_DICT_KEYS,
    depth: int = 0,
    max_depth: int = _MAX_JSON_DEPTH,
) -> Any:
    if depth > max_depth:
        return _TRUNCATED_SUFFIX
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= max_string_chars:
            return value
        keep = max(0, max_string_chars - len(_TRUNCATED_SUFFIX))
        return value[:keep] + _TRUNCATED_SUFFIX
    if isinstance(value, list):
        bounded = [
            _bound_json_value(
                item,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
                max_dict_keys=max_dict_keys,
                depth=depth + 1,
                max_depth=max_depth,
            )
            for item in value[:max_list_items]
        ]
        omitted = len(value) - max_list_items
        if omitted > 0:
            bounded.append(f"{_TRUNCATED_SUFFIX} {omitted} more items omitted")
        return bounded
    if isinstance(value, dict):
        keys = sorted(value.keys(), key=lambda item: str(item))
        selected = keys[:max_dict_keys]
        bounded = {
            str(key): _bound_json_value(
                value[key],
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
                max_dict_keys=max_dict_keys,
                depth=depth + 1,
                max_depth=max_depth,
            )
            for key in selected
        }
        omitted = len(value) - len(selected)
        if omitted > 0:
            bounded["_truncated_key_count"] = omitted
        return bounded
    text = str(value)
    if len(text) <= max_string_chars:
        return text
    keep = max(0, max_string_chars - len(_TRUNCATED_SUFFIX))
    return text[:keep] + _TRUNCATED_SUFFIX


def _object_key_count(value: Any) -> int:
    if isinstance(value, dict):
        return len(value)
    return 0


def _ordered_alert_keys(payload: dict[str, Any]) -> list[str]:
    keys = [str(key) for key in payload.keys()]
    priority = [key for key in keys if key in _ALERT_PRIORITY_KEYS]
    remainder = sorted(key for key in keys if key not in _ALERT_PRIORITY_KEYS)
    return priority + remainder


def _build_bounded_alert_view(payload: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    if not payload:
        return {}, False
    ordered_keys = _ordered_alert_keys(payload)
    view: dict[str, Any] = {}
    truncated = False
    for key in ordered_keys:
        candidate = dict(view)
        candidate[key] = _bound_json_value(payload[key])
        if _json_byte_size(candidate) > _MAX_VIEW_JSON_BYTES // 2:
            truncated = True
            break
        view = candidate
    if len(view) < len(payload):
        truncated = True
    return view, truncated


def _build_bounded_analysis_view(analysis: dict[str, Any] | None) -> tuple[dict[str, Any] | None, bool]:
    if analysis is None:
        return None, False
    view: dict[str, Any] = {}
    truncated = False
    for key in sorted(_ANALYSIS_VIEW_KEYS):
        if key not in analysis:
            continue
        candidate = dict(view)
        candidate[key] = _bound_json_value(analysis[key])
        if _json_byte_size(candidate) > _MAX_VIEW_JSON_BYTES // 2:
            truncated = True
            break
        view[key] = candidate[key]
    if len(view) < len(analysis):
        truncated = True
    return (view or None), truncated


def build_case_detail_view(record: CaseArchiveRecord) -> dict[str, Any]:
    """Build a bounded portal case detail view from one archive record."""
    alert_source = record.alert_payload if isinstance(record.alert_payload, dict) else {}
    analysis_source = record.analysis if isinstance(record.analysis, dict) else None

    alert_payload, alert_truncated = _build_bounded_alert_view(alert_source)
    analysis, analysis_truncated = _build_bounded_analysis_view(analysis_source)

    combined_size = _json_byte_size({"alert_payload": alert_payload, "analysis": analysis})
    if combined_size > _MAX_VIEW_JSON_BYTES:
        alert_truncated = True
        analysis_truncated = True

    raw_sections: list[str] = []
    if alert_source:
        raw_sections.append("alert_payload")
    if analysis_source is not None:
        raw_sections.append("analysis")

    return {
        "alert_payload": alert_payload,
        "analysis": analysis,
        "content_bounds": {
            "alert_payload_truncated": alert_truncated,
            "analysis_truncated": analysis_truncated,
            "alert_payload_total_keys": _object_key_count(alert_source),
            "analysis_total_keys": _object_key_count(analysis_source),
            "raw_sections": raw_sections,
        },
    }


def _normalize_raw_section(section: str) -> RawSection:
    normalized = str(section or "").strip()
    if normalized not in {"alert_payload", "analysis"}:
        raise ValueError("section must be alert_payload or analysis.")
    return normalized  # type: ignore[return-value]


def _section_source(record: CaseArchiveRecord, section: RawSection) -> dict[str, Any] | None:
    if section == "alert_payload":
        payload = record.alert_payload
        return payload if isinstance(payload, dict) else {}
    analysis = record.analysis
    return analysis if isinstance(analysis, dict) else None


def build_case_raw_section_page(
    record: CaseArchiveRecord,
    *,
    section: str,
    offset: int,
    limit: int,
    key: str | None = None,
) -> dict[str, Any]:
    """Return one paginated page of raw alert or analysis JSON."""
    normalized_section = _normalize_raw_section(section)
    page_limit = max(1, min(int(limit), _MAX_RAW_PAGE_KEYS))
    page_offset = max(0, int(offset))
    source = _section_source(record, normalized_section)
    if source is None:
        raise LookupError("analysis is not available for this case.")

    if key is not None:
        normalized_key = str(key).strip()
        if not normalized_key:
            raise ValueError("key must be non-empty when provided.")
        if normalized_key not in source:
            raise LookupError(f"{normalized_key!r} was not found in {normalized_section}.")
        return {
            "case_id": record.case_id,
            "section": normalized_section,
            "offset": 0,
            "limit": 1,
            "has_more": False,
            "total_keys": len(source),
            "items": {normalized_key: _bound_json_value(source[normalized_key])},
        }

    ordered_keys = (
        _ordered_alert_keys(source)
        if normalized_section == "alert_payload"
        else sorted(str(item) for item in source.keys())
    )
    page_keys = ordered_keys[page_offset : page_offset + page_limit]
    items = {item: _bound_json_value(source[item]) for item in page_keys}
    next_offset = page_offset + len(page_keys)
    return {
        "case_id": record.case_id,
        "section": normalized_section,
        "offset": page_offset,
        "limit": page_limit,
        "has_more": next_offset < len(ordered_keys),
        "total_keys": len(ordered_keys),
        "items": items,
    }


def default_raw_page_limit() -> int:
    return _DEFAULT_RAW_PAGE_KEYS
