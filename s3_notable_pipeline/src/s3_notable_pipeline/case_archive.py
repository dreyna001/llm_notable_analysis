"""Case archive writer for the AWS notable pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any

from .config import Config
from .verdicts import normalize_verdict

FINDING_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
IDENTIFIER_FIELDS = ("finding_id", "notable_id", "sid")
CORRELATION_FIELDS = ("correlation_id", "correlationId", "event_id")


@dataclass(frozen=True)
class SourceContext:
    """Source alert context needed to write a case archive envelope."""

    input_bucket: str
    input_key: str
    source_filename: str
    content_type: str
    was_compressed: bool


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
    lambda_client: Any | None = None,
    processed_at: datetime | str | None = None,
) -> ArchiveWriteResult:
    """Write a canonical S3 case envelope and DynamoDB CaseIndex row."""

    if not config.CASE_ARCHIVE_ENABLED:
        return ArchiveWriteResult(status="skipped", message="case archive disabled")

    processed_at_dt = _coerce_utc_datetime(processed_at)
    expires_at_dt = processed_at_dt + timedelta(days=config.CASE_RETENTION_DAYS)
    alert_payload = analysis_result.get("alert_payload")
    analysis = analysis_result.get("llm_response")
    finding_id = _resolve_finding_id(alert_payload, source.input_key)
    case_id = _build_case_id(finding_id)
    correlation_id = _extract_first_string(alert_payload, CORRELATION_FIELDS)
    source_completeness, archived_alert, archived_analysis = _bounded_archive_values(
        alert_payload=alert_payload,
        analysis=analysis,
        config=config,
    )
    artifacts = _extract_artifact_keys(sink_result)
    retrieval_status = "pending" if config.CASE_QA_ENABLED else "not_indexed"
    envelope_key = _build_envelope_key(config, processed_at_dt, case_id)

    existing_item = _get_case_index_item(dynamodb_client, config.CASE_INDEX_TABLE, case_id)
    if existing_item:
        if not _identity_matches(
            existing_item,
            source_filename=source.source_filename,
            correlation_id=correlation_id,
            finding_id=finding_id,
        ):
            return ArchiveWriteResult(
                status="skipped",
                case_id=case_id,
                message="case identity collision suppressed",
            )
        return ArchiveWriteResult(
            status="success",
            case_id=case_id,
            case_envelope_key=str(existing_item.get("case_envelope_key", envelope_key)),
            retrieval_status=str(existing_item.get("retrieval_status", retrieval_status)),
            source_completeness=str(
                existing_item.get("source_completeness", source_completeness)
            ),
            message="case archive replay matched existing identity",
        )

    envelope = {
        "case_schema_version": config.CASE_SCHEMA_VERSION,
        "analysis_schema_version": config.CASE_ANALYSIS_SCHEMA_VERSION,
        "case_id": case_id,
        "finding_id": finding_id,
        "source": {
            "input_bucket": source.input_bucket,
            "input_key": source.input_key,
            "source_filename": source.source_filename,
            "content_type": source.content_type,
            "was_compressed": source.was_compressed,
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
        },
        "alert_payload": archived_alert,
        "analysis": archived_analysis,
    }

    s3_client.put_object(
        Bucket=config.CASE_ARCHIVE_BUCKET,
        Key=envelope_key,
        Body=json.dumps(envelope, ensure_ascii=False, default=str).encode("utf-8"),
        ContentType="application/json",
    )
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
    try:
        dynamodb_client.put_item(
            TableName=config.CASE_INDEX_TABLE,
            Item=_to_ddb_item(_prepare_case_index_attributes(item)),
            ConditionExpression="attribute_not_exists(case_id)",
        )
    except Exception as exc:
        if not _is_conditional_check_failed(exc):
            raise
        existing_item = _get_case_index_item(dynamodb_client, config.CASE_INDEX_TABLE, case_id)
        if existing_item and _identity_matches(
            existing_item,
            source_filename=source.source_filename,
            correlation_id=correlation_id,
            finding_id=finding_id,
        ):
            return ArchiveWriteResult(
                status="success",
                case_id=case_id,
                case_envelope_key=str(existing_item.get("case_envelope_key", envelope_key)),
                retrieval_status=str(existing_item.get("retrieval_status", retrieval_status)),
                source_completeness=str(
                    existing_item.get("source_completeness", source_completeness)
                ),
                message="case archive replay matched existing identity",
            )
        return ArchiveWriteResult(
            status="skipped",
            case_id=case_id,
            case_envelope_key=envelope_key,
            message="case identity collision suppressed",
        )

    _invoke_embed_lambda(
        config=config,
        lambda_client=lambda_client,
        case_id=case_id,
        envelope_bucket=config.CASE_ARCHIVE_BUCKET,
        envelope_key=envelope_key,
    )
    return ArchiveWriteResult(
        status="success",
        case_id=case_id,
        case_envelope_key=envelope_key,
        retrieval_status=retrieval_status,
        source_completeness=source_completeness,
    )


def _invoke_embed_lambda(
    *,
    config: Config,
    lambda_client: Any | None,
    case_id: str,
    envelope_bucket: str,
    envelope_key: str,
) -> None:
    if not config.CASE_QA_ENABLED:
        return
    if lambda_client is None:
        raise ValueError("lambda_client is required when Case Q&A embedding is enabled")
    payload = {
        "case_id": case_id,
        "case_envelope_bucket": envelope_bucket,
        "case_envelope_key": envelope_key,
    }
    lambda_client.invoke(
        FunctionName=config.CASE_EMBED_LAMBDA_NAME,
        InvocationType="Event",
        Payload=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
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


def _build_envelope_key(config: Config, processed_at: datetime, case_id: str) -> str:
    return (
        f"{config.CASE_ARCHIVE_PREFIX}/"
        f"{processed_at.year:04d}/{processed_at.month:02d}/{processed_at.day:02d}/"
        f"{case_id}.json"
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
    source_filename: str,
    correlation_id: str,
    finding_id: str,
) -> bool:
    if str(item.get("source_filename", "")) == source_filename:
        return True
    if correlation_id and str(item.get("correlation_id", "")) == correlation_id:
        return True
    if finding_id and str(item.get("finding_id", "")) == finding_id:
        return True
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
