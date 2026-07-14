"""ServiceNow closed-disposition sync backed by native Cosmos operations."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

import requests

from .blob_store import read_blob
from .config import Config
from .cosmos_store import CosmosStore
from .runtime_security import resolve_secret_string, validate_https_url
from .verdicts import ALLOWED_VERDICTS, normalize_verdict

logger = logging.getLogger(__name__)
JOB_NAME = "servicenow_closed"
MAX_RECORDS_PER_RUN = 500
PAGE_SIZE = 100
MALFORMED_PAGE_FAIL_RATIO = 0.10
SOURCE_PAYLOAD_MAX_BYTES = 32_768
CLOSE_NOTES_MAX_CHARS = 4000
CASE_LINK_SCAN_LIMIT = 200
_ALERT_CORRELATION_FIELDS = ("notable_id", "event_id", "sid")
_TABLE_NAME_PATTERN = re.compile(r"^[a-z0-9_]+$")
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_RETRY_DELAYS_SECONDS = (1.0, 2.0, 4.0)
_REQUIRED_FIELD_KEYS = (
    "sys_id", "number", "state", "closed_at", "sys_updated_on",
    "close_code", "close_notes", "correlation_id",
)


class DispositionSyncAuthError(Exception):
    """ServiceNow returned 401/403 for disposition sync."""


class DispositionSyncConfigError(Exception):
    """Disposition sync configuration or map validation failed."""


@dataclass(frozen=True, order=True)
class SyncCursor:
    """Stable ServiceNow page boundary ordered by update time then sys_id."""

    updated_at: datetime
    sys_id: str = ""


@dataclass(frozen=True)
class DispositionSyncSummary:
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
        return dict(self.__dict__)


def run_disposition_sync(
    *,
    config: Config,
    cosmos_store: CosmosStore,
    blob_service: Any | None = None,
    http_session: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Pull closed ServiceNow incidents and upsert disposition documents."""

    if not config.SERVICENOW_DISPOSITION_SYNC_ENABLED:
        return DispositionSyncSummary(status="skipped", message="disposition sync disabled").as_dict()
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
        _validate_container_names(config)
    except (DispositionSyncConfigError, ValueError) as exc:
        return DispositionSyncSummary(status="error", message=str(exc), errors=1).as_dict()

    cursor = _read_cursor(cosmos_store, config.DISPOSITION_SYNC_STATE_CONTAINER)
    counts = {key: 0 for key in ("fetched", "upserted", "skipped", "linked", "deactivated", "malformed")}
    max_cursor: SyncCursor | None = None
    try:
        for page_rows in _iter_table_api_pages(
            base_url=base_url,
            table_name=field_map["table"],
            api_fields=_api_field_list(field_map),
            closed_states=field_map["closed_state_values"],
            field_map=field_map,
            cursor=cursor,
            backfill_days=config.SERVICENOW_DISPOSITION_BACKFILL_DAYS,
            run_at=run_at,
            token=token,
            session=http_session or requests.Session(),
            timeout_seconds=config.SERVICENOW_TIMEOUT_SECONDS,
        ):
            counts["fetched"] += len(page_rows)
            page_malformed = 0
            for raw_row in page_rows:
                outcome = _process_row(
                    raw_row=raw_row,
                    field_map=field_map,
                    code_map=code_map,
                    closed_states=field_map["closed_state_values"],
                    config=config,
                    cosmos_store=cosmos_store,
                    blob_service=blob_service,
                    run_at=run_at,
                )
                action = outcome["action"]
                counts[action] = counts.get(action, 0) + 1
                if action == "malformed":
                    page_malformed += 1
                if outcome.get("linked"):
                    counts["linked"] += 1
                updated = outcome.get("sys_updated_on")
                snow_sys_id = str(outcome.get("snow_sys_id") or "").strip()
                if isinstance(updated, datetime) and snow_sys_id:
                    row_cursor = SyncCursor(updated, snow_sys_id)
                    if max_cursor is None or row_cursor > max_cursor:
                        max_cursor = row_cursor
            if page_rows and page_malformed / len(page_rows) > MALFORMED_PAGE_FAIL_RATIO:
                raise RuntimeError(
                    f"malformed row ratio exceeded threshold on page ({page_malformed}/{len(page_rows)})"
                )
            if counts["fetched"] >= MAX_RECORDS_PER_RUN:
                break
        if max_cursor is not None:
            _write_cursor(
                cosmos_store,
                config.DISPOSITION_SYNC_STATE_CONTAINER,
                cursor=max_cursor,
                updated_at=run_at,
            )
        summary = DispositionSyncSummary(
            status="success",
            **counts,
            message="" if max_cursor else "no rows processed; cursor unchanged",
            cursor_advanced=max_cursor is not None,
        )
    except Exception as exc:
        summary = DispositionSyncSummary(
            status="error", **counts, errors=1, message=str(exc), cursor_advanced=False
        )
    logger.info("ServiceNow disposition sync finished: %s", summary.as_dict())
    return summary.as_dict()


