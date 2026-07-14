"""Read-only Cosmos case-index and Blob case-envelope helpers."""

from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import date, datetime, time, timezone
from typing import Any

from .blob_store import read_blob
from .case_archive_notices import build_case_archive_notices
from .config import Config
from .cosmos_store import CosmosStore


def list_cases(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    limit: int | None = None,
    cursor: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    verdict: str | None = None,
    search_name: str | None = None,
) -> dict[str, Any]:
    """List cases with a bounded newest-first application keyset."""

    page_size = min(max(1, int(limit or config.PORTAL_PAGE_SIZE)), config.PORTAL_PAGE_SIZE)
    before = _decode_cursor(cursor) if cursor else None
    normalized_start = _normalized_timestamp(start_date, field_name="start_date", end=False)
    normalized_end = _normalized_timestamp(end_date, field_name="end_date", end=True)
    if normalized_start and normalized_end and normalized_start > normalized_end:
        raise ValueError("start_date must not be after end_date")
    normalized_verdict = _bounded_filter(verdict, field_name="verdict", max_chars=64)
    if normalized_verdict and not re.fullmatch(r"[A-Za-z0-9._-]+", normalized_verdict):
        raise ValueError("verdict is invalid")
    normalized_search = _bounded_filter(
        search_name,
        field_name="search_name",
        max_chars=256,
    )
    rows = cosmos_store.list_cases(
        config.CASE_INDEX_CONTAINER,
        limit=page_size + 1,
        before=before,
        start_date=normalized_start,
        end_date=normalized_end,
        verdict=normalized_verdict,
        search_name=normalized_search,
    )
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    return {
        "items": [_case_summary(row) for row in rows],
        "limit": page_size,
        "has_more": has_more,
        "next_cursor": _cursor_from_row(rows[-1]) if has_more and rows else None,
    }


def get_case_metadata(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    case_id: str,
) -> dict[str, Any] | None:
    """Fetch one case-index document by natural id."""

    return cosmos_store.get_case(config.CASE_INDEX_CONTAINER, case_id)


def get_case_detail(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    blob_service: Any,
    case_id: str,
) -> dict[str, Any] | None:
    """Assemble bounded case detail from Cosmos metadata and a Blob envelope."""

    metadata = get_case_metadata(config=config, cosmos_store=cosmos_store, case_id=case_id)
    if not metadata:
        return None
    envelope = _load_envelope(
        container_name=config.CASE_ARCHIVE_CONTAINER,
        blob_name=str(metadata.get("case_envelope_key", "")),
        blob_service=blob_service,
    )
    alert_payload = envelope.get("alert_payload")
    analysis = envelope.get("analysis")
    alert_dict = alert_payload if isinstance(alert_payload, dict) else {}
    analysis_dict = analysis if isinstance(analysis, dict) else None
    bounded_alert, alert_truncated, alert_total = _bounded_mapping(
        alert_dict, config.PORTAL_MAX_DETAIL_BYTES
    )
    bounded_analysis, analysis_truncated, analysis_total = _bounded_mapping(
        analysis_dict or {}, config.PORTAL_MAX_DETAIL_BYTES
    )
    artifacts = envelope.get("artifacts") if isinstance(envelope.get("artifacts"), dict) else {}
    retrieval_status = str(metadata.get("retrieval_status", "unknown"))
    source_completeness = str(metadata.get("source_completeness", "complete"))
    notices = build_case_archive_notices(
        retrieval_status=retrieval_status,
        source_completeness=source_completeness,
        archive_metadata=envelope.get("archive_metadata"),
    )
    return {
        "case_id": case_id,
        "metadata": {
            "processed_at": str(metadata.get("processed_at", "")),
            "expires_at": str(metadata.get("expires_at", "")),
            "retrieval_status": retrieval_status,
            "source_completeness": source_completeness,
            "archive_notices": notices or None,
        },
        "alert_payload": bounded_alert,
        "analysis": bounded_analysis if analysis_dict is not None else None,
        "report_md_path": artifacts.get("report_markdown_key") or None,
        "report_html_path": artifacts.get("report_html_key") or None,
        "content_bounds": {
            "alert_payload_truncated": alert_truncated,
            "analysis_truncated": analysis_truncated,
            "alert_payload_total_keys": alert_total,
            "analysis_total_keys": analysis_total,
            "raw_sections": ["alert_payload", "analysis"],
        },
    }


