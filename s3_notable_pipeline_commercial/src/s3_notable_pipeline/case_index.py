"""Read-only CaseIndex and case envelope helpers for the AWS portal."""

from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import date, datetime, timedelta
from typing import Any

from .case_archive_notices import build_case_archive_notices
from .config import Config

_CASE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def list_cases(
    *,
    config: Config,
    dynamodb_client: Any,
    limit: int | None = None,
    cursor: str | dict[str, str] | None = None,
    cursor_processed_at: str | None = None,
    cursor_case_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    verdict: str | None = None,
    search_name: str | None = None,
) -> dict[str, Any]:
    """List cases with bounded, filtered two-part cursor pagination."""

    page_size = min(max(1, int(limit or config.PORTAL_PAGE_SIZE)), config.PORTAL_PAGE_SIZE)
    exclusive_start_key = _cursor_key(
        cursor=cursor,
        cursor_processed_at=cursor_processed_at,
        cursor_case_id=cursor_case_id,
    )
    bounds = _normalize_filters(
        start=start,
        end=end,
        start_date=start_date,
        end_date=end_date,
        verdict=verdict,
        search_name=search_name,
    )
    request: dict[str, Any] = {
        "TableName": config.CASE_INDEX_TABLE,
        "IndexName": "ProcessedAtIndex",
        "KeyConditionExpression": "archive_partition = :partition",
        "ExpressionAttributeValues": {":partition": {"S": "default"}},
        "ScanIndexForward": False,
        "Limit": page_size + 1,
    }
    _add_filter_expression(request, bounds)
    if exclusive_start_key:
        request["ExclusiveStartKey"] = exclusive_start_key

    rows: list[dict[str, Any]] = []
    last_evaluated_key: dict[str, dict[str, Any]] | None = None
    previous_key: dict[str, dict[str, Any]] | None = None
    while len(rows) <= page_size:
        response = dynamodb_client.query(**request)
        for item in response.get("Items", []):
            row = _from_ddb_item(item)
            if _matches_filters(row, bounds):
                rows.append(row)
        last_evaluated_key = response.get("LastEvaluatedKey")
        if len(rows) > page_size or not last_evaluated_key:
            break
        validated_key = _validate_ddb_cursor_key(last_evaluated_key)
        if validated_key == previous_key:
            break
        previous_key = validated_key
        request["ExclusiveStartKey"] = validated_key
    has_more = len(rows) > page_size or bool(last_evaluated_key)
    rows = rows[:page_size]
    next_cursor = None
    if has_more and rows:
        if len(rows) == page_size and last_evaluated_key:
            next_cursor = _cursor_from_ddb_key(last_evaluated_key)
        else:
            next_cursor = _cursor_from_row(rows[-1])
    return {
        "items": [_case_summary(row) for row in rows],
        "limit": page_size,
        "has_more": has_more,
        "next_cursor": next_cursor,
    }


def _cursor_key(
    *,
    cursor: str | dict[str, str] | None,
    cursor_processed_at: str | None,
    cursor_case_id: str | None,
) -> dict[str, dict[str, Any]] | None:
    if cursor is not None and (cursor_processed_at is not None or cursor_case_id is not None):
        raise ValueError("cursor must use either cursor or cursor_processed_at/cursor_case_id")
    if cursor is not None:
        if isinstance(cursor, dict):
            processed_at = cursor.get("processed_at")
            case_id = cursor.get("case_id")
            if not isinstance(processed_at, str) or not isinstance(case_id, str):
                raise ValueError("cursor must contain processed_at and case_id")
            return _cursor_key_from_parts(processed_at, case_id)
        return _decode_cursor(cursor)
    if (cursor_processed_at is None) != (cursor_case_id is None):
        raise ValueError("cursor_processed_at and cursor_case_id must be provided together")
    if cursor_processed_at is None:
        return None
    return _cursor_key_from_parts(cursor_processed_at, cursor_case_id or "")


def _cursor_key_from_parts(processed_at: str, case_id: str) -> dict[str, dict[str, Any]]:
    normalized_processed_at = _validate_timestamp(processed_at, "cursor_processed_at")
    normalized_case_id = _validate_case_id(case_id, "cursor_case_id")
    return {
        "archive_partition": {"S": "default"},
        "processed_at_case_id": {"S": f"{normalized_processed_at}#{normalized_case_id}"},
        "case_id": {"S": normalized_case_id},
    }