def load_field_map(path: str) -> dict[str, Any]:
    payload = _load_json_file(path, setting_name="SERVICENOW_DISPOSITION_FIELD_MAP")
    table = str(payload.get("table", "")).strip()
    if not _TABLE_NAME_PATTERN.fullmatch(table):
        raise DispositionSyncConfigError("field map table must match [a-z0-9_]+")
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        raise DispositionSyncConfigError("field map fields must be an object")
    for key in _REQUIRED_FIELD_KEYS:
        if not isinstance(fields.get(key), str) or not fields[key].strip():
            raise DispositionSyncConfigError(f"field map fields.{key} is required")
    states = payload.get("closed_state_values")
    if not isinstance(states, list) or not [value for value in states if str(value).strip()]:
        raise DispositionSyncConfigError("field map closed_state_values must be a non-empty array")
    return {
        "table": table,
        "fields": {key: str(value).strip() for key, value in fields.items() if str(value).strip()},
        "closed_state_values": [str(value).strip() for value in states if str(value).strip()],
    }


def load_code_map(path: str) -> dict[str, list[str]]:
    payload = _load_json_file(path, setting_name="SERVICENOW_DISPOSITION_CODE_MAP")
    if not isinstance(payload, dict):
        raise DispositionSyncConfigError("code map must be a JSON object")
    normalized: dict[str, list[str]] = {}
    for bucket in ALLOWED_VERDICTS:
        values = payload.get(bucket, []) or []
        if not isinstance(values, list):
            raise DispositionSyncConfigError(f"code map {bucket} must be an array")
        normalized[bucket] = [str(item).strip() for item in values if str(item).strip()]
    return normalized


def normalize_disposition(raw_value: Any, code_map: dict[str, list[str]]) -> tuple[str, str]:
    raw_text = str(raw_value or "").strip()
    if not raw_text:
        return normalize_verdict(None), ""
    lowered = raw_text.casefold()
    for bucket, entries in code_map.items():
        if any(entry.casefold() == lowered for entry in entries):
            return bucket, raw_text
    return normalize_verdict(raw_text), raw_text


