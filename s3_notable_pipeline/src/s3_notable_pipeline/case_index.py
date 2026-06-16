"""Read-only CaseIndex and case envelope helpers for the AWS portal."""

from __future__ import annotations

import base64
import json
from typing import Any

from .case_archive_notices import build_case_archive_notices
from .config import Config


def list_cases(
    *,
    config: Config,
    dynamodb_client: Any,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List cases from the ProcessedAtIndex with bounded page size."""

    page_size = min(max(1, int(limit or config.PORTAL_PAGE_SIZE)), config.PORTAL_PAGE_SIZE)
    request: dict[str, Any] = {
        "TableName": config.CASE_INDEX_TABLE,
        "IndexName": "ProcessedAtIndex",
        "KeyConditionExpression": "archive_partition = :partition",
        "ExpressionAttributeValues": {":partition": {"S": "default"}},
        "ScanIndexForward": False,
        "Limit": page_size + 1,
    }
    if cursor:
        request["ExclusiveStartKey"] = _decode_cursor(cursor)
    response = dynamodb_client.query(**request)
    rows = [_from_ddb_item(item) for item in response.get("Items", [])]
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
    decoded = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
    processed_at = str(decoded.get("processed_at", ""))
    case_id = str(decoded.get("case_id", ""))
    return {
        "archive_partition": {"S": "default"},
        "processed_at_case_id": {"S": f"{processed_at}#{case_id}"},
        "case_id": {"S": case_id},
    }


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
