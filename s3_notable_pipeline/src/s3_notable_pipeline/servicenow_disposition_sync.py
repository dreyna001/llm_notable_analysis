"""ServiceNow closed disposition sync for AWS (read-only Table API -> DynamoDB)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from .config import Config
from .runtime_security import validate_https_url
from .verdicts import ALLOWED_VERDICTS, normalize_verdict

logger = logging.getLogger(__name__)

JOB_NAME = "servicenow_closed"
MAX_RECORDS_PER_RUN = 500
PAGE_SIZE = 100
MALFORMED_PAGE_FAIL_RATIO = 0.10
SOURCE_PAYLOAD_MAX_BYTES = 32_768
CLOSE_NOTES_MAX_CHARS = 4000
CASE_LINK_SCAN_LIMIT = 200
CORRELATION_INDEX_NAME = "CorrelationIdIndex"
DDB_SPARSE_GSI_STRING_KEYS = frozenset({"correlation_id", "case_id"})
_ALERT_CORRELATION_FIELDS = ("notable_id", "event_id", "sid")
_TABLE_NAME_PATTERN = re.compile(r"^[a-z0-9_]+$")
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_RETRY_DELAYS_SECONDS = (1.0, 2.0, 4.0)

_REQUIRED_FIELD_KEYS = (
    "sys_id",
    "number",
    "state",
    "closed_at",
    "sys_updated_on",
    "close_code",
    "close_notes",
    "correlation_id",
)


class DispositionSyncAuthError(Exception):
    """ServiceNow returned 401/403 for disposition sync."""


class DispositionSyncConfigError(Exception):
    """Disposition sync configuration or map validation failed."""


@dataclass(frozen=True)
class DispositionSyncSummary:
    """Structured result for one sync run."""

    status: str
    fetched: int = 0
    upserted: int = 0
    skipped: int = 0
    linked: int = 0
    deactivated: int = 0
    malformed: int = 0
    errors: int = 0
    message: str = ""
    cursor_advanced: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "fetched": self.fetched,
            "upserted": self.upserted,
            "skipped": self.skipped,
            "linked": self.linked,
            "deactivated": self.deactivated,
            "malformed": self.malformed,
            "errors": self.errors,
            "message": self.message,
            "cursor_advanced": self.cursor_advanced,
        }


def run_disposition_sync(
    *,
    config: Config,
    dynamodb_client: Any,
    s3_client: Any | None = None,
    http_session: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Pull closed ServiceNow incidents and upsert disposition rows in DynamoDB."""

    if not config.SERVICENOW_DISPOSITION_SYNC_ENABLED:
        summary = DispositionSyncSummary(status="skipped", message="disposition sync disabled")
        logger.info("ServiceNow disposition sync skipped: disabled")
        return summary.as_dict()

    run_at = _coerce_utc(now)
    try:
        field_map = load_field_map(config.SERVICENOW_DISPOSITION_FIELD_MAP)
        code_map = load_code_map(config.SERVICENOW_DISPOSITION_CODE_MAP)
        base_url = validate_https_url(
            config.SERVICENOW_BASE_URL,
            setting_name="SERVICENOW_BASE_URL",
            allow_private=config.ALLOW_PRIVATE_OUTBOUND_ENDPOINTS,
        )
        token = _resolve_sync_token(config)
        if not token:
            raise DispositionSyncConfigError(
                "SERVICENOW_DISPOSITION_SYNC_TOKEN is required when disposition sync is enabled"
            )
        _validate_table_names(config)
    except (DispositionSyncConfigError, ValueError) as exc:
        summary = DispositionSyncSummary(status="error", message=str(exc), errors=1)
        logger.error("ServiceNow disposition sync config error: %s", exc)
        return summary.as_dict()

    session = http_session or requests.Session()
    cursor = _read_cursor(dynamodb_client, config.DISPOSITION_SYNC_STATE_TABLE)
    closed_states = field_map["closed_state_values"]
    table_name = field_map["table"]
    api_fields = _api_field_list(field_map)

    fetched = 0
    upserted = 0
    skipped = 0
    linked = 0
    deactivated = 0
    malformed = 0
    errors = 0
    max_sys_updated_on: datetime | None = None

    try:
        for page_rows in _iter_table_api_pages(
            base_url=base_url,
            table_name=table_name,
            api_fields=api_fields,
            closed_states=closed_states,
            field_map=field_map,
            cursor=cursor,
            backfill_days=config.SERVICENOW_DISPOSITION_BACKFILL_DAYS,
            run_at=run_at,
            token=token,
            session=session,
            timeout_seconds=config.SERVICENOW_TIMEOUT_SECONDS,
        ):
            page_malformed = 0
            page_total = len(page_rows)
            fetched += page_total

            for raw_row in page_rows:
                outcome = _process_row(
                    raw_row=raw_row,
                    field_map=field_map,
                    code_map=code_map,
                    closed_states=closed_states,
                    config=config,
                    dynamodb_client=dynamodb_client,
                    s3_client=s3_client,
                    run_at=run_at,
                )

                if outcome["action"] == "malformed":
                    malformed += 1
                    page_malformed += 1
                    continue
                if outcome["action"] == "skipped":
                    skipped += 1
                if outcome["action"] == "upserted":
                    upserted += 1
                if outcome["action"] == "deactivated":
                    deactivated += 1
                if outcome.get("linked"):
                    linked += 1

                row_updated = outcome.get("sys_updated_on")
                if isinstance(row_updated, datetime):
                    if max_sys_updated_on is None or row_updated > max_sys_updated_on:
                        max_sys_updated_on = row_updated

            if page_total and (page_malformed / page_total) > MALFORMED_PAGE_FAIL_RATIO:
                raise RuntimeError(
                    f"malformed row ratio exceeded threshold on page ({page_malformed}/{page_total})"
                )

            if fetched >= MAX_RECORDS_PER_RUN:
                break

        if max_sys_updated_on is not None:
            _write_cursor(
                dynamodb_client,
                config.DISPOSITION_SYNC_STATE_TABLE,
                cursor_value=max_sys_updated_on,
                updated_at=run_at,
            )
            summary = DispositionSyncSummary(
                status="success",
                fetched=fetched,
                upserted=upserted,
                skipped=skipped,
                linked=linked,
                deactivated=deactivated,
                malformed=malformed,
                errors=errors,
                cursor_advanced=True,
            )
        else:
            summary = DispositionSyncSummary(
                status="success",
                fetched=fetched,
                upserted=upserted,
                skipped=skipped,
                linked=linked,
                deactivated=deactivated,
                malformed=malformed,
                errors=errors,
                message="no rows processed; cursor unchanged",
            )
    except DispositionSyncAuthError as exc:
        summary = DispositionSyncSummary(
            status="error",
            fetched=fetched,
            upserted=upserted,
            skipped=skipped,
            linked=linked,
            deactivated=deactivated,
            malformed=malformed,
            errors=errors + 1,
            message=str(exc),
        )
    except Exception as exc:
        summary = DispositionSyncSummary(
            status="error",
            fetched=fetched,
            upserted=upserted,
            skipped=skipped,
            linked=linked,
            deactivated=deactivated,
            malformed=malformed,
            errors=errors + 1,
            message=str(exc),
        )

    logger.info("ServiceNow disposition sync finished: %s", summary.as_dict())
    return summary.as_dict()