def payload_hash(mapped_fields: dict[str, Any]) -> str:
    canonical = json.dumps(mapped_fields, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _process_row(
    *,
    raw_row: dict[str, Any],
    field_map: dict[str, Any],
    code_map: dict[str, list[str]],
    closed_states: list[str],
    config: Config,
    cosmos_store: CosmosStore,
    blob_service: Any | None,
    run_at: datetime,
) -> dict[str, Any]:
    mapped = _map_row_fields(raw_row, field_map)
    snow_sys_id = str(mapped.get("sys_id") or "").strip()
    updated = _parse_servicenow_datetime(mapped.get("sys_updated_on"))
    if not snow_sys_id or updated is None:
        return {"action": "malformed"}
    existing = cosmos_store.get_disposition(config.DISPOSITION_CONTAINER, snow_sys_id)
    if not _state_is_closed(str(mapped.get("state") or ""), closed_states):
        if not existing or existing.get("is_active") is False:
            return {
                "action": "skipped",
                "sys_updated_on": updated,
                "snow_sys_id": snow_sys_id,
            }
        cosmos_store.upsert_disposition(
            config.DISPOSITION_CONTAINER,
            _merge_deactivated_item(existing, sys_updated_on=updated, run_at=run_at),
        )
        return {
            "action": "deactivated",
            "sys_updated_on": updated,
            "snow_sys_id": snow_sys_id,
        }

    row_hash = payload_hash({key: mapped.get(key) for key in sorted(mapped)})
    if existing and str(existing.get("payload_hash") or "") == row_hash:
        return {
            "action": "skipped",
            "sys_updated_on": updated,
            "snow_sys_id": snow_sys_id,
        }
    normalized, raw = normalize_disposition(mapped.get("close_code"), code_map)
    correlation_id = str(mapped.get("correlation_id") or "").strip()
    case_id = str((existing or {}).get("case_id") or "").strip()
    if not case_id and correlation_id and config.CASE_INDEX_CONTAINER:
        case_id = _link_case_id(config, cosmos_store, blob_service, correlation_id)
    expires_at = run_at + timedelta(days=config.DISPOSITION_RETENTION_DAYS)
    item = {
        "snow_sys_id": snow_sys_id,
        "snow_number": str(mapped.get("number") or "").strip() or snow_sys_id,
        "snow_table": field_map["table"],
        "state": str(mapped.get("state") or "").strip(),
        "is_active": True,
        "closed_at": _format_servicenow_timestamp(_parse_servicenow_datetime(mapped.get("closed_at"))),
        "sys_updated_on": _format_servicenow_timestamp(updated),
        "disposition_normalized": normalized,
        "disposition_raw": raw,
        "close_notes": _truncate(str(mapped.get("close_notes") or ""), CLOSE_NOTES_MAX_CHARS),
        "short_description": str(mapped.get("short_description") or "").strip(),
        "search_name": str(mapped.get("search_name") or "").strip(),
        "correlation_id": correlation_id,
        "correlation_display": str(mapped.get("correlation_display") or "").strip(),
        "source_payload": _bounded_source_payload(mapped),
        "payload_hash": row_hash,
        "case_id": case_id,
        "synced_at": _format_servicenow_timestamp(run_at),
        "expires_at": _format_servicenow_timestamp(expires_at),
        "expires_at_epoch": int(expires_at.timestamp()),
    }
    cosmos_store.upsert_disposition(config.DISPOSITION_CONTAINER, item)
    return {
        "action": "upserted",
        "sys_updated_on": updated,
        "snow_sys_id": snow_sys_id,
        "linked": bool(case_id),
    }


def _link_case_id(
    config: Config,
    store: CosmosStore,
    blob_service: Any | None,
    correlation_id: str,
) -> str:
    candidates = store.find_cases_by_correlation(
        config.CASE_INDEX_CONTAINER,
        correlation_id=correlation_id,
        limit=CASE_LINK_SCAN_LIMIT,
    )
    if not candidates and blob_service is not None:
        candidates = []
        for row in store.list_cases(config.CASE_INDEX_CONTAINER, limit=CASE_LINK_SCAN_LIMIT):
            if str(row.get("finding_id") or "").strip() == correlation_id:
                candidates.append(row)
                continue
            blob_name = str(row.get("case_envelope_key") or "").strip()
            if blob_name and _alert_payload_matches(
                _load_alert_payload(config.CASE_ARCHIVE_CONTAINER, blob_name, blob_service),
                correlation_id,
            ):
                candidates.append(row)
    if not candidates:
        return ""
    best = max(candidates, key=lambda row: (str(row.get("processed_at", "")), str(row.get("case_id", ""))))
    return str(best.get("case_id") or "").strip()


def _load_alert_payload(container: str, blob_name: str, blob_service: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(read_blob(container, blob_name, store=blob_service).decode("utf-8"))
    except (UnicodeError, ValueError):
        return {}
    payload = parsed.get("alert_payload") if isinstance(parsed, dict) else None
    return payload if isinstance(payload, dict) else {}


def _alert_payload_matches(payload: dict[str, Any], correlation_id: str) -> bool:
    return any(
        value is not None and str(value).strip() == correlation_id
        for value in (payload.get(field) for field in _ALERT_CORRELATION_FIELDS)
    )


def _iter_table_api_pages(
    *, base_url: str, table_name: str, api_fields: list[str], closed_states: list[str],
    field_map: dict[str, Any], cursor: SyncCursor | datetime | None, backfill_days: int,
    run_at: datetime, token: str, session: Any, timeout_seconds: int,
) -> Iterator[list[dict[str, Any]]]:
    offset = fetched_total = 0
    closed_field = field_map["fields"]["closed_at"]
    updated_field = field_map["fields"]["sys_updated_on"]
    sys_id_field = field_map["fields"]["sys_id"]
    state_field = field_map["fields"]["state"]
    while fetched_total < MAX_RECORDS_PER_RUN:
        if cursor is None:
            query = (
                f"{closed_field}>{_servicenow_query_timestamp(run_at - timedelta(days=backfill_days))}"
                f"^{state_field}IN{','.join(closed_states)}"
            )
        else:
            boundary = cursor if isinstance(cursor, SyncCursor) else SyncCursor(cursor)
            timestamp = _servicenow_query_timestamp(boundary.updated_at)
            # NQ expresses the required union without relying on ambiguous OR/AND
            # precedence in ServiceNow encoded queries. A legacy timestamp-only
            # checkpoint has an empty sys_id and safely replays its boundary.
            query = (
                f"{updated_field}>{timestamp}"
                f"^NQ{updated_field}={timestamp}^{sys_id_field}>{boundary.sys_id}"
            )
        query += f"^ORDERBY{updated_field}^ORDERBY{sys_id_field}"
        response = _request_with_retry(
            session=session,
            method="GET",
            url=f"{base_url.rstrip('/')}/api/now/table/{table_name}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params={
                "sysparm_query": query,
                "sysparm_fields": ",".join(api_fields),
                "sysparm_display_value": "false",
                "sysparm_exclude_reference_link": "true",
                "sysparm_limit": str(PAGE_SIZE),
                "sysparm_offset": str(offset),
            },
            timeout=timeout_seconds,
        )
        body = response.json() if response.content else {}
        rows = body.get("result", []) if isinstance(body, dict) else []
        if not isinstance(rows, list) or not rows:
            break
        yield rows
        fetched_total += len(rows)
        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE


def _request_with_retry(*, session: Any, method: str, url: str, timeout: int, **kwargs: Any) -> Any:
    last_response = None
    for attempt in range(len(_RETRY_DELAYS_SECONDS) + 1):
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


def _read_cursor(store: CosmosStore, container_name: str) -> SyncCursor | None:
    row = store.get_sync_checkpoint(container_name, JOB_NAME)
    updated_at = _parse_servicenow_datetime(row.get("cursor_value")) if row else None
    if updated_at is None:
        return None
    return SyncCursor(updated_at, str(row.get("cursor_sys_id") or "").strip())


def _write_cursor(
    store: CosmosStore,
    container_name: str,
    *,
    cursor: SyncCursor,
    updated_at: datetime,
) -> None:
    store.upsert_sync_checkpoint(
        container_name,
        {
            "job_name": JOB_NAME,
            "cursor_value": _format_servicenow_timestamp(cursor.updated_at),
            "cursor_sys_id": cursor.sys_id,
            "updated_at": _format_servicenow_timestamp(updated_at),
        },
    )


def _resolve_sync_token(config: Config) -> str:
    direct = str(config.SERVICENOW_DISPOSITION_SYNC_TOKEN or "").strip()
    if direct:
        return direct
    name = str(config.SERVICENOW_DISPOSITION_SYNC_TOKEN_SECRET_NAME or "").strip()
    return resolve_secret_string(
        secret_name=name,
        setting_name="SERVICENOW_DISPOSITION_SYNC_TOKEN",
        secret_field="token",
        fallback_fields=("SERVICENOW_DISPOSITION_SYNC_TOKEN",),
    ) if name else ""


def _validate_container_names(config: Config) -> None:
    if not config.DISPOSITION_CONTAINER.strip():
        raise DispositionSyncConfigError("DISPOSITION_CONTAINER is required when disposition sync is enabled")
    if not config.DISPOSITION_SYNC_STATE_CONTAINER.strip():
        raise DispositionSyncConfigError(
            "DISPOSITION_SYNC_STATE_CONTAINER is required when disposition sync is enabled"
        )


def _load_json_file(path: str, *, setting_name: str) -> Any:
    clean = str(path or "").strip()
    if not clean:
        raise DispositionSyncConfigError(f"{setting_name} path is required")
    file_path = Path(clean)
    if not file_path.is_file():
        raise DispositionSyncConfigError(f"{setting_name} file not found: {clean}")
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DispositionSyncConfigError(f"{setting_name} is not valid JSON") from exc


def _map_row_fields(raw: dict[str, Any], field_map: dict[str, Any]) -> dict[str, Any]:
    mapped = {logical: raw.get(field) for logical, field in field_map["fields"].items()}
    mapped["sys_id"] = mapped.get("sys_id") or raw.get("sys_id")
    return mapped


def _api_field_list(field_map: dict[str, Any]) -> list[str]:
    return sorted({"sys_id", *(str(value).strip() for value in field_map["fields"].values())})


def _merge_deactivated_item(existing: dict[str, Any], *, sys_updated_on: datetime, run_at: datetime) -> dict[str, Any]:
    merged = dict(existing)
    merged.update(
        is_active=False,
        sys_updated_on=_format_servicenow_timestamp(sys_updated_on),
        synced_at=_format_servicenow_timestamp(run_at),
    )
    return merged


def _bounded_source_payload(mapped: dict[str, Any]) -> dict[str, Any]:
    payload = {key: mapped.get(key) for key in sorted(mapped)}
    if len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")) <= SOURCE_PAYLOAD_MAX_BYTES:
        return payload
    trimmed = dict(payload)
    for key in list(trimmed):
        trimmed[key] = _truncate(str(trimmed[key]), 512)
        if len(json.dumps(trimmed, ensure_ascii=False).encode("utf-8")) <= SOURCE_PAYLOAD_MAX_BYTES:
            return trimmed
    return {"truncated": True, "payload_hash_hint": payload_hash(payload)}


def _state_is_closed(state: str, closed_states: list[str]) -> bool:
    return state.casefold() in {value.casefold() for value in closed_states}


def _servicenow_query_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _format_servicenow_timestamp(value: datetime | None) -> str:
    return "" if value is None else value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_servicenow_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    if " " in text and "T" not in text:
        text = text.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _truncate(value: str, max_chars: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= max_chars else text[: max_chars - 3].rstrip() + "..."


def _coerce_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
