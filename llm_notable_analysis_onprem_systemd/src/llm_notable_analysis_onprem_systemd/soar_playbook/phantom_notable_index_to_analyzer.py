"""Template Splunk SOAR (Phantom) playbook for notable-index polling.

This alternative template is intended for environments where SOAR should query
Splunk ES for recent notables from the notable index, then upload one JSON file
per notable to the analyzer host.

It differs from ``phantom_notable_to_analyzer.py``:
- This template is query/schedule driven.
- The existing template is notable-container triggered.

Adjust action names, asset names, query fields, and result parsing to match your
SOAR app integrations before production use.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, List, Mapping, Sequence, Tuple

try:
    import phantom.rules as phantom
except ImportError:  # pragma: no cover - enables local test imports
    class _PhantomStub:
        """Fallback stub used when imported outside Phantom runtime."""

        def debug(self, *_args: Any, **_kwargs: Any) -> None:
            """No-op debug logger."""

        def error(self, *_args: Any, **_kwargs: Any) -> None:
            """No-op error logger."""

        def act(self, *_args: Any, **_kwargs: Any) -> None:
            """Raise when runtime-only action helpers are used outside Phantom."""
            raise RuntimeError("phantom runtime is unavailable")

        def vault_add(self, *_args: Any, **_kwargs: Any) -> Tuple[bool, str, str]:
            """Raise when runtime-only vault helpers are used outside Phantom."""
            raise RuntimeError("phantom runtime is unavailable")

        def add_note(self, *_args: Any, **_kwargs: Any) -> None:
            """Raise when runtime-only note helpers are used outside Phantom."""
            raise RuntimeError("phantom runtime is unavailable")

    phantom = _PhantomStub()


# ---------------------------------------------------------------------------
# Operator-tunable constants
# ---------------------------------------------------------------------------
SPLUNK_ASSET_NAME = "splunk-es"
SPLUNK_QUERY_ACTION = "run query"
SFTP_ASSET_NAME = "notable-analyzer-sftp"
SFTP_UPLOAD_ACTION = "upload file"
SFTP_REMOTE_DIR = "/incoming"
LOOKBACK_MINUTES = 15
MAX_NOTABLES = 100
PROCESS_STATUSES = ("new", "open")
QUERY_FIELDS = (
    "_time",
    "event_id",
    "finding_id",
    "notable_id",
    "search_name",
    "rule_name",
    "rule_title",
    "summary",
    "description",
    "severity",
    "urgency",
    "owner",
    "security_domain",
    "status",
    "risk_score",
    "threat_category",
    "orig_sid",
)


def on_start(container: Mapping[str, Any]) -> None:
    """Playbook entry point.

    Args:
        container: Phantom container dictionary. For scheduled/manual playbooks,
            this may be a thin control container rather than a notable container.
    """
    phantom.debug("Starting Phantom notable-index->analyzer playbook")
    query = build_notable_query(
        lookback_minutes=LOOKBACK_MINUTES,
        statuses=PROCESS_STATUSES,
        max_notables=MAX_NOTABLES,
        query_fields=QUERY_FIELDS,
    )
    params = [{"query": query}]
    phantom.act(
        action=SPLUNK_QUERY_ACTION,
        parameters=params,
        assets=[SPLUNK_ASSET_NAME],
        callback=_query_done,
        name="query_recent_notables",
    )


def on_finish(container: Mapping[str, Any], summary: Mapping[str, Any]) -> None:
    """Playbook completion hook.

    Args:
        container: Phantom container dictionary.
        summary: Phantom playbook summary payload.
    """
    phantom.debug("Finished Phantom notable-index->analyzer playbook")


def build_notable_query(
    *,
    lookback_minutes: int,
    statuses: Sequence[str],
    max_notables: int,
    query_fields: Sequence[str],
) -> str:
    """Build a Splunk search for recent notable-index records.

    Args:
        lookback_minutes: Relative lookback window for recent notables.
        statuses: Allowed notable states to retrieve.
        max_notables: Maximum number of notable rows to return.
        query_fields: Splunk fields to keep in the result set.

    Returns:
        Splunk search string suitable for a SOAR "run query" action.
    """
    safe_lookback = max(1, int(lookback_minutes))
    safe_max = max(1, int(max_notables))
    normalized_statuses = [str(status).strip().lower() for status in statuses if status]
    if normalized_statuses:
        where_clause = " OR ".join(f'status="{status}"' for status in normalized_statuses)
        status_filter = f" | search ({where_clause})"
    else:
        status_filter = ""
    fields_clause = ", ".join(str(field).strip() for field in query_fields if field)
    return (
        f"search index=notable earliest=-{safe_lookback}m latest=now"
        f"{status_filter}"
        f" | fields {fields_clause}"
        f" | head {safe_max}"
    )


def extract_query_rows(results: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Extract row dictionaries from Phantom action callback results.

    Args:
        results: Callback results payload from a Phantom action.

    Returns:
        Flat list of row dictionaries from supported result containers.
    """
    rows: List[Dict[str, Any]] = []
    for result in results or []:
        rows.extend(_extract_rows_from_mapping(result))
        action_results = result.get("action_results")
        if isinstance(action_results, list):
            for action_result in action_results:
                if isinstance(action_result, Mapping):
                    rows.extend(_extract_rows_from_mapping(action_result))
    return rows