def load_field_map(path: str) -> dict[str, Any]:
    """Load and validate the ServiceNow disposition field map JSON."""

    payload = _load_json_file(path, setting_name="SERVICENOW_DISPOSITION_FIELD_MAP")
    table = str(payload.get("table", "")).strip()
    if not _TABLE_NAME_PATTERN.fullmatch(table):
        raise DispositionSyncConfigError("field map table must match [a-z0-9_]+")
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        raise DispositionSyncConfigError("field map fields must be an object")
    for key in _REQUIRED_FIELD_KEYS:
        value = fields.get(key)
        if not isinstance(value, str) or not value.strip():
            raise DispositionSyncConfigError(f"field map fields.{key} is required")
    closed_state_values = payload.get("closed_state_values")
    if not isinstance(closed_state_values, list) or not closed_state_values:
        raise DispositionSyncConfigError("field map closed_state_values must be a non-empty array")
    normalized_states = [str(item).strip() for item in closed_state_values if str(item).strip()]
    if not normalized_states:
        raise DispositionSyncConfigError("field map closed_state_values must contain values")
    return {
        "table": table,
        "fields": {key: str(fields[key]).strip() for key in fields if str(fields[key]).strip()},
        "closed_state_values": normalized_states,
    }


def load_code_map(path: str) -> dict[str, list[str]]:
    """Load and validate the ServiceNow disposition code map JSON."""

    payload = _load_json_file(path, setting_name="SERVICENOW_DISPOSITION_CODE_MAP")
    if not isinstance(payload, dict):
        raise DispositionSyncConfigError("code map must be a JSON object")
    normalized: dict[str, list[str]] = {}
    for bucket in ALLOWED_VERDICTS:
        values = payload.get(bucket, [])
        if values is None:
            values = []
        if not isinstance(values, list):
            raise DispositionSyncConfigError(f"code map {bucket} must be an array")
        normalized[bucket] = [str(item).strip() for item in values if str(item).strip()]
    return normalized