def _normalize_filters(
    *,
    start: str | None,
    end: str | None,
    start_date: str | None,
    end_date: str | None,
    verdict: str | None,
    search_name: str | None,
) -> dict[str, str | None]:
    normalized_start_date = _normalize_date(start_date, "start_date")
    normalized_end_date = _normalize_date(end_date, "end_date")
    normalized_start = _normalize_bound(start, "start")
    normalized_end = _normalize_bound(end, "end")
    if normalized_start and normalized_start_date:
        raise ValueError("start and start_date cannot both be provided")
    if normalized_end and normalized_end_date:
        raise ValueError("end and end_date cannot both be provided")
    if normalized_start and normalized_end and normalized_start > normalized_end:
        raise ValueError("start must not be after end")
    if normalized_start_date and normalized_end_date and normalized_start_date > normalized_end_date:
        raise ValueError("start_date must not be after end_date")
    normalized_verdict = _bounded_filter(verdict, "verdict")
    normalized_search_name = _bounded_filter(search_name, "search_name")
    return {
        "start": normalized_start,
        "end": normalized_end,
        "start_date": normalized_start_date,
        "end_date": normalized_end_date,
        "verdict": normalized_verdict,
        "search_name": normalized_search_name,
    }


def _add_filter_expression(request: dict[str, Any], bounds: dict[str, str | None]) -> None:
    clauses: list[str] = []
    values: dict[str, dict[str, str]] = {}
    start = bounds["start"] or (
        f"{bounds['start_date']}T00:00:00Z" if bounds["start_date"] else None
    )
    end = bounds["end"]
    if bounds["end_date"]:
        end_date = date.fromisoformat(str(bounds["end_date"])) + timedelta(days=1)
        end = f"{end_date.isoformat()}T00:00:00Z"
    if start:
        clauses.append("processed_at >= :start_processed_at")
        values[":start_processed_at"] = {"S": start}
    if end:
        operator = "<" if bounds["end_date"] else "<="
        clauses.append(f"processed_at {operator} :end_processed_at")
        values[":end_processed_at"] = {"S": end}
    if bounds["verdict"]:
        clauses.append("verdict = :verdict")
        values[":verdict"] = {"S": str(bounds["verdict"])}
    if bounds["search_name"]:
        clauses.append("contains(search_name, :search_name)")
        values[":search_name"] = {"S": str(bounds["search_name"])}
    if clauses:
        request["FilterExpression"] = " AND ".join(clauses)
        request["ExpressionAttributeValues"].update(values)


def _matches_filters(row: dict[str, Any], bounds: dict[str, str | None]) -> bool:
    processed_at = str(row.get("processed_at", ""))
    start = bounds["start"] or (
        f"{bounds['start_date']}T00:00:00Z" if bounds["start_date"] else None
    )
    if start and processed_at < start:
        return False
    end = bounds["end"]
    if bounds["end_date"]:
        end_date = date.fromisoformat(str(bounds["end_date"])) + timedelta(days=1)
        end = f"{end_date.isoformat()}T00:00:00Z"
    if end:
        if bounds["end_date"] and processed_at >= end:
            return False
        if not bounds["end_date"] and processed_at > end:
            return False
    if bounds["verdict"] and str(row.get("verdict", "")) != bounds["verdict"]:
        return False
    if bounds["search_name"] and str(bounds["search_name"]).lower() not in str(
        row.get("search_name", "")
    ).lower():
        return False
    return True


def _bounded_filter(value: str | None, name: str) -> str | None:
    if value is None or not str(value).strip():
        return None
    normalized = str(value).strip()
    if len(normalized) > 256:
        raise ValueError(f"{name} is too long")
    return normalized


def _normalize_bound(value: str | None, name: str) -> str | None:
    if value is None or not str(value).strip():
        return None
    normalized = str(value).strip()
    if _DATE_RE.fullmatch(normalized):
        return f"{normalized}T00:00:00Z"
    return _validate_timestamp(normalized, name)


def _normalize_date(value: str | None, name: str) -> str | None:
    if value is None or not str(value).strip():
        return None
    normalized = str(value).strip()
    if not _DATE_RE.fullmatch(normalized):
        raise ValueError(f"{name} must be YYYY-MM-DD")
    try:
        date.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid calendar date") from exc
    return normalized