def get_case_raw_section(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    blob_service: Any,
    case_id: str,
    section: str,
    offset: int = 0,
    limit: int | None = None,
) -> dict[str, Any] | None:
    """Return a bounded raw envelope section page."""

    metadata = get_case_metadata(config=config, cosmos_store=cosmos_store, case_id=case_id)
    if not metadata:
        return None
    envelope = _load_envelope(
        container_name=config.CASE_ARCHIVE_CONTAINER,
        blob_name=str(metadata.get("case_envelope_key", "")),
        blob_service=blob_service,
    )
    if section not in {"alert_payload", "analysis"}:
        raise ValueError("raw section must be alert_payload or analysis")
    value = envelope.get(section)
    mapping = value if isinstance(value, dict) else {}
    items = list(mapping.items())
    start = max(0, int(offset))
    page_size = min(max(1, int(limit or config.PORTAL_PAGE_SIZE)), config.PORTAL_PAGE_SIZE)
    page = dict(items[start : start + page_size])
    return {
        "case_id": case_id,
        "section": section,
        "offset": start,
        "limit": page_size,
        "has_more": start + page_size < len(items),
        "total_keys": len(items),
        "items": page,
    }


def _case_summary(row: dict[str, Any]) -> dict[str, Any]:
    notices = build_case_archive_notices(
        retrieval_status=str(row.get("retrieval_status", "")),
        source_completeness=str(row.get("source_completeness", "")),
    )
    return {
        "case_id": str(row.get("case_id", "")),
        "processed_at": str(row.get("processed_at", "")),
        "expires_at": str(row.get("expires_at", "")),
        "verdict": row.get("verdict") or None,
        "confidence": _float_or_none(row.get("confidence")),
        "search_name": row.get("search_name") or None,
        "retrieval_status": str(row.get("retrieval_status", "unknown")),
        "source_completeness": str(row.get("source_completeness", "complete")),
        "archive_notices": notices or None,
    }


def _load_envelope(container_name: str, blob_name: str, blob_service: Any) -> dict[str, Any]:
    if not blob_name:
        raise ValueError("case_envelope_key is missing from case-index document")
    body = read_blob(container_name, blob_name, store=blob_service)
    parsed = json.loads(body.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("case envelope must be a JSON object")
    return parsed


def _bounded_mapping(value: dict[str, Any], max_bytes: int) -> tuple[dict[str, Any], bool, int]:
    bounded: dict[str, Any] = {}
    total = len(value)
    for key, child in value.items():
        candidate = dict(bounded)
        candidate[str(key)] = child
        if len(json.dumps(candidate, ensure_ascii=False, default=str).encode("utf-8")) > max_bytes:
            return bounded, True, total
        bounded[str(key)] = child
    return bounded, False, total


def _cursor_from_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        "processed_at": str(row.get("processed_at", "")),
        "case_id": str(row.get("case_id", "")),
    }


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        decoded = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
    except (binascii.Error, TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("case cursor is invalid") from exc
    processed_at = str(decoded.get("processed_at", "")).strip()
    case_id = str(decoded.get("case_id", "")).strip()
    if not processed_at or not case_id:
        raise ValueError("case cursor is invalid")
    return processed_at, case_id


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bounded_filter(value: str | None, *, field_name: str, max_chars: int) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if len(normalized) > max_chars:
        raise ValueError(f"{field_name} exceeds {max_chars} characters")
    return normalized


def _normalized_timestamp(
    value: str | None,
    *,
    field_name: str,
    end: bool,
) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized):
            parsed_date = date.fromisoformat(normalized)
            parsed = datetime.combine(
                parsed_date,
                time.max if end else time.min,
                tzinfo=timezone.utc,
            )
        else:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError
            parsed = parsed.astimezone(timezone.utc)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 date or timestamp") from exc
    return parsed.isoformat().replace("+00:00", "Z")
