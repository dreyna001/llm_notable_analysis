"""
Template Splunk SOAR (Phantom) playbook:
Send one notable + supporting events to s3_notable_pipeline via S3 object upload.

This is a baseline template with placeholder AWS/S3 values. Update constants
and action parameter keys to match your SOAR AWS S3 app integration.
"""

import json
import os
import tempfile
from datetime import datetime, timezone

import phantom.rules as phantom


# ---------------------------------------------------------------------------
# Operator-tunable placeholders
# ---------------------------------------------------------------------------
AWS_S3_ASSET_NAME = "aws-s3-placeholder"
S3_PUT_ACTION = "put object"  # Placeholder action name; confirm in your SOAR app
INPUT_BUCKET_NAME = "REPLACE_WITH_INPUT_BUCKET_NAME"
INPUT_PREFIX = "incoming"
MAX_SUPPORTING_EVENTS = 200

# Basic routing controls
PROCESS_LABELS = {"notable"}  # Empty set means allow all labels
PROCESS_STATUSES = {"new", "open"}
PROCESS_SEVERITIES = {"medium", "high", "critical"}  # Empty set means allow all


def on_start(container):
    """Playbook entry point."""
    phantom.debug("Starting Phantom notable->S3 playbook")

    if not _should_process_container(container):
        phantom.debug("Container did not meet processing gates; skipping")
        return

    notable = _extract_notable_fields(container)
    supporting_events, supporting_event_summaries = _collect_supporting_events(container)
    payload = _build_payload(notable, container, supporting_events, supporting_event_summaries)

    local_path, finding_id = _write_payload_to_temp_file(payload)
    if not local_path:
        phantom.error("Failed to write payload file; aborting")
        return

    s3_key = _build_s3_key(finding_id)

    success, message, vault_id = phantom.vault_add(
        container=container, file_location=local_path, file_name=os.path.basename(local_path)
    )
    if not success:
        phantom.error("vault_add failed: {}".format(message))
        return

    # NOTE:
    # AWS S3 app action parameter names vary by app version/vendor.
    # Replace keys below with your app's required params.
    params = [
        {
            "bucket": INPUT_BUCKET_NAME,
            "key": s3_key,
            "vault_id": vault_id,
        }
    ]

    phantom.act(
        action=S3_PUT_ACTION,
        parameters=params,
        assets=[AWS_S3_ASSET_NAME],
        callback=_put_object_done,
        name="write_notable_to_s3_incoming",
    )


def on_finish(container, summary):
    """Playbook completion hook."""
    phantom.debug("Finished Phantom notable->S3 playbook")
    return


def _should_process_container(container):
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
    rows = phantom.collect2(
        container=container,
        datapath=["artifact:*.id", "artifact:*.name", "artifact:*.cef"],
        limit=MAX_SUPPORTING_EVENTS,
    )

    events = []
    summaries = []
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
        summaries.append(json.dumps(cef, sort_keys=True, ensure_ascii=True))

    return events, summaries


def _build_payload(notable, container, supporting_events, supporting_event_summaries):
    now_iso = datetime.now(timezone.utc).isoformat()

    finding_id = notable["source_data_identifier"] or notable["container_id"] or "unknown"
    finding_id = _safe_filename(finding_id)
    summary = notable["description"] or notable["name"] or "SOAR notable"

    payload = {
        "summary": summary,
        "notable_id": notable["container_id"],
        "event_id": notable["source_data_identifier"] or notable["container_id"],
        "finding_id": finding_id,
        "search_name": notable["name"] or "SOAR notable",
        "risk_score": notable["severity"] or "N/A",
        "threat_category": "N/A",
        "alert_time": notable["create_time"] or now_iso,
        "supporting_events": supporting_event_summaries,
    }

    payload["raw_event"] = json.dumps(
        {
            "container": container,
            "supporting_events": supporting_events,
        },
        default=str,
        ensure_ascii=True,
    )

    return payload


def _write_payload_to_temp_file(payload):
    finding_id = _safe_filename(payload.get("finding_id", "unknown"))

    fd, tmp_path = tempfile.mkstemp(prefix="notable_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2)
        return tmp_path, finding_id
    except Exception:
        try:
            os.close(fd)
        except Exception:
            pass
        return None, None


def _build_s3_key(finding_id):
    return "{}/{}.json".format(INPUT_PREFIX.strip("/"), finding_id)


def _safe_filename(value):
    value = str(value or "unknown")
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value)
    return safe[:100] or "unknown"


def _put_object_done(action, success, container, results, handle):
    if success:
        phantom.debug("Uploaded notable payload object to S3 incoming prefix")
        phantom.add_note(
            container=container,
            title="Sent to S3 notable pipeline",
            content="SOAR playbook uploaded notable payload object to S3 incoming prefix.",
            note_type="general",
        )
    else:
        phantom.error("S3 put-object action failed")
