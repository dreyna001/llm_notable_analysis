"""Read-only ServiceNow closed disposition sync into Postgres."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
import requests

from .case_db import default_connect, fetchone, set_statement_timeout
from .config import Config
from .verdicts import ALLOWED_VERDICTS, normalize_verdict

logger = logging.getLogger(__name__)

JOB_NAME = "servicenow_closed"
MAX_RECORDS_PER_RUN = 500
PAGE_SIZE = 100
MAX_HTTP_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0
MALFORMED_ROW_FAIL_RATIO = 0.10
CLOSE_NOTES_MAX_CHARS = 4000
SOURCE_PAYLOAD_MAX_BYTES = 32 * 1024

_TABLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")
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
_OPTIONAL_FIELD_KEYS = ("short_description", "correlation_display", "search_name")
_CODE_MAP_BUCKETS = ALLOWED_VERDICTS


@dataclass(frozen=True)
class FieldMap:
    table: str
    fields: dict[str, str]
    closed_state_values: tuple[str, ...]


@dataclass(frozen=True)
class CodeMap:
    likely_malicious: tuple[str, ...]
    likely_benign: tuple[str, ...]
    unknown: tuple[str, ...]


@dataclass
class MappedIncident:
    snow_sys_id: str
    snow_number: str
    snow_table: str
    state: str
    is_active: bool
    closed_at: datetime | None
    sys_updated_on: datetime
    disposition_normalized: str
    disposition_raw: str | None
    close_notes: str | None
    short_description: str | None
    search_name: str | None
    correlation_id: str | None
    correlation_display: str | None
    source_payload: dict[str, Any]
    payload_hash: str


@dataclass
class SyncSummary:
    enabled: bool = True
    skipped: bool = False
    fetched: int = 0
    upserted: int = 0
    skipped_noop: int = 0
    deactivated: int = 0
    linked: int = 0
    malformed: int = 0
    errors: list[str] = field(default_factory=list)
    cursor_advanced: bool = False
    max_sys_updated_on: datetime | None = None


def _truncate(value: str, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _parse_sn_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
    ):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sn_query_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _validate_field_map_payload(payload: Any) -> FieldMap:
    if not isinstance(payload, dict):
        raise ValueError("field map must be a JSON object")
    table = str(payload.get("table", "")).strip()
    if not _TABLE_NAME_RE.fullmatch(table):
        raise ValueError("field map table must match [a-z0-9_]+")
    fields_raw = payload.get("fields")
    if not isinstance(fields_raw, dict):
        raise ValueError("field map fields must be an object")
    fields: dict[str, str] = {}
    for key in _REQUIRED_FIELD_KEYS:
        column = str(fields_raw.get(key, "")).strip()
        if not column:
            raise ValueError(f"field map fields.{key} is required")
        fields[key] = column
    for key in _OPTIONAL_FIELD_KEYS:
        column = str(fields_raw.get(key, "")).strip()
        if column:
            fields[key] = column
    closed_values = payload.get("closed_state_values")
    if not isinstance(closed_values, list) or not closed_values:
        raise ValueError("field map closed_state_values must be a non-empty array")
    normalized_closed = tuple(
        str(item).strip() for item in closed_values if str(item).strip()
    )
    if not normalized_closed:
        raise ValueError("field map closed_state_values must contain values")
    return FieldMap(table=table, fields=fields, closed_state_values=normalized_closed)


def load_field_map(path: str | Path) -> FieldMap:
    """Load and validate the ServiceNow disposition field map JSON."""
    map_path = Path(path)
    if not map_path.is_file():
        raise ValueError(f"field map not found: {map_path}")
    try:
        payload = json.loads(map_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid field map JSON: {map_path}") from exc
    return _validate_field_map_payload(payload)


def _validate_code_map_payload(payload: Any) -> CodeMap:
    if not isinstance(payload, dict):
        raise ValueError("code map must be a JSON object")
    buckets: dict[str, tuple[str, ...]] = {}
    for bucket in _CODE_MAP_BUCKETS:
        values = payload.get(bucket)
        if not isinstance(values, list):
            raise ValueError(f"code map {bucket} must be an array")
        normalized = tuple(str(item).strip() for item in values if str(item).strip())
        buckets[bucket] = normalized
    return CodeMap(
        likely_malicious=buckets["likely_malicious"],
        likely_benign=buckets["likely_benign"],
        unknown=buckets["unknown"],
    )


def load_code_map(path: str | Path) -> CodeMap:
    """Load and validate the ServiceNow disposition code map JSON."""
    map_path = Path(path)
    if not map_path.is_file():
        raise ValueError(f"code map not found: {map_path}")
    try:
        payload = json.loads(map_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid code map JSON: {map_path}") from exc
    return _validate_code_map_payload(payload)


def normalize_disposition(raw: Any, code_map: CodeMap) -> str:
    """Normalize a ServiceNow close code using code map then verdict rules."""
    text = str(raw or "").strip()
    if not text:
        return "unknown"
    lowered = text.casefold()
    for bucket, values in (
        ("likely_malicious", code_map.likely_malicious),
        ("likely_benign", code_map.likely_benign),
        ("unknown", code_map.unknown),
    ):
        for candidate in values:
            if candidate.casefold() == lowered:
                return bucket
    return normalize_verdict(text)


def _bounded_source_payload(row: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) <= SOURCE_PAYLOAD_MAX_BYTES:
        return row
    trimmed = dict(row)
    trimmed["_truncated"] = True
    while trimmed:
        encoded = json.dumps(trimmed, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        if len(encoded) <= SOURCE_PAYLOAD_MAX_BYTES:
            return trimmed
        if len(trimmed) == 1:
            break
        trimmed.pop(next(reversed(trimmed)))
    return {"_truncated": True}


def _payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _row_value(row: dict[str, Any], column: str) -> Any:
    return row.get(column)


def _is_closed_state(state: str, field_map: FieldMap) -> bool:
    normalized = str(state or "").strip().casefold()
    closed = {value.casefold() for value in field_map.closed_state_values}
    return normalized in closed


def map_incident_row(
    row: dict[str, Any],
    *,
    field_map: FieldMap,
    code_map: CodeMap,
) -> MappedIncident:
    """Map one ServiceNow Table API row into a disposition record."""
    sys_id = str(_row_value(row, field_map.fields["sys_id"]) or "").strip()
    number = str(_row_value(row, field_map.fields["number"]) or "").strip()
    state = str(_row_value(row, field_map.fields["state"]) or "").strip()
    if not sys_id:
        raise ValueError("missing sys_id")
    if not number:
        raise ValueError("missing number")
    if not state:
        raise ValueError("missing state")

    sys_updated_on = _parse_sn_datetime(_row_value(row, field_map.fields["sys_updated_on"]))
    if sys_updated_on is None:
        raise ValueError("missing or invalid sys_updated_on")

    closed_at = _parse_sn_datetime(_row_value(row, field_map.fields["closed_at"]))
    disposition_raw = str(_row_value(row, field_map.fields["close_code"]) or "").strip()
    close_notes = _truncate(
        str(_row_value(row, field_map.fields["close_notes"]) or ""),
        CLOSE_NOTES_MAX_CHARS,
    )
    correlation_id = str(
        _row_value(row, field_map.fields["correlation_id"]) or ""
    ).strip() or None
    short_description = None
    if "short_description" in field_map.fields:
        short_description = str(
            _row_value(row, field_map.fields["short_description"]) or ""
        ).strip() or None
    correlation_display = None
    if "correlation_display" in field_map.fields:
        correlation_display = str(
            _row_value(row, field_map.fields["correlation_display"]) or ""
        ).strip() or None
    search_name = None
    if "search_name" in field_map.fields:
        search_name = str(
            _row_value(row, field_map.fields["search_name"]) or ""
        ).strip() or None

    hash_payload = {
        "snow_sys_id": sys_id,
        "snow_number": number,
        "state": state,
        "closed_at": closed_at.isoformat() if closed_at else None,
        "sys_updated_on": sys_updated_on.isoformat(),
        "disposition_raw": disposition_raw or None,
        "close_notes": close_notes or None,
        "short_description": short_description,
        "search_name": search_name,
        "correlation_id": correlation_id,
        "correlation_display": correlation_display,
    }

    return MappedIncident(
        snow_sys_id=sys_id,
        snow_number=number,
        snow_table=field_map.table,
        state=state,
        is_active=_is_closed_state(state, field_map),
        closed_at=closed_at,
        sys_updated_on=sys_updated_on,
        disposition_normalized=normalize_disposition(disposition_raw, code_map),
        disposition_raw=disposition_raw or None,
        close_notes=close_notes or None,
        short_description=short_description,
        search_name=search_name,
        correlation_id=correlation_id,
        correlation_display=correlation_display,
        source_payload=_bounded_source_payload(row),
        payload_hash=_payload_hash(hash_payload),
    )


def _validate_servicenow_https(base_url: str) -> None:
    if not str(base_url or "").strip().startswith("https://"):
        raise ValueError("ServiceNow base URL must be HTTPS")


def _request_with_retry(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, str],
    timeout_seconds: int,
    session: requests.Session | None = None,
) -> requests.Response:
    client = session or requests
    last_exc: requests.RequestException | None = None
    for attempt in range(MAX_HTTP_RETRIES):
        try:
            response = client.request(
                method,
                url,
                headers=headers,
                params=params,
                timeout=timeout_seconds,
            )
        except requests.RequestException as exc:
            last_exc = exc
            if attempt + 1 >= MAX_HTTP_RETRIES:
                raise
            time.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
            continue
        if response.status_code in {401, 403}:
            response.raise_for_status()
        if response.status_code in {429, 500, 502, 503, 504}:
            if attempt + 1 >= MAX_HTTP_RETRIES:
                response.raise_for_status()
            time.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
            continue
        response.raise_for_status()
        return response
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("ServiceNow request failed without response")


def fetch_closed_incidents(
    config: Config,
    *,
    field_map: FieldMap,
    cursor: datetime | None,
    backfill_start: datetime,
    session: requests.Session | None = None,
) -> Iterator[dict[str, Any]]:
    """Fetch closed or updated incidents from ServiceNow Table API with pagination."""
    _validate_servicenow_https(config.SERVICENOW_BASE_URL)
    token = str(config.SERVICENOW_DISPOSITION_SYNC_TOKEN or "").strip()
    if not token:
        raise ValueError("SERVICENOW_DISPOSITION_SYNC_TOKEN is required")

    base_url = str(config.SERVICENOW_BASE_URL).rstrip("/")
    url = f"{base_url}/api/now/table/{field_map.table}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    timeout_seconds = int(getattr(config, "SERVICENOW_TIMEOUT_SECONDS", 15))

    field_columns = sorted(set(field_map.fields.values()))
    if "sys_id" not in field_columns:
        field_columns.append(field_map.fields["sys_id"])

    closed_csv = ",".join(field_map.closed_state_values)
    updated_column = field_map.fields["sys_updated_on"]
    closed_at_column = field_map.fields["closed_at"]
    state_column = field_map.fields["state"]

    fetched = 0
    offset = 0
    while fetched < MAX_RECORDS_PER_RUN:
        limit = min(PAGE_SIZE, MAX_RECORDS_PER_RUN - fetched)
        if cursor is None:
            query = (
                f"{closed_at_column}>{_sn_query_timestamp(backfill_start)}"
                f"^{state_column}IN{closed_csv}"
            )
        else:
            query = f"{updated_column}>{_sn_query_timestamp(cursor)}"
        params = {
            "sysparm_query": query,
            "sysparm_fields": ",".join(field_columns),
            "sysparm_display_value": "false",
            "sysparm_exclude_reference_link": "true",
            "sysparm_limit": str(limit),
            "sysparm_offset": str(offset),
            "sysparm_order_by": updated_column,
        }
        response = _request_with_retry(
            "GET",
            url,
            headers=headers,
            params=params,
            timeout_seconds=timeout_seconds,
            session=session,
        )
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("ServiceNow response must be a JSON object")
        results = body.get("result", [])
        if not isinstance(results, list):
            raise ValueError("ServiceNow result must be an array")
        if not results:
            break
        for row in results:
            if isinstance(row, dict):
                yield row
                fetched += 1
                if fetched >= MAX_RECORDS_PER_RUN:
                    return
        if len(results) < limit:
            break
        offset += limit


def _read_cursor(conn: Any) -> datetime | None:
    row = fetchone(
        conn.execute(
            """
            SELECT cursor_value
            FROM notable_dispositions.sync_state
            WHERE job_name = %s
            """,
            (JOB_NAME,),
        )
    )
    if row is None:
        return None
    value = row[0] if not isinstance(row, dict) else row.get("cursor_value")
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return _parse_sn_datetime(value)


def _write_cursor(conn: Any, cursor_value: datetime) -> None:
    conn.execute(
        """
        INSERT INTO notable_dispositions.sync_state (job_name, cursor_value, updated_at)
        VALUES (%s, %s, now())
        ON CONFLICT (job_name) DO UPDATE
        SET cursor_value = EXCLUDED.cursor_value,
            updated_at = now()
        """,
        (JOB_NAME, cursor_value),
    )


def _existing_payload_hash(conn: Any, snow_sys_id: str) -> str | None:
    row = fetchone(
        conn.execute(
            """
            SELECT payload_hash
            FROM notable_dispositions.servicenow_closed_incidents
            WHERE snow_sys_id = %s
            """,
            (snow_sys_id,),
        )
    )
    if row is None:
        return None
    return str(row[0] if not isinstance(row, dict) else row.get("payload_hash") or "")


def _upsert_incident(
    conn: Any,
    incident: MappedIncident,
    *,
    retention_days: int,
) -> str:
    """Upsert one incident row. Returns action: inserted, updated, skipped."""
    existing_hash = _existing_payload_hash(conn, incident.snow_sys_id)
    if existing_hash == incident.payload_hash:
        return "skipped"

    expires_at = datetime.now(timezone.utc) + timedelta(days=int(retention_days))
    conn.execute(
        """
        INSERT INTO notable_dispositions.servicenow_closed_incidents (
            snow_sys_id,
            snow_number,
            snow_table,
            state,
            is_active,
            closed_at,
            sys_updated_on,
            disposition_normalized,
            disposition_raw,
            close_notes,
            short_description,
            search_name,
            correlation_id,
            correlation_display,
            source_payload,
            payload_hash,
            synced_at,
            expires_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, now(), %s
        )
        ON CONFLICT (snow_sys_id) DO UPDATE SET
            snow_number = EXCLUDED.snow_number,
            snow_table = EXCLUDED.snow_table,
            state = EXCLUDED.state,
            is_active = EXCLUDED.is_active,
            closed_at = EXCLUDED.closed_at,
            sys_updated_on = EXCLUDED.sys_updated_on,
            disposition_normalized = EXCLUDED.disposition_normalized,
            disposition_raw = EXCLUDED.disposition_raw,
            close_notes = EXCLUDED.close_notes,
            short_description = EXCLUDED.short_description,
            search_name = EXCLUDED.search_name,
            correlation_id = EXCLUDED.correlation_id,
            correlation_display = EXCLUDED.correlation_display,
            source_payload = EXCLUDED.source_payload,
            payload_hash = EXCLUDED.payload_hash,
            synced_at = now(),
            expires_at = EXCLUDED.expires_at
        """,
        (
            incident.snow_sys_id,
            incident.snow_number,
            incident.snow_table,
            incident.state,
            incident.is_active,
            incident.closed_at,
            incident.sys_updated_on,
            incident.disposition_normalized,
            incident.disposition_raw,
            incident.close_notes,
            incident.short_description,
            incident.search_name,
            incident.correlation_id,
            incident.correlation_display,
            json.dumps(incident.source_payload),
            incident.payload_hash,
            expires_at,
        ),
    )
    return "inserted" if existing_hash is None else "updated"


def _deactivate_incident(conn: Any, incident: MappedIncident) -> bool:
    row = fetchone(
        conn.execute(
            """
            UPDATE notable_dispositions.servicenow_closed_incidents
            SET is_active = false,
                state = %s,
                sys_updated_on = %s,
                synced_at = now()
            WHERE snow_sys_id = %s
              AND is_active = true
            RETURNING snow_sys_id
            """,
            (incident.state, incident.sys_updated_on, incident.snow_sys_id),
        )
    )
    return row is not None


def link_case_ids(
    conn: Any,
    *,
    case_schema: str,
    correlation_ids: list[str],
) -> dict[str, str | None]:
    """Link correlation IDs to archived case_id values using deterministic rules."""
    links: dict[str, str | None] = {}
    unique_ids = [value for value in dict.fromkeys(correlation_ids) if value]
    if not unique_ids:
        return links

    schema_ident = case_schema.strip()
    for correlation_id in unique_ids:
        row = fetchone(
            conn.execute(
                f"""
                SELECT case_id
                FROM {schema_ident}.cases
                WHERE correlation_id = %s
                   OR alert_payload->>'notable_id' = %s
                   OR alert_payload->>'event_id' = %s
                   OR alert_payload->>'sid' = %s
                ORDER BY processed_at DESC, case_id ASC
                LIMIT 1
                """,
                (correlation_id, correlation_id, correlation_id, correlation_id),
            )
        )
        if row is None:
            links[correlation_id] = None
            continue
        case_id = row[0] if not isinstance(row, dict) else row.get("case_id")
        links[correlation_id] = str(case_id) if case_id else None
    return links


def _apply_case_links(conn: Any, links: dict[str, str | None]) -> int:
    linked = 0
    for correlation_id, case_id in links.items():
        if not case_id:
            continue
        result = conn.execute(
            """
            UPDATE notable_dispositions.servicenow_closed_incidents
            SET case_id = %s
            WHERE correlation_id = %s
              AND (case_id IS DISTINCT FROM %s)
            """,
            (case_id, correlation_id, case_id),
        )
        if getattr(result, "rowcount", 0):
            linked += int(result.rowcount)
    return linked


def run_disposition_sync(
    config: Config,
    connect: Callable[[str], Any] | None = None,
) -> SyncSummary:
    """Run one ServiceNow closed disposition sync cycle."""
    summary = SyncSummary()
    if not bool(getattr(config, "SERVICENOW_DISPOSITION_SYNC_ENABLED", False)):
        summary.enabled = False
        summary.skipped = True
        return summary

    _validate_servicenow_https(config.SERVICENOW_BASE_URL)
    token = str(getattr(config, "SERVICENOW_DISPOSITION_SYNC_TOKEN", "")).strip()
    if not token:
        summary.errors.append("SERVICENOW_DISPOSITION_SYNC_TOKEN is required")
        return summary
    dsn = str(getattr(config, "CASE_POSTGRES_DSN", "")).strip()
    if not dsn:
        summary.errors.append("CASE_POSTGRES_DSN is required")
        return summary

    field_map = load_field_map(config.SERVICENOW_DISPOSITION_FIELD_MAP)
    code_map = load_code_map(config.SERVICENOW_DISPOSITION_CODE_MAP)
    backfill_days = int(getattr(config, "SERVICENOW_DISPOSITION_BACKFILL_DAYS", 90))
    retention_days = int(getattr(config, "DISPOSITION_RETENTION_DAYS", 365))
    backfill_start = datetime.now(timezone.utc) - timedelta(days=backfill_days)

    connect_fn = connect or default_connect
    conn = connect_fn(dsn)
    try:
        set_statement_timeout(conn, int(getattr(config, "CASE_POSTGRES_STATEMENT_TIMEOUT_MS", 5000)))
        cursor = _read_cursor(conn)
        rows = list(
            fetch_closed_incidents(
                config,
                field_map=field_map,
                cursor=cursor,
                backfill_start=backfill_start,
            )
        )
        summary.fetched = len(rows)
        if not rows:
            conn.commit()
            return summary

        mapped_rows: list[MappedIncident] = []
        malformed = 0
        for row in rows:
            try:
                mapped_rows.append(
                    map_incident_row(row, field_map=field_map, code_map=code_map)
                )
            except ValueError as exc:
                malformed += 1
                logger.warning("skipping malformed ServiceNow row: %s", exc)

        summary.malformed = malformed
        if mapped_rows and malformed / len(rows) > MALFORMED_ROW_FAIL_RATIO:
            conn.rollback()
            summary.errors.append(
                f"malformed row ratio exceeded {MALFORMED_ROW_FAIL_RATIO:.0%}"
            )
            return summary

        max_sys_updated_on: datetime | None = None
        correlation_ids: list[str] = []

        for incident in mapped_rows:
            if max_sys_updated_on is None or incident.sys_updated_on > max_sys_updated_on:
                max_sys_updated_on = incident.sys_updated_on

            if incident.is_active:
                action = _upsert_incident(
                    conn,
                    incident,
                    retention_days=retention_days,
                )
                if action == "skipped":
                    summary.skipped_noop += 1
                else:
                    summary.upserted += 1
                if incident.correlation_id:
                    correlation_ids.append(incident.correlation_id)
            else:
                if _deactivate_incident(conn, incident):
                    summary.deactivated += 1
                if max_sys_updated_on is not None:
                    pass

        if correlation_ids:
            links = link_case_ids(
                conn,
                case_schema=str(config.CASE_POSTGRES_SCHEMA),
                correlation_ids=correlation_ids,
            )
            summary.linked = _apply_case_links(conn, links)

        if max_sys_updated_on is not None:
            _write_cursor(conn, max_sys_updated_on)
            summary.cursor_advanced = True
            summary.max_sys_updated_on = max_sys_updated_on

        conn.commit()
    except Exception as exc:
        conn.rollback()
        summary.errors.append(str(exc))
        logger.exception("ServiceNow disposition sync failed")
    finally:
        conn.close()

    logger.info(
        "servicenow disposition sync summary fetched=%s upserted=%s skipped_noop=%s "
        "deactivated=%s linked=%s malformed=%s cursor_advanced=%s",
        summary.fetched,
        summary.upserted,
        summary.skipped_noop,
        summary.deactivated,
        summary.linked,
        summary.malformed,
        summary.cursor_advanced,
    )
    return summary