def normalize_notable_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize one Splunk notable row into analyzer payload shape.

    Args:
        row: One notable-index result row.

    Returns:
        Analyzer-friendly JSON payload with explicit unknown placeholders.
    """
    notable_id = _first_non_empty(
        row.get("notable_id"),
        row.get("event_id"),
        row.get("orig_sid"),
        "unknown",
    )
    event_id = _first_non_empty(
        row.get("event_id"),
        row.get("finding_id"),
        row.get("orig_sid"),
        notable_id,
    )
    raw_finding_id = _first_non_empty(
        row.get("finding_id"),
        row.get("event_id"),
        row.get("notable_id"),
        row.get("orig_sid"),
        "unknown",
    )
    finding_id = safe_filename(raw_finding_id)
    summary = _first_non_empty(
        row.get("summary"),
        row.get("description"),
        row.get("rule_title"),
        row.get("rule_name"),
        row.get("search_name"),
        "unknown",
    )
    search_name = _first_non_empty(
        row.get("search_name"),
        row.get("rule_name"),
        row.get("rule_title"),
        "unknown",
    )
    threat_category = _first_non_empty(
        row.get("threat_category"),
        row.get("security_domain"),
        "unknown",
    )
    risk_score = _first_non_empty(row.get("risk_score"), "unknown")
    alert_time = _first_non_empty(row.get("_time"), "unknown")

    payload = {
        "summary": summary,
        "notable_id": str(notable_id),
        "event_id": str(event_id),
        "finding_id": finding_id,
        "search_name": str(search_name),
        "risk_score": risk_score,
        "threat_category": str(threat_category),
        "alert_time": str(alert_time),
        "severity": _first_non_empty(row.get("severity"), "unknown"),
        "urgency": _first_non_empty(row.get("urgency"), "unknown"),
        "status": _first_non_empty(row.get("status"), "unknown"),
        "owner": _first_non_empty(row.get("owner"), "unknown"),
        "security_domain": _first_non_empty(row.get("security_domain"), "unknown"),
        "orig_sid": _first_non_empty(row.get("orig_sid"), "unknown"),
        "supporting_events": [],
        "raw_event": json.dumps(dict(row), ensure_ascii=True, default=str, sort_keys=True),
        "ingest_source": "splunk_soar_phantom_notable_index",
    }
    return payload


def safe_filename(value: Any) -> str:
    """Sanitize identifier text for safe filename usage.

    Args:
        value: Raw identifier value.

    Returns:
        ASCII-safe identifier capped to 100 characters.
    """
    text = str(value or "unknown")
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in text)
    return safe[:100] or "unknown"


def _query_done(
    action: str,
    success: bool,
    container: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
    handle: Any,
) -> None:
    """Handle completion of the Splunk notable-index query.

    Args:
        action: Phantom action name.
        success: Whether the query action succeeded.
        container: Phantom container dictionary.
        results: Callback results payload.
        handle: Phantom callback handle.
    """
    if not success:
        phantom.error("Splunk notable query action failed")
        return

    rows = extract_query_rows(results)
    if not rows:
        phantom.debug("No notable rows returned from notable index query")
        return

    seen_finding_ids = set()
    uploaded = 0
    for row in rows:
        payload = normalize_notable_row(row)
        finding_id = payload["finding_id"]
        if finding_id in seen_finding_ids:
            continue
        seen_finding_ids.add(finding_id)
        _send_payload_to_analyzer(container, payload)
        uploaded += 1

    phantom.debug(f"Queued {uploaded} notable payload(s) for analyzer upload")


def _send_payload_to_analyzer(
    container: Mapping[str, Any], payload: Mapping[str, Any]
) -> None:
    """Write one payload to temp storage and queue SFTP upload.

    Args:
        container: Phantom container dictionary.
        payload: Analyzer payload dictionary for one notable.
    """
    local_path, remote_file_name = _write_payload_to_temp_file(payload)
    if not local_path:
        phantom.error("Failed to write payload temp file for analyzer upload")
        return

    success, message, vault_id = phantom.vault_add(
        container=container,
        file_location=local_path,
        file_name=remote_file_name,
    )
    if not success:
        phantom.error(f"vault_add failed for {remote_file_name}: {message}")
        return

    params = [
        {
            "vault_id": vault_id,
            "remote_path": SFTP_REMOTE_DIR,
            "file_name": remote_file_name,
        }
    ]
    phantom.act(
        action=SFTP_UPLOAD_ACTION,
        parameters=params,
        assets=[SFTP_ASSET_NAME],
        callback=_upload_done,
        name=f"send_notable_{payload['finding_id']}",
    )


def _write_payload_to_temp_file(
    payload: Mapping[str, Any]
) -> Tuple[str | None, str | None]:
    """Write payload JSON to a local temp file.

    Args:
        payload: JSON-serializable payload dictionary.

    Returns:
        Tuple of ``(local_path, remote_file_name)`` on success, otherwise
        ``(None, None)``.
    """
    finding_id = safe_filename(payload.get("finding_id", "unknown"))
    remote_file_name = f"{finding_id}.json"
    fd, tmp_path = tempfile.mkstemp(prefix="notable_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2, default=str)
        return tmp_path, remote_file_name
    except Exception:
        try:
            os.close(fd)
        except Exception:
            pass
        return None, None


def _upload_done(
    action: str,
    success: bool,
    container: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
    handle: Any,
) -> None:
    """Handle callback after SFTP upload action finishes.

    Args:
        action: Phantom action name.
        success: Whether the action succeeded.
        container: Phantom container dictionary.
        results: Action results payload.
        handle: Phantom callback handle.
    """
    if success:
        phantom.debug("Uploaded notable-index payload to analyzer incoming directory")
        phantom.add_note(
            container=container,
            title="Sent notable-index results to analyzer",
            content=(
                "SOAR playbook queried recent notables from Splunk ES and uploaded "
                "payload(s) for analyzer processing."
            ),
            note_type="general",
        )
    else:
        phantom.error("SFTP upload action failed for notable-index payload")


def _extract_rows_from_mapping(result: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Extract rows from a generic action-result mapping.

    Args:
        result: Action-result mapping that may contain a ``data`` list.

    Returns:
        List of row dictionaries.
    """
    rows: List[Dict[str, Any]] = []
    data = result.get("data")
    if isinstance(data, list):
        for row in data:
            if isinstance(row, Mapping):
                rows.append(dict(row))
    return rows


def _first_non_empty(*values: Any) -> Any:
    """Return the first non-empty value from a candidate list.

    Args:
        *values: Candidate values in priority order.

    Returns:
        The first non-empty value, or the last supplied value if all are empty.
    """
    fallback = values[-1] if values else "unknown"
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return fallback