def _validate_timestamp(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized or len(normalized) > 64:
        raise ValueError(f"{name} must be a valid timestamp")
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return normalized


def _validate_case_id(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not _CASE_ID_RE.fullmatch(normalized) or "#" in normalized:
        raise ValueError(f"{name} is invalid")
    return normalized


def get_case_metadata(
    *,
    config: Config,
    dynamodb_client: Any,
    case_id: str,
) -> dict[str, Any] | None:
    """Fetch one CaseIndex row by case id."""

    response = dynamodb_client.get_item(
        TableName=config.CASE_INDEX_TABLE,
        Key={"case_id": {"S": case_id}},
        ConsistentRead=True,
    )
    item = response.get("Item")
    if not item:
        return None
    return _from_ddb_item(item)


def get_case_detail(
    *,
    config: Config,
    dynamodb_client: Any,
    s3_client: Any,
    case_id: str,
) -> dict[str, Any] | None:
    """Assemble bounded case detail from CaseIndex metadata and S3 envelope."""

    metadata = get_case_metadata(
        config=config,
        dynamodb_client=dynamodb_client,
        case_id=case_id,
    )
    if not metadata:
        return None
    envelope = _load_envelope(
        bucket=config.CASE_ARCHIVE_BUCKET,
        key=str(metadata.get("case_envelope_key", "")),
        s3_client=s3_client,
    )
    alert_payload = envelope.get("alert_payload")
    analysis = envelope.get("analysis")
    alert_dict = alert_payload if isinstance(alert_payload, dict) else {}
    analysis_dict = analysis if isinstance(analysis, dict) else None
    bounded_alert, alert_truncated, alert_total = _bounded_mapping(
        alert_dict,
        config.PORTAL_MAX_DETAIL_BYTES,
    )
    bounded_analysis, analysis_truncated, analysis_total = _bounded_mapping(
        analysis_dict or {},
        config.PORTAL_MAX_DETAIL_BYTES,
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
    dynamodb_client: Any,
    s3_client: Any,
    case_id: str,
    section: str,
    offset: int = 0,
    limit: int | None = None,
) -> dict[str, Any] | None:
    """Return a bounded raw envelope section page."""

    metadata = get_case_metadata(
        config=config,
        dynamodb_client=dynamodb_client,
        case_id=case_id,
    )
    if not metadata:
        return None
    envelope = _load_envelope(
        bucket=config.CASE_ARCHIVE_BUCKET,
        key=str(metadata.get("case_envelope_key", "")),
        s3_client=s3_client,
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


def _load_envelope(bucket: str, key: str, s3_client: Any) -> dict[str, Any]:
    if not key:
        raise ValueError("case_envelope_key is missing from CaseIndex row")
    response = s3_client.get_object(Bucket=bucket, Key=key)
    body = response["Body"].read()
    parsed = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
    if not isinstance(parsed, dict):
        raise ValueError("case envelope must be a JSON object")
    return parsed


def _bounded_mapping(value: dict[str, Any], max_bytes: int) -> tuple[dict[str, Any], bool, int]:
    bounded: dict[str, Any] = {}
    total = len(value)
    for key, child in value.items():
        candidate = dict(bounded)
        candidate[str(key)] = child
        encoded = json.dumps(candidate, ensure_ascii=False, default=str).encode("utf-8")
        if len(encoded) > max_bytes:
            return bounded, True, total
        bounded[str(key)] = child
    return bounded, False, total


def _cursor_from_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        "processed_at": str(row.get("processed_at", "")),
        "case_id": str(row.get("case_id", "")),
    }


def _decode_cursor(cursor: str) -> dict[str, dict[str, Any]]:
    try:
        encoded = cursor.encode("ascii")
        padded = encoded + b"=" * (-len(encoded) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (
        UnicodeEncodeError,
        ValueError,
        TypeError,
        binascii.Error,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError("cursor is malformed") from exc
    if not isinstance(decoded, dict) or set(decoded) != {"processed_at", "case_id"}:
        raise ValueError("cursor must contain exactly processed_at and case_id")
    processed_at = decoded.get("processed_at")
    case_id = decoded.get("case_id")
    if not isinstance(processed_at, str) or not isinstance(case_id, str):
        raise ValueError("cursor must contain string processed_at and case_id")
    return _cursor_key_from_parts(processed_at, case_id)


def _validate_ddb_cursor_key(key: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(key, dict):
        raise ValueError("DynamoDB cursor is malformed")
    try:
        partition = key["archive_partition"]["S"]
        sort_key = key["processed_at_case_id"]["S"]
        case_id = key["case_id"]["S"]
    except (KeyError, TypeError):
        raise ValueError("DynamoDB cursor is malformed") from None
    if partition != "default" or "#" not in sort_key:
        raise ValueError("DynamoDB cursor is malformed")
    processed_at, sort_case_id = sort_key.rsplit("#", 1)
    if sort_case_id != case_id:
        raise ValueError("DynamoDB cursor is malformed")
    return _cursor_key_from_parts(processed_at, case_id)


def _cursor_from_ddb_key(key: dict[str, Any]) -> dict[str, str]:
    validated = _validate_ddb_cursor_key(key)
    sort_key = validated["processed_at_case_id"]["S"]
    processed_at, case_id = sort_key.rsplit("#", 1)
    return {"processed_at": processed_at, "case_id": case_id}


def _from_ddb_item(item: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {key: _from_ddb_value(value) for key, value in item.items()}


def _from_ddb_value(value: dict[str, Any]) -> Any:
    if "S" in value:
        return value["S"]
    if "N" in value:
        raw = value["N"]
        return int(raw) if str(raw).isdigit() else float(raw)
    if "BOOL" in value:
        return bool(value["BOOL"])
    if "NULL" in value:
        return None
    if "M" in value:
        return {key: _from_ddb_value(child) for key, child in value["M"].items()}
    if "L" in value:
        return [_from_ddb_value(child) for child in value["L"]]
    return value


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
