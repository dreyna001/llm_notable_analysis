"""
Template Splunk SOAR (Phantom) playbook:
Send one notable + supporting events to llm_notable_analysis_onprem_systemd as JSON.

This is intentionally a simple baseline:
- Build one JSON payload per notable container
- Keep payload format-agnostic (raw notable/container context, no PoC field mapping)
- Upload to SFTP drop location consumed by analyzer

Adjust constants and action parameter names to match your SOAR asset app.
"""

import json
import os
import tempfile
from datetime import datetime, timezone

import phantom.rules as phantom


# ---------------------------------------------------------------------------
# Operator-tunable constants
# ---------------------------------------------------------------------------
SFTP_ASSET_NAME = "notable-analyzer-sftp"
SFTP_UPLOAD_ACTION = "upload file"
SFTP_REMOTE_DIR = "/incoming"
MAX_SUPPORTING_EVENTS = 500

# Basic routing controls
PROCESS_LABELS = {"notable"}  # empty set means allow all labels
PROCESS_STATUSES = {"new", "open"}
PROCESS_SEVERITIES = {"medium", "high", "critical"}  # empty set means allow all


def on_start(container):
    """Playbook entry point.

    Args:
        container: Phantom container dictionary.
    """
    phantom.debug("Starting Phantom notable->analyzer playbook")

    if not _should_process_container(container):
        phantom.debug("Container did not meet processing gates; skipping")
        return

    notable = _extract_notable_fields(container)
    supporting_events = _collect_supporting_events(container)
    payload = _build_payload(notable, container, supporting_events)

    local_path, remote_file_name = _write_payload_to_temp_file(payload)
    if not local_path:
        phantom.error("Failed to write payload file; aborting")
        return

    success, message, vault_id = phantom.vault_add(
        container=container, file_location=local_path, file_name=remote_file_name
    )
    if not success:
        phantom.error("vault_add failed: {}".format(message))
        return

    # NOTE:
    # Parameter names vary by SFTP app. Validate the required parameter keys
    # for your installed app and adjust this dict accordingly.
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
        name="send_notable_to_analyzer",
    )


def on_finish(container, summary):
    """Playbook completion hook.

    Args:
        container: Phantom container dictionary.
        summary: Phantom playbook summary payload.
    """
    phantom.debug("Finished Phantom notable->analyzer playbook")
    return


def _should_process_container(container):
    """Apply routing gates to decide whether a container should be processed.

    Args:
        container: Phantom container dictionary.

    Returns:
        True when label/status/severity gates pass.
    """
    label = (container.get("label") or "").lower()
    status = (container.get("status") or "").lower()
    severity = (container.get("severity") or "").lower()

    if PROCESS_LABELS and label not in PROCESS_LABELS:
        return False
    if PROCESS_STATUSES and status not in PROCESS_STATUSES:
        return False
    if PROCESS_SEVERITIES and severity and severity not in PROCESS_SEVERITIES:
        return False

    return True


def _extract_notable_fields(container):
    """Extract common notable-level fields from the SOAR container.

    Args:
        container: Phantom container dictionary.

    Returns:
        Flat notable metadata dictionary used by payload building.
    """
    return {
        "container_id": str(container.get("id", "")),
        "name": container.get("name") or "",
        "description": container.get("description") or "",
        "severity": container.get("severity") or "",
        "status": container.get("status") or "",
        "label": container.get("label") or "",
        "source_data_identifier": str(container.get("source_data_identifier") or ""),
        "create_time": container.get("create_time") or "",
    }


def _collect_supporting_events(container):
    """Collect supporting artifact rows for context.

    Args:
        container: Phantom container dictionary.

    Returns:
        List of normalized supporting event records.
    """
    rows = phantom.collect2(
        container=container,
        datapath=["artifact:*.id", "artifact:*.name", "artifact:*.cef"],
        limit=MAX_SUPPORTING_EVENTS,
    )

    events = []
    for row in rows:
        artifact_id = row[0]
        artifact_name = row[1]
        cef = row[2] or {}
        if not isinstance(cef, dict):
            cef = {"cef_raw": str(cef)}

        event = {
            "artifact_id": artifact_id,
            "artifact_name": artifact_name,
            "cef": cef,
        }
        events.append(event)

    return events


def _build_payload(notable, container, supporting_events):
    """Build analyzer-compatible payload.

    Args:
        notable: Normalized notable metadata.
        container: Full Phantom container dictionary.
        supporting_events: Structured supporting event records.

    Returns:
        JSON-serializable payload dictionary.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    # Identifier selection strategy:
    # 1) SOAR source_data_identifier (often maps to upstream event/notable id)
    # 2) container id
    finding_id = notable["source_data_identifier"] or notable["container_id"] or "unknown"
    finding_id = _safe_filename(finding_id)

    # Keep the payload format-agnostic: raw container + normalized notable metadata.
    # The analyzer now consumes arbitrary JSON/text and does not require PoC fields.
    payload = {
        "finding_id": finding_id,
        "ingest_source": "splunk_soar_phantom",
        "captured_at": now_iso,
        "notable": notable,
        "container": container,
        "supporting_events": supporting_events,
    }

    return payload


def _write_payload_to_temp_file(payload):
    """Write payload JSON to local temp file.

    Args:
        payload: JSON-serializable payload dictionary.

    Returns:
        Tuple of `(local_path, remote_file_name)` on success; `(None, None)` on
        write failure.
    """
    finding_id = _safe_filename(payload.get("finding_id", "unknown"))
    remote_file_name = "{}.json".format(finding_id)

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


def _safe_filename(value):
    """Sanitize identifier text for safe filename usage.

    Args:
        value: Raw identifier value.

    Returns:
        ASCII-safe identifier capped to 100 characters.
    """
    value = str(value or "unknown")
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value)
    return safe[:100] or "unknown"


def _upload_done(action, success, container, results, handle):
    """Handle callback after SFTP upload action finishes.

    Args:
        action: Phantom action name.
        success: Whether the action succeeded.
        container: Phantom container dictionary.
        results: Action results payload.
        handle: Phantom callback handle.

    Returns:
        None.
    """
    if success:
        phantom.debug("Uploaded notable payload to analyzer incoming directory")
        phantom.add_note(
            container=container,
            title="Sent to notable analyzer",
            content="SOAR playbook uploaded notable payload for analyzer processing.",
            note_type="general",
        )
    else:
        phantom.error("SFTP upload action failed")