def normalize_disposition(raw_value: Any, code_map: dict[str, list[str]]) -> tuple[str, str]:
    """Map raw close code text to normalized disposition and preserve raw text."""

    raw_text = str(raw_value or "").strip()
    if not raw_text:
        return normalize_verdict(None), ""
    lowered = raw_text.casefold()
    for bucket, entries in code_map.items():
        for entry in entries:
            if entry.casefold() == lowered:
                return bucket, raw_text
    return normalize_verdict(raw_text), raw_text


def payload_hash(mapped_fields: dict[str, Any]) -> str:
    """Return SHA-256 of canonical mapped-field JSON."""

    canonical = json.dumps(mapped_fields, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _process_row(
    *,
    raw_row: dict[str, Any],
    field_map: dict[str, Any],
    code_map: dict[str, list[str]],
    closed_states: list[str],
    config: Config,
    dynamodb_client: Any,
    s3_client: Any | None,
    run_at: datetime,
) -> dict[str, Any]:
    mapped = _map_row_fields(raw_row, field_map)
    snow_sys_id = mapped.get("sys_id", "")
    if not snow_sys_id:
        return {"action": "malformed"}

    state = str(mapped.get("state", "")).strip()
    sys_updated_on = _parse_servicenow_datetime(mapped.get("sys_updated_on"))
    if sys_updated_on is None:
        return {"action": "malformed"}

    is_closed = _state_is_closed(state, closed_states)
    existing = _get_disposition_item(
        dynamodb_client,
        config.DISPOSITION_TABLE,
        snow_sys_id,
    )

    if not is_closed:
        if not existing:
            return {"action": "skipped", "sys_updated_on": sys_updated_on}
        if existing.get("is_active") is False:
            return {"action": "skipped", "sys_updated_on": sys_updated_on}
        _upsert_disposition_item(
            dynamodb_client=dynamodb_client,
            table_name=config.DISPOSITION_TABLE,
            item=_merge_deactivated_item(existing, sys_updated_on=sys_updated_on, run_at=run_at),
        )
        return {"action": "deactivated", "sys_updated_on": sys_updated_on}

    mapped_for_hash = {key: mapped.get(key) for key in sorted(mapped)}
    row_hash = payload_hash(mapped_for_hash)
    if existing and str(existing.get("payload_hash", "")) == row_hash:
        return {"action": "skipped", "sys_updated_on": sys_updated_on}

    disposition_normalized, disposition_raw = normalize_disposition(
        mapped.get("close_code"),
        code_map,
    )
    correlation_id = str(mapped.get("correlation_id", "")).strip()
    case_id = str(existing.get("case_id", "")).strip() if existing else ""
    if not case_id and correlation_id and config.CASE_INDEX_TABLE:
        case_id = _link_case_id(
            config=config,
            dynamodb_client=dynamodb_client,
            s3_client=s3_client,
            correlation_id=correlation_id,
        )

    expires_at = run_at + timedelta(days=config.DISPOSITION_RETENTION_DAYS)
    item = {
        "snow_sys_id": snow_sys_id,
        "snow_number": str(mapped.get("number", "")).strip() or snow_sys_id,
        "snow_table": field_map["table"],
        "state": state,
        "is_active": True,
        "closed_at": _format_servicenow_timestamp(_parse_servicenow_datetime(mapped.get("closed_at"))),
        "sys_updated_on": _format_servicenow_timestamp(sys_updated_on),
        "disposition_normalized": disposition_normalized,
        "disposition_raw": disposition_raw,
        "close_notes": _truncate(str(mapped.get("close_notes", "")), CLOSE_NOTES_MAX_CHARS),
        "short_description": str(mapped.get("short_description", "")).strip(),
        "search_name": str(mapped.get("search_name", "")).strip(),
        "correlation_id": correlation_id,
        "correlation_display": str(mapped.get("correlation_display", "")).strip(),
        "source_payload": _bounded_source_payload(mapped),
        "payload_hash": row_hash,
        "case_id": case_id,
        "synced_at": _format_servicenow_timestamp(run_at),
        "expires_at": _format_servicenow_timestamp(expires_at),
        "expires_at_epoch": int(expires_at.timestamp()),
    }
    _upsert_disposition_item(
        dynamodb_client=dynamodb_client,
        table_name=config.DISPOSITION_TABLE,
        item=item,
    )
    return {
        "action": "upserted",
        "sys_updated_on": sys_updated_on,
        "linked": bool(case_id),
    }


def _link_case_id(
    *,
    config: Config,
    dynamodb_client: Any,
    s3_client: Any | None,
    correlation_id: str,
) -> str:
    candidates = _find_case_candidates(
        dynamodb_client=dynamodb_client,
        table_name=config.CASE_INDEX_TABLE,
        correlation_id=correlation_id,
    )
    if not candidates and s3_client is not None:
        candidates = _scan_cases_for_payload_correlation(
            config=config,
            dynamodb_client=dynamodb_client,
            s3_client=s3_client,
            correlation_id=correlation_id,
        )
    if not candidates:
        return ""
    best = _select_latest_case(candidates)
    return str(best.get("case_id", "")).strip()


def _find_case_candidates(
    *,
    dynamodb_client: Any,
    table_name: str,
    correlation_id: str,
) -> list[dict[str, Any]]:
    try:
        response = dynamodb_client.query(
            TableName=table_name,
            IndexName=CORRELATION_INDEX_NAME,
            KeyConditionExpression="correlation_id = :cid",
            ExpressionAttributeValues={":cid": {"S": correlation_id}},
            ScanIndexForward=False,
            Limit=CASE_LINK_SCAN_LIMIT,
        )
        return [_from_ddb_item(item) for item in response.get("Items", [])]
    except Exception as exc:
        if not _is_missing_index_error(exc):
            raise
    return _scan_cases_by_correlation_id(
        dynamodb_client=dynamodb_client,
        table_name=table_name,
        correlation_id=correlation_id,
    )


def _scan_cases_by_correlation_id(
    *,
    dynamodb_client: Any,
    table_name: str,
    correlation_id: str,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    request: dict[str, Any] = {
        "TableName": table_name,
        "FilterExpression": "correlation_id = :cid",
        "ExpressionAttributeValues": {":cid": {"S": correlation_id}},
        "Limit": CASE_LINK_SCAN_LIMIT,
    }
    while True:
        response = dynamodb_client.scan(**request)
        matches.extend(_from_ddb_item(item) for item in response.get("Items", []))
        if len(matches) >= CASE_LINK_SCAN_LIMIT:
            break
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        request["ExclusiveStartKey"] = last_key
    return matches[:CASE_LINK_SCAN_LIMIT]


def _scan_cases_for_payload_correlation(
    *,
    config: Config,
    dynamodb_client: Any,
    s3_client: Any,
    correlation_id: str,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    scanned = 0
    request: dict[str, Any] = {
        "TableName": config.CASE_INDEX_TABLE,
        "ProjectionExpression": "case_id, processed_at, processed_at_case_id, correlation_id, finding_id, case_envelope_key",
        "Limit": 100,
    }
    while scanned < CASE_LINK_SCAN_LIMIT:
        response = dynamodb_client.scan(**request)
        for item in response.get("Items", []):
            scanned += 1
            row = _from_ddb_item(item)
            if str(row.get("finding_id", "")).strip() == correlation_id:
                matches.append(row)
                continue
            if str(row.get("correlation_id", "")).strip() == correlation_id:
                matches.append(row)
                continue
            envelope_key = str(row.get("case_envelope_key", "")).strip()
            if not envelope_key:
                continue
            alert_payload = _load_alert_payload(
                bucket=config.CASE_ARCHIVE_BUCKET,
                key=envelope_key,
                s3_client=s3_client,
            )
            if _alert_payload_matches(alert_payload, correlation_id):
                matches.append(row)
        if scanned >= CASE_LINK_SCAN_LIMIT:
            break
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        request["ExclusiveStartKey"] = last_key
    return matches


def _load_alert_payload(*, bucket: str, key: str, s3_client: Any) -> dict[str, Any]:
    if not bucket or not key:
        return {}
    response = s3_client.get_object(Bucket=bucket, Key=key)
    body = response["Body"].read()
    parsed = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
    if not isinstance(parsed, dict):
        return {}
    alert_payload = parsed.get("alert_payload")
    return alert_payload if isinstance(alert_payload, dict) else {}


def _alert_payload_matches(alert_payload: dict[str, Any], correlation_id: str) -> bool:
    for field in _ALERT_CORRELATION_FIELDS:
        value = alert_payload.get(field)
        if value is not None and str(value).strip() == correlation_id:
            return True
    return False


def _select_latest_case(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def sort_key(row: dict[str, Any]) -> tuple[str, str]:
        return (
            str(row.get("processed_at", "")),
            str(row.get("case_id", "")),
        )

    return max(rows, key=sort_key)


def _iter_table_api_pages(
    *,
    base_url: str,
    table_name: str,
    api_fields: list[str],
    closed_states: list[str],
    field_map: dict[str, Any],
    cursor: datetime | None,
    backfill_days: int,
    run_at: datetime,
    token: str,
    session: Any,
    timeout_seconds: int,
):
    offset = 0
    fetched_total = 0
    closed_field = field_map["fields"]["closed_at"]
    updated_field = field_map["fields"]["sys_updated_on"]

    state_field = field_map["fields"]["state"]

    while fetched_total < MAX_RECORDS_PER_RUN:
        if cursor is None:
            backfill_start = run_at - timedelta(days=backfill_days)
            query = (
                f"{closed_field}>{_servicenow_query_timestamp(backfill_start)}"
                f"^{state_field}IN{_comma_join(closed_states)}"
            )
        else:
            query = f"{updated_field}>{_servicenow_query_timestamp(cursor)}"

        url = f"{base_url.rstrip('/')}/api/now/table/{table_name}"
        params = {
            "sysparm_query": query,
            "sysparm_fields": ",".join(api_fields),
            "sysparm_display_value": "false",
            "sysparm_exclude_reference_link": "true",
            "sysparm_limit": str(PAGE_SIZE),
            "sysparm_offset": str(offset),
            "sysparm_order_by": updated_field,
        }
        response = _request_with_retry(
            session=session,
            method="GET",
            url=url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            params=params,
            timeout=timeout_seconds,
        )
        body = response.json() if response.content else {}
        rows = body.get("result", []) if isinstance(body, dict) else []
        if not isinstance(rows, list):
            rows = []
        if not rows:
            break
        yield rows
        fetched_total += len(rows)
        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE


def _request_with_retry(
    *,
    session: Any,
    method: str,
    url: str,
    timeout: int,
    **kwargs: Any,
) -> Any:
    last_response = None
    attempts = len(_RETRY_DELAYS_SECONDS) + 1
    for attempt in range(attempts):
        if attempt:
            time.sleep(_RETRY_DELAYS_SECONDS[attempt - 1])
        response = session.request(method, url, timeout=timeout, **kwargs)
        last_response = response
        if response.status_code in {401, 403}:
            raise DispositionSyncAuthError(
                f"ServiceNow disposition sync auth failed with HTTP {response.status_code}"
            )
        if response.status_code not in _RETRYABLE_STATUS_CODES:
            response.raise_for_status()
            return response
    if last_response is not None:
        last_response.raise_for_status()
    raise RuntimeError("ServiceNow disposition sync request failed without response")


def _map_row_fields(raw_row: dict[str, Any], field_map: dict[str, Any]) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    for logical_name, sn_field in field_map["fields"].items():
        mapped[logical_name] = raw_row.get(sn_field)
    if not mapped.get("sys_id"):
        mapped["sys_id"] = raw_row.get("sys_id")
    return mapped


def _api_field_list(field_map: dict[str, Any]) -> list[str]:
    columns = {str(value).strip() for value in field_map["fields"].values() if str(value).strip()}
    columns.add("sys_id")
    return sorted(columns)


def _read_cursor(dynamodb_client: Any, table_name: str) -> datetime | None:
    response = dynamodb_client.get_item(
        TableName=table_name,
        Key={"job_name": {"S": JOB_NAME}},
        ConsistentRead=True,
    )
    item = response.get("Item")
    if not item:
        return None
    row = _from_ddb_item(item)
    cursor_text = str(row.get("cursor_value", "")).strip()
    if not cursor_text:
        return None
    return _parse_servicenow_datetime(cursor_text)


def _write_cursor(
    dynamodb_client: Any,
    table_name: str,
    *,
    cursor_value: datetime,
    updated_at: datetime,
) -> None:
    dynamodb_client.put_item(
        TableName=table_name,
        Item=_to_ddb_item(
            {
                "job_name": JOB_NAME,
                "cursor_value": _format_servicenow_timestamp(cursor_value),
                "updated_at": _format_servicenow_timestamp(updated_at),
            }
        ),
    )


def _get_disposition_item(
    dynamodb_client: Any,
    table_name: str,
    snow_sys_id: str,
) -> dict[str, Any] | None:
    response = dynamodb_client.get_item(
        TableName=table_name,
        Key={"snow_sys_id": {"S": snow_sys_id}},
        ConsistentRead=True,
    )
    item = response.get("Item")
    if not item:
        return None
    return _from_ddb_item(item)


def _upsert_disposition_item(
    *,
    dynamodb_client: Any,
    table_name: str,
    item: dict[str, Any],
) -> None:
    dynamodb_client.put_item(
        TableName=table_name,
        Item=_to_ddb_item(_prepare_ddb_attributes(item)),
    )


def _prepare_ddb_attributes(item: dict[str, Any]) -> dict[str, Any]:
    """Omit empty optional GSI key attributes before DynamoDB PutItem."""
    prepared = dict(item)
    for key in DDB_SPARSE_GSI_STRING_KEYS:
        if key in prepared and not str(prepared[key] or "").strip():
            prepared.pop(key, None)
    return prepared


def _merge_deactivated_item(
    existing: dict[str, Any],
    *,
    sys_updated_on: datetime,
    run_at: datetime,
) -> dict[str, Any]:
    merged = dict(existing)
    merged["is_active"] = False
    merged["sys_updated_on"] = _format_servicenow_timestamp(sys_updated_on)
    merged["synced_at"] = _format_servicenow_timestamp(run_at)
    return merged


def _bounded_source_payload(mapped: dict[str, Any]) -> dict[str, Any]:
    payload = {key: mapped.get(key) for key in sorted(mapped)}
    encoded = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    if len(encoded) <= SOURCE_PAYLOAD_MAX_BYTES:
        return payload
    trimmed = dict(payload)
    for key in list(trimmed):
        trimmed[key] = _truncate(str(trimmed[key]), 512)
        encoded = json.dumps(trimmed, ensure_ascii=False, default=str).encode("utf-8")
        if len(encoded) <= SOURCE_PAYLOAD_MAX_BYTES:
            return trimmed
    return {"truncated": True, "payload_hash_hint": payload_hash(payload)}


def _resolve_sync_token(config: Config) -> str:
    direct = str(config.SERVICENOW_DISPOSITION_SYNC_TOKEN or "").strip()
    if direct:
        return direct
    secret_arn = str(config.SERVICENOW_DISPOSITION_SYNC_TOKEN_SECRET_ARN or "").strip()
    if not secret_arn or secret_arn == "*":
        return ""
    from .runtime_security import resolve_secret_string

    return resolve_secret_string(
        secret_arn=secret_arn,
        setting_name="SERVICENOW_DISPOSITION_SYNC_TOKEN",
        secret_field="token",
        fallback_fields=("SERVICENOW_DISPOSITION_SYNC_TOKEN",),
    )


def _validate_table_names(config: Config) -> None:
    if not config.DISPOSITION_TABLE.strip():
        raise DispositionSyncConfigError("DISPOSITION_TABLE is required when disposition sync is enabled")
    if not config.DISPOSITION_SYNC_STATE_TABLE.strip():
        raise DispositionSyncConfigError(
            "DISPOSITION_SYNC_STATE_TABLE is required when disposition sync is enabled"
        )


def _load_json_file(path: str, *, setting_name: str) -> Any:
    clean_path = str(path or "").strip()
    if not clean_path:
        raise DispositionSyncConfigError(f"{setting_name} path is required")
    file_path = Path(clean_path)
    if not file_path.is_file():
        raise DispositionSyncConfigError(f"{setting_name} file not found: {clean_path}")
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DispositionSyncConfigError(f"{setting_name} is not valid JSON") from exc


def _state_is_closed(state: str, closed_states: list[str]) -> bool:
    normalized_state = state.casefold()
    closed = {value.casefold() for value in closed_states}
    return normalized_state in closed


def _comma_join(values: list[str]) -> str:
    return ",".join(values)


def _servicenow_query_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _format_servicenow_timestamp(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_servicenow_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    if " " in normalized and "T" not in normalized:
        normalized = normalized.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _truncate(value: str, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _coerce_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_missing_index_error(exc: Exception) -> bool:
    response = getattr(exc, "response", {})
    if isinstance(response, dict):
        error = response.get("Error", {})
        if isinstance(error, dict) and error.get("Code") == "ValidationException":
            return True
    return exc.__class__.__name__ == "ValidationException"


def _to_ddb_item(item: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {key: _to_ddb_value(value) for key, value in item.items()}


def _to_ddb_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, int | float) and not isinstance(value, bool):
        return {"N": str(value)}
    if isinstance(value, dict):
        return {"M": {str(key): _to_ddb_value(child) for key, child in value.items()}}
    if isinstance(value, list):
        return {"L": [_to_ddb_value(child) for child in value]}
    if value is None:
        return {"NULL": True}
    return {"S": str(value)}


def _from_ddb_item(item: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {key: _from_ddb_value(value) for key, value in item.items()}


def _from_ddb_value(value: dict[str, Any]) -> Any:
    if "S" in value:
        return value["S"]
    if "N" in value:
        number = value["N"]
        return int(number) if str(number).isdigit() else float(number)
    if "BOOL" in value:
        return bool(value["BOOL"])
    if "NULL" in value:
        return None
    if "M" in value:
        return {key: _from_ddb_value(child) for key, child in value["M"].items()}
    if "L" in value:
        return [_from_ddb_value(child) for child in value["L"]]
    return value
