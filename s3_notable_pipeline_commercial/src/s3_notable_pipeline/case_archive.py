"""Case archive writer for the AWS notable pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from uuid import uuid4
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any

from .config import Config
from .verdicts import normalize_verdict

FINDING_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
IDENTIFIER_FIELDS = ("finding_id", "notable_id", "sid")
CORRELATION_FIELDS = ("correlation_id", "correlationId", "event_id")


class CaseEnvelopeMismatchError(ValueError):
    """Existing case envelope content does not match the intended payload."""


@dataclass(frozen=True)
class SourceContext:
    """Source alert context needed to write a case archive envelope."""

    input_bucket: str
    input_key: str
    source_filename: str
    content_type: str
    was_compressed: bool
    source_version_id: str = ""
    source_etag: str = ""
    source_sequencer: str = ""
    processing_id: str = ""


@dataclass(frozen=True)
class ArchiveWriteResult:
    """Result of one case archive write attempt."""

    status: str
    case_id: str = ""
    case_envelope_key: str = ""
    retrieval_status: str = ""
    source_completeness: str = ""
    message: str = ""


def archive_case(
    *,
    analysis_result: dict[str, Any],
    config: Config,
    source: SourceContext,
    sink_result: dict[str, Any],
    s3_client: Any,
    dynamodb_client: Any,
    sqs_client: Any | None = None,
    lambda_client: Any | None = None,
    processed_at: datetime | str | None = None,
) -> ArchiveWriteResult:
    """Claim one immutable run, write its envelope, then publish latest atomically."""

    if not config.CASE_ARCHIVE_ENABLED:
        return ArchiveWriteResult(status="skipped", message="case archive disabled")

    processed_at_dt = _coerce_utc_datetime(processed_at)
    expires_at_dt = processed_at_dt + timedelta(days=config.CASE_RETENTION_DAYS)
    alert_payload = analysis_result.get("alert_payload")
    analysis = analysis_result.get("llm_response")
    finding_id = _resolve_finding_id(alert_payload, source.input_key)
    case_id = _build_case_id(finding_id)
    processing_id = source.processing_id or _build_processing_id(source)
    run_id = _build_run_id(finding_id, processing_id)
    correlation_id = _extract_first_string(alert_payload, CORRELATION_FIELDS)
    source_completeness, archived_alert, archived_analysis = _bounded_archive_values(
        alert_payload=alert_payload,
        analysis=analysis,
        config=config,
    )
    artifacts = _extract_artifact_keys(sink_result)
    retrieval_status = "pending" if config.CASE_QA_ENABLED else "not_indexed"
    envelope_key = _build_envelope_key(config, processed_at_dt, case_id, run_id, bool(source.processing_id))

    envelope = {
        "case_schema_version": config.CASE_SCHEMA_VERSION,
        "analysis_schema_version": config.CASE_ANALYSIS_SCHEMA_VERSION,
        "case_id": case_id,
        "run_id": run_id,
        "finding_id": finding_id,
        "source": {
            "input_bucket": source.input_bucket,
            "input_key": source.input_key,
            "source_filename": source.source_filename,
            "content_type": source.content_type,
            "was_compressed": source.was_compressed,
            "version_id": source.source_version_id,
            "etag": source.source_etag,
            "sequencer": source.source_sequencer,
            "processing_id": processing_id,
        },
        "processed_at": _format_utc(processed_at_dt),
        "expires_at": _format_utc(expires_at_dt),
        "correlation_id": correlation_id,
        "capability_snapshot": _capability_snapshot(config),
        "artifacts": artifacts,
        "archive_metadata": {
            "source_completeness": source_completeness,
            "retrieval_status": retrieval_status,
            "archive_failure_mode": config.CASE_ARCHIVE_FAILURE_MODE,
            "analysis_status": _analysis_status(analysis),
        },
        "alert_payload": archived_alert,
        "analysis": archived_analysis,
    }
    envelope_body = _encode_envelope(envelope)

    existing_item = _get_case_index_item(dynamodb_client, config.CASE_INDEX_TABLE, case_id)
    if existing_item:
        if not _identity_matches(
            existing_item,
            source_key=source.input_key,
            correlation_id=correlation_id,
            finding_id=finding_id,
        ):
            return ArchiveWriteResult(
                status="skipped",
                case_id=case_id,
                message="case identity collision suppressed",
            )
        existing_run = existing_item.get(_run_attribute_name(run_id))
        if isinstance(existing_run, dict):
            run_state = str(existing_run.get("state", "")).strip()
            if run_state == "completed":
                _republish_pending_embed(
                    config=config,
                    item=existing_item,
                    run=existing_run,
                    sqs_client=sqs_client,
                    lambda_client=lambda_client,
                )
                return _run_result_from_item(existing_item, existing_run, retrieval_status, source_completeness)
            if run_state == "claimed":
                return _recover_claimed_run(
                    config=config,
                    case_id=case_id,
                    run_id=run_id,
                    run_attribute=_run_attribute_name(run_id),
                    existing_item=existing_item,
                    existing_run=existing_run,
                    envelope_key=envelope_key,
                    envelope_body=envelope_body,
                    processed_at_dt=processed_at_dt,
                    retrieval_status=retrieval_status,
                    source_completeness=source_completeness,
                    s3_client=s3_client,
                    dynamodb_client=dynamodb_client,
                    sqs_client=sqs_client,
                    lambda_client=lambda_client,
                )
            return ArchiveWriteResult(
                status="skipped",
                case_id=case_id,
                case_envelope_key=str(existing_run.get("envelope_key", envelope_key)),
                retrieval_status=retrieval_status,
                source_completeness=source_completeness,
                message="case run is already claimed",
            )
        # Keep legacy rows replay-safe when they predate immutable run metadata.
        if not source.processing_id:
            _republish_pending_embed(
                config=config,
                item=existing_item,
                run={},
                sqs_client=sqs_client,
                lambda_client=lambda_client,
            )
            return ArchiveWriteResult(
                status="success",
                case_id=case_id,
                case_envelope_key=str(existing_item.get("case_envelope_key", envelope_key)),
                retrieval_status=str(existing_item.get("retrieval_status", retrieval_status)),
                source_completeness=str(existing_item.get("source_completeness", source_completeness)),
                message="case archive replay matched existing identity",
            )

    run_fencing_token = uuid4().hex
    item = _build_case_index_item(
        config=config,
        case_id=case_id,
        finding_id=finding_id,
        source=source,
        envelope_key=envelope_key,
        artifacts=artifacts,
        processed_at=processed_at_dt,
        expires_at=expires_at_dt,
        correlation_id=correlation_id,
        source_completeness=source_completeness,
        retrieval_status=retrieval_status,
        analysis=analysis,
        alert_payload=alert_payload,
    )
    run_attribute = _run_attribute_name(run_id)
    run_record = {
        "run_id": run_id,
        "processing_id": processing_id,
        "state": "claimed",
        "fencing_token": run_fencing_token,
        "envelope_key": envelope_key,
        "claimed_at": _format_utc(processed_at_dt),
        "source_key": source.input_key,
    }
    item[run_attribute] = run_record
    item.pop("case_envelope_key", None)
    if not source.processing_id:
        # Preserve the pre-run contract for direct archive callers without S3 identity.
        item["case_envelope_key"] = envelope_key
    try:
        if existing_item:
            dynamodb_client.update_item(
                TableName=config.CASE_INDEX_TABLE,
                Key={"case_id": {"S": case_id}},
                UpdateExpression="SET #run = :run",
                ConditionExpression="attribute_not_exists(#run)",
                ExpressionAttributeNames={"#run": run_attribute},
                ExpressionAttributeValues={":run": _to_ddb_value(run_record)},
            )
        else:
            dynamodb_client.put_item(
                TableName=config.CASE_INDEX_TABLE,
                Item=_to_ddb_item(_prepare_case_index_attributes(item)),
                ConditionExpression="attribute_not_exists(case_id)",
            )
    except Exception as exc:
        if not _is_conditional_check_failed(exc):
            raise
        existing_item = _get_case_index_item(dynamodb_client, config.CASE_INDEX_TABLE, case_id)
        existing_run = (existing_item or {}).get(run_attribute)
        if isinstance(existing_run, dict) and str(existing_run.get("state", "")) == "completed":
            _republish_pending_embed(
                config=config,
                item=existing_item or {},
                run=existing_run,
                sqs_client=sqs_client,
                lambda_client=lambda_client,
            )
            return ArchiveWriteResult(
                status="success",
                case_id=case_id,
                case_envelope_key=str(existing_run.get("envelope_key", envelope_key)),
                retrieval_status=str(existing_item.get("retrieval_status", retrieval_status)),
                source_completeness=str(existing_item.get("source_completeness", source_completeness)),
                message="case archive run replay matched existing identity",
            )
        if existing_item and _identity_matches(existing_item, source_key=source.input_key, correlation_id=correlation_id, finding_id=finding_id):
            existing_run = (existing_item or {}).get(run_attribute)
            if isinstance(existing_run, dict) and str(existing_run.get("state", "")).strip() == "claimed":
                return _recover_claimed_run(
                    config=config,
                    case_id=case_id,
                    run_id=run_id,
                    run_attribute=run_attribute,
                    existing_item=existing_item or {},
                    existing_run=existing_run,
                    envelope_key=envelope_key,
                    envelope_body=envelope_body,
                    processed_at_dt=processed_at_dt,
                    retrieval_status=retrieval_status,
                    source_completeness=source_completeness,
                    s3_client=s3_client,
                    dynamodb_client=dynamodb_client,
                    sqs_client=sqs_client,
                    lambda_client=lambda_client,
                )
            return ArchiveWriteResult(status="skipped", case_id=case_id, case_envelope_key=envelope_key, message="case run claim is already held")
        return ArchiveWriteResult(
            status="skipped",
            case_id=case_id,
            case_envelope_key=envelope_key,
            message="case identity collision suppressed",
        )

    _verify_or_write_envelope(
        s3_client=s3_client,
        bucket=config.CASE_ARCHIVE_BUCKET,
        envelope_key=envelope_key,
        envelope_body=envelope_body,
    )

    _finalize_run_and_publish_embed(
        config=config,
        dynamodb_client=dynamodb_client,
        case_id=case_id,
        run_id=run_id,
        run_attribute=run_attribute,
        run_record=run_record,
        envelope_key=envelope_key,
        processed_at_dt=processed_at_dt,
        sqs_client=sqs_client,
        lambda_client=lambda_client,
        existing_item=existing_item,
    )
    return ArchiveWriteResult(
        status="success",
        case_id=case_id,
        case_envelope_key=envelope_key,
        retrieval_status=retrieval_status,
        source_completeness=source_completeness,
    )


def _encode_envelope(envelope: dict[str, Any]) -> bytes:
    return json.dumps(envelope, ensure_ascii=False, default=str).encode("utf-8")


def _is_s3_precondition_failed(exc: Exception) -> bool:
    response = getattr(exc, "response", {})
    if isinstance(response, dict):
        error = response.get("Error", {})
        if isinstance(error, dict):
            code = str(error.get("Code", ""))
            if code in {"PreconditionFailed", "412"}:
                return True
    return exc.__class__.__name__ in {"PreconditionFailed", "PreconditionFailedException"}


def _verify_or_write_envelope(
    *,
    s3_client: Any,
    bucket: str,
    envelope_key: str,
    envelope_body: bytes,
) -> None:
    """Create the envelope once, reconciling create-only conflicts on replay."""

    try:
        s3_client.put_object(
            Bucket=bucket,
            Key=envelope_key,
            Body=envelope_body,
            ContentType="application/json",
            IfNoneMatch="*",
        )
    except Exception as exc:
        if not _is_s3_precondition_failed(exc):
            raise
        existing = s3_client.get_object(Bucket=bucket, Key=envelope_key)["Body"].read()
        if existing != envelope_body:
            raise CaseEnvelopeMismatchError(
                f"existing case envelope s3://{bucket}/{envelope_key} does not match intended content"
            )


def _finalize_run_and_publish_embed(
    *,
    config: Config,
    dynamodb_client: Any,
    case_id: str,
    run_id: str,
    run_attribute: str,
    run_record: dict[str, Any],
    envelope_key: str,
    processed_at_dt: datetime,
    sqs_client: Any | None,
    lambda_client: Any | None,
    existing_item: dict[str, Any] | None,
) -> None:
    completed_run = {**run_record, "state": "completed", "completed_at": _format_utc(processed_at_dt)}
    try:
        dynamodb_client.update_item(
            TableName=config.CASE_INDEX_TABLE,
            Key={"case_id": {"S": case_id}},
            UpdateExpression=(
                "SET #run = :run, latest_run_id = :run_id, latest_run_key = :run_key, "
                "latest_run_at = :run_at, case_envelope_key = :run_key"
            ),
            ConditionExpression="#run.#state = :claimed AND #run.#fence = :fence",
            ExpressionAttributeNames={"#run": run_attribute, "#state": "state", "#fence": "fencing_token"},
            ExpressionAttributeValues={
                ":run": _to_ddb_value(completed_run),
                ":run_id": {"S": run_id},
                ":run_key": {"S": envelope_key},
                ":run_at": {"S": _format_utc(processed_at_dt)},
                ":claimed": {"S": "claimed"},
                ":fence": {"S": str(run_record.get("fencing_token", ""))},
            },
        )
    except Exception as exc:
        if not _is_conditional_check_failed(exc):
            raise
        item = _get_case_index_item(dynamodb_client, config.CASE_INDEX_TABLE, case_id) or existing_item or {}
        run = item.get(run_attribute)
        if not isinstance(run, dict) or str(run.get("state", "")).strip() != "completed":
            raise
        _republish_pending_embed(
            config=config,
            item=item,
            run=run,
            sqs_client=sqs_client,
            lambda_client=lambda_client,
        )
        return

    _publish_embed_request(
        config=config,
        sqs_client=sqs_client,
        lambda_client=lambda_client,
        case_id=case_id,
        envelope_bucket=config.CASE_ARCHIVE_BUCKET,
        envelope_key=envelope_key,
    )


def _recover_claimed_run(
    *,
    config: Config,
    case_id: str,
    run_id: str,
    run_attribute: str,
    existing_item: dict[str, Any],
    existing_run: dict[str, Any],
    envelope_key: str,
    envelope_body: bytes,
    processed_at_dt: datetime,
    retrieval_status: str,
    source_completeness: str,
    s3_client: Any,
    dynamodb_client: Any,
    sqs_client: Any | None,
    lambda_client: Any | None,
) -> ArchiveWriteResult:
    """Reconcile a claimed run after partial envelope, finalize, or embed failures."""

    stored_key = str(existing_run.get("envelope_key", envelope_key)).strip() or envelope_key
    if stored_key != envelope_key:
        return ArchiveWriteResult(
            status="skipped",
            case_id=case_id,
            case_envelope_key=stored_key,
            message="case run claim is already held",
        )

    _verify_or_write_envelope(
        s3_client=s3_client,
        bucket=config.CASE_ARCHIVE_BUCKET,
        envelope_key=envelope_key,
        envelope_body=envelope_body,
    )
    _finalize_run_and_publish_embed(
        config=config,
        dynamodb_client=dynamodb_client,
        case_id=case_id,
        run_id=run_id,
        run_attribute=run_attribute,
        run_record=existing_run,
        envelope_key=envelope_key,
        processed_at_dt=processed_at_dt,
        sqs_client=sqs_client,
        lambda_client=lambda_client,
        existing_item=existing_item,
    )
    return ArchiveWriteResult(
        status="success",
        case_id=case_id,
        case_envelope_key=envelope_key,
        retrieval_status=retrieval_status,
        source_completeness=source_completeness,
        message="case archive claimed run replay reconciled",
    )


def _publish_embed_request(
    *,
    config: Config,
    sqs_client: Any | None,
    lambda_client: Any | None,
    case_id: str,
    envelope_bucket: str,
    envelope_key: str,
) -> None:
    if not config.CASE_QA_ENABLED:
        return
    payload = {
        "case_id": case_id,
        "case_envelope_bucket": envelope_bucket,
        "case_envelope_key": envelope_key,
    }
    if config.CASE_EMBED_QUEUE_URL:
        if sqs_client is None:
            raise ValueError("sqs_client is required when CASE_EMBED_QUEUE_URL is configured")
        sqs_client.send_message(
            QueueUrl=config.CASE_EMBED_QUEUE_URL,
            MessageBody=json.dumps(payload, separators=(",", ":"), sort_keys=True),
        )
        return
    if lambda_client is None:
        raise ValueError("lambda_client is required for legacy direct case embedding")
    lambda_client.invoke(
        FunctionName=config.CASE_EMBED_LAMBDA_NAME,
        InvocationType="Event",
        Payload=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
    )


def _republish_pending_embed(
    *,
    config: Config,
    item: dict[str, Any],
    run: dict[str, Any],
    sqs_client: Any | None,
    lambda_client: Any | None,
) -> None:
    """Repair an archive-to-embed handoff that failed after the run committed."""

    if not config.CASE_QA_ENABLED or str(item.get("retrieval_status", "")) != "pending":
        return
    envelope_key = str(run.get("envelope_key", item.get("case_envelope_key", ""))).strip()
    case_id = str(item.get("case_id", "")).strip()
    if not case_id or not envelope_key:
        raise ValueError("pending case replay is missing its case or envelope identity")
    _publish_embed_request(
        config=config,
        sqs_client=sqs_client,
        lambda_client=lambda_client,
        case_id=case_id,
        envelope_bucket=config.CASE_ARCHIVE_BUCKET,
        envelope_key=envelope_key,
    )


def _resolve_finding_id(alert_payload: Any, source_key: str) -> str:
    candidate = _extract_first_string(alert_payload, IDENTIFIER_FIELDS)
    if not candidate:
        candidate = _source_key_stem(source_key)
    return _validate_finding_id(candidate)


def _validate_finding_id(value: str) -> str:
    finding_id = str(value or "").strip()
    if not FINDING_ID_RE.fullmatch(finding_id):
        raise ValueError(
            "finding_id must be 1-128 chars using letters, digits, dot, underscore, colon, or dash"
        )
    return finding_id


def _source_key_stem(source_key: str) -> str:
    filename = PurePosixPath(source_key).name
    lower_filename = filename.lower()
    if lower_filename.endswith(".gzip"):
        filename = filename[:-5]
    elif lower_filename.endswith(".gz"):
        filename = filename[:-3]
    return filename.rsplit(".", 1)[0]


def _build_case_id(finding_id: str) -> str:
    digest = hashlib.sha256(finding_id.encode("utf-8")).hexdigest()[:16]
    return f"{finding_id}-{digest}"


def _extract_first_string(value: Any, fields: tuple[str, ...]) -> str:
    if not isinstance(value, dict):
        return ""
    for field in fields:
        candidate = value.get(field)
        if candidate is not None:
            text = str(candidate).strip()
            if text:
                return text
    return ""


def _bounded_archive_values(
    *,
    alert_payload: Any,
    analysis: Any,
    config: Config,
) -> tuple[str, Any, Any]:
    archived_alert = _bounded_value(alert_payload, config.CASE_ARCHIVE_MAX_ALERT_BYTES)
    archived_analysis = _bounded_value(analysis, config.CASE_ARCHIVE_MAX_ANALYSIS_BYTES)
    alert_missing = archived_alert is None
    analysis_missing = archived_analysis is None
    if alert_missing and analysis_missing:
        return "markdown_only", None, None
    if alert_missing:
        return "missing_alert", None, _with_normalized_verdict(archived_analysis)
    if analysis_missing:
        return "missing_analysis", archived_alert, None
    return "complete", archived_alert, _with_normalized_verdict(archived_analysis)


def _with_normalized_verdict(analysis: Any) -> Any:
    """Return analysis with a normalized alert_reconciliation.verdict when present."""
    if not isinstance(analysis, dict):
        return analysis
    stored = dict(analysis)
    reconciliation = stored.get("alert_reconciliation")
    if isinstance(reconciliation, dict):
        normalized = dict(reconciliation)
        normalized["verdict"] = normalize_verdict(reconciliation.get("verdict"))
        stored["alert_reconciliation"] = normalized
    return stored


def _bounded_value(value: Any, max_bytes: int) -> Any | None:
    try:
        encoded = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
    except (TypeError, ValueError):
        return None
    if len(encoded) > max_bytes:
        return None
    return value


def _extract_artifact_keys(sink_result: dict[str, Any]) -> dict[str, str]:
    s3_result = sink_result.get("s3_result")
    if isinstance(s3_result, dict):
        source = s3_result
    else:
        source = sink_result
    return {
        "report_markdown_key": str(source.get("markdown_key", "")),
        "report_json_key": str(source.get("json_key", "")),
        "report_html_key": str(source.get("html_key", "")),
    }


def _build_processing_id(source: SourceContext) -> str:
    material = "\x1f".join(
        (
            source.input_bucket,
            source.input_key,
            source.source_version_id or source.source_etag or "unversioned",
            source.source_etag,
            source.source_sequencer,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _build_run_id(finding_id: str, processing_id: str) -> str:
    digest = hashlib.sha256(f"{finding_id}:{processing_id}".encode("utf-8")).hexdigest()[:24]
    return f"run-{digest}"


def _run_attribute_name(run_id: str) -> str:
    return f"run_{run_id.replace('-', '_')}"


def _run_result_from_item(
    item: dict[str, Any],
    run: dict[str, Any],
    retrieval_status: str,
    source_completeness: str,
) -> ArchiveWriteResult:
    return ArchiveWriteResult(
        status="success",
        case_id=str(item.get("case_id", "")),
        case_envelope_key=str(run.get("envelope_key", item.get("case_envelope_key", ""))),
        retrieval_status=str(item.get("retrieval_status", retrieval_status)),
        source_completeness=str(item.get("source_completeness", source_completeness)),
        message="case archive run replay matched existing identity",
    )


def _build_envelope_key(
    config: Config,
    processed_at: datetime,
    case_id: str,
    run_id: str,
    immutable_run: bool = False,
) -> str:
    filename = f"{case_id}.json" if not immutable_run else f"{case_id}/{run_id}.json"
    return (
        f"{config.CASE_ARCHIVE_PREFIX}/"
        f"{processed_at.year:04d}/{processed_at.month:02d}/{processed_at.day:02d}/"
        f"{filename}"
    )


def _build_case_index_item(
    *,
    config: Config,
    case_id: str,
    finding_id: str,
    source: SourceContext,
    envelope_key: str,
    artifacts: dict[str, str],
    processed_at: datetime,
    expires_at: datetime,
    correlation_id: str,
    source_completeness: str,
    retrieval_status: str,
    analysis: Any,
    alert_payload: Any,
) -> dict[str, Any]:
    reconciliation = analysis.get("alert_reconciliation", {}) if isinstance(analysis, dict) else {}
    return {
        "case_id": case_id,
        "finding_id": finding_id,
        "archive_partition": "default",
        "processed_at": _format_utc(processed_at),
        "processed_at_case_id": f"{_format_utc(processed_at)}#{case_id}",
        "expires_at": _format_utc(expires_at),
        "expires_at_epoch": int(expires_at.timestamp()),
        "verdict": normalize_verdict(reconciliation.get("verdict")),
        "confidence": str(reconciliation.get("confidence", "unknown") or "unknown"),
        "search_name": _extract_search_name(alert_payload),
        "risk_score": _extract_risk_score(alert_payload),
        "source_filename": source.source_filename,
        "source_key": source.input_key,
        "case_envelope_key": envelope_key,
        "report_markdown_key": artifacts.get("report_markdown_key", ""),
        "report_json_key": artifacts.get("report_json_key", ""),
        "report_html_key": artifacts.get("report_html_key", ""),
        "capability_snapshot": _capability_snapshot(config),
        "source_completeness": source_completeness,
        "retrieval_status": retrieval_status,
        "correlation_id": correlation_id,
        "analysis_status": _analysis_status(analysis),
    }


def _extract_search_name(alert_payload: Any) -> str:
    if not isinstance(alert_payload, dict):
        return ""
    for field in ("search_name", "searchName", "savedsearch_name", "rule_name"):
        value = alert_payload.get(field)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _extract_risk_score(alert_payload: Any) -> str:
    if not isinstance(alert_payload, dict):
        return ""
    for field in ("risk_score", "riskScore", "urgency"):
        value = alert_payload.get(field)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _analysis_status(analysis: Any) -> str:
    if not isinstance(analysis, dict):
        return "unknown"
    metadata = analysis.get("metadata")
    if not isinstance(metadata, dict):
        return "success"
    return str(metadata.get("analysis_status", "success") or "success")


def _capability_snapshot(config: Config) -> dict[str, Any]:
    return {
        "capability_profiles": config.CAPABILITY_PROFILES,
        "case_archive_enabled": config.CASE_ARCHIVE_ENABLED,
        "portal_enabled": config.PORTAL_ENABLED,
        "case_qa_enabled": config.CASE_QA_ENABLED,
        "html_report_enabled": config.HTML_REPORT_ENABLED,
        "splunk_sink_mode": config.SPLUNK_SINK_MODE,
    }


def _identity_matches(
    item: dict[str, Any],
    *,
    source_key: str,
    correlation_id: str,
    finding_id: str,
) -> bool:
    stored_source_key = str(item.get("source_key", "")).strip()
    stored_finding_id = str(item.get("finding_id", "")).strip()
    stored_correlation_id = str(item.get("correlation_id", "")).strip()
    # finding_id is the logical-case key; source-key changes are new immutable runs.
    if stored_finding_id and finding_id:
        return stored_finding_id == finding_id
    if stored_correlation_id and correlation_id:
        return stored_correlation_id == correlation_id
    if stored_source_key and source_key:
        return stored_source_key == source_key
    return False


def _get_case_index_item(
    dynamodb_client: Any,
    table_name: str,
    case_id: str,
) -> dict[str, Any] | None:
    response = dynamodb_client.get_item(
        TableName=table_name,
        Key={"case_id": {"S": case_id}},
        ConsistentRead=True,
    )
    item = response.get("Item")
    if not item:
        return None
    return {key: _from_ddb_value(value) for key, value in item.items()}


def _prepare_case_index_attributes(item: dict[str, Any]) -> dict[str, Any]:
    """Omit empty correlation_id before PutItem (CorrelationIdIndex GSI key)."""
    if not str(item.get("correlation_id", "")).strip():
        return {key: value for key, value in item.items() if key != "correlation_id"}
    return item


def _to_ddb_item(item: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {key: _to_ddb_value(value) for key, value in item.items()}


def _to_ddb_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, int | float):
        return {"N": str(value)}
    if isinstance(value, dict):
        return {"M": {str(key): _to_ddb_value(child) for key, child in value.items()}}
    if isinstance(value, list):
        return {"L": [_to_ddb_value(child) for child in value]}
    if value is None:
        return {"NULL": True}
    return {"S": str(value)}


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


def _is_conditional_check_failed(exc: Exception) -> bool:
    response = getattr(exc, "response", {})
    if isinstance(response, dict):
        error = response.get("Error", {})
        if isinstance(error, dict) and error.get("Code") == "ConditionalCheckFailedException":
            return True
    return exc.__class__.__name__ == "ConditionalCheckFailedException"


def _coerce_utc_datetime(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    text = str(value).strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
