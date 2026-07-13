"""Canonical case archive orchestration over native Blob and Cosmos boundaries."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any

from .blob_store import write_blob
from .config import Config
from .cosmos_store import CosmosStore
from .verdicts import normalize_verdict

FINDING_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
IDENTIFIER_FIELDS = ("finding_id", "notable_id", "sid")
CORRELATION_FIELDS = ("correlation_id", "correlationId", "event_id")


@dataclass(frozen=True)
class SourceContext:
    """Source alert context retained in the durable legacy envelope schema."""

    input_bucket: str
    input_key: str
    source_filename: str
    content_type: str
    was_compressed: bool


@dataclass(frozen=True)
class ArchiveWriteResult:
    """Result of one idempotent case archive attempt."""

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
    blob_store: Any | None = None,
    cosmos: CosmosStore | Any | None = None,
    processed_at: datetime | str | None = None,
) -> ArchiveWriteResult:
    """Write a bounded case envelope and conditionally create its Cosmos index."""

    if not config.CASE_ARCHIVE_ENABLED:
        return ArchiveWriteResult(status="skipped", message="case archive disabled")
    store = cosmos or CosmosStore.from_config(config)
    processed = _coerce_utc_datetime(processed_at)
    expires = processed + timedelta(days=config.CASE_RETENTION_DAYS)
    alert_payload = analysis_result.get("alert_payload")
    analysis = analysis_result.get("llm_response")
    finding_id = _resolve_finding_id(alert_payload, source.input_key)
    case_id = _build_case_id(finding_id)
    correlation_id = _extract_first_string(alert_payload, CORRELATION_FIELDS)
    completeness, archived_alert, archived_analysis = _bounded_archive_values(
        alert_payload=alert_payload,
        analysis=analysis,
        config=config,
    )
    artifacts = _extract_artifact_keys(sink_result)
    retrieval_status = "pending" if config.CASE_QA_ENABLED else "not_indexed"
    envelope_key = _build_envelope_key(config, processed, case_id)

    existing = store.get_case(config.CASE_INDEX_CONTAINER, case_id)
    if existing:
        return _replay_result(
            existing,
            case_id=case_id,
            envelope_key=envelope_key,
            retrieval_status=retrieval_status,
            source_completeness=completeness,
            source=source,
            correlation_id=correlation_id,
            finding_id=finding_id,
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
        "processed_at": _format_utc(processed),
        "expires_at": _format_utc(expires),
        "correlation_id": correlation_id,
        "capability_snapshot": _capability_snapshot(config),
        "artifacts": artifacts,
        "archive_metadata": {
            "source_completeness": completeness,
            "retrieval_status": retrieval_status,
            "archive_failure_mode": config.CASE_ARCHIVE_FAILURE_MODE,
        },
        "alert_payload": archived_alert,
        "analysis": archived_analysis,
    }
    write_blob(
        config.CASE_ARCHIVE_CONTAINER,
        envelope_key,
        json.dumps(envelope, ensure_ascii=False, default=str).encode("utf-8"),
        content_type="application/json",
        overwrite=True,
        store=blob_store,
    )
    item = _build_case_index_item(
        config=config,
        case_id=case_id,
        finding_id=finding_id,
        source=source,
        envelope_key=envelope_key,
        artifacts=artifacts,
        processed_at=processed,
        expires_at=expires,
        correlation_id=correlation_id,
        source_completeness=completeness,
        retrieval_status=retrieval_status,
        analysis=analysis,
        alert_payload=alert_payload,
    )
    outcome = store.create_case_if_absent(config.CASE_INDEX_CONTAINER, item)
    if not outcome.created:
        existing = store.get_case(config.CASE_INDEX_CONTAINER, case_id)
        if existing:
            return _replay_result(
                existing,
                case_id=case_id,
                envelope_key=envelope_key,
                retrieval_status=retrieval_status,
                source_completeness=completeness,
                source=source,
                correlation_id=correlation_id,
                finding_id=finding_id,
            )
        raise RuntimeError("case index create conflicted but the item could not be read")
    return ArchiveWriteResult(
        status="success",
        case_id=case_id,
        case_envelope_key=envelope_key,
        retrieval_status=retrieval_status,
        source_completeness=completeness,
    )


def _replay_result(
    item: dict[str, Any],
    *,
    case_id: str,
    envelope_key: str,
    retrieval_status: str,
    source_completeness: str,
    source: SourceContext,
    correlation_id: str,
    finding_id: str,
) -> ArchiveWriteResult:
    if not _identity_matches(
        item,
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
        case_envelope_key=str(item.get("case_envelope_key", envelope_key)),
        retrieval_status=str(item.get("retrieval_status", retrieval_status)),
        source_completeness=str(item.get("source_completeness", source_completeness)),
        message="case archive replay matched existing identity",
    )


def _resolve_finding_id(alert_payload: Any, source_key: str) -> str:
    candidate = _extract_first_string(alert_payload, IDENTIFIER_FIELDS)
    if not candidate:
        filename = PurePosixPath(source_key).name
        lower = filename.lower()
        if lower.endswith(".gzip"):
            filename = filename[:-5]
        elif lower.endswith(".gz"):
            filename = filename[:-3]
        candidate = filename.rsplit(".", 1)[0]
    finding_id = str(candidate or "").strip()
    if not FINDING_ID_RE.fullmatch(finding_id):
        raise ValueError(
            "finding_id must be 1-128 chars using letters, digits, dot, underscore, colon, or dash"
        )
    return finding_id


def _build_case_id(finding_id: str) -> str:
    digest = hashlib.sha256(finding_id.encode("utf-8")).hexdigest()[:16]
    return f"{finding_id}-{digest}"


def _extract_first_string(value: Any, fields: tuple[str, ...]) -> str:
    if not isinstance(value, dict):
        return ""
    for field in fields:
        candidate = value.get(field)
        if candidate is not None and str(candidate).strip():
            return str(candidate).strip()
    return ""


def _bounded_archive_values(
    *, alert_payload: Any, analysis: Any, config: Config
) -> tuple[str, Any, Any]:
    archived_alert = _bounded_value(alert_payload, config.CASE_ARCHIVE_MAX_ALERT_BYTES)
    archived_analysis = _bounded_value(analysis, config.CASE_ARCHIVE_MAX_ANALYSIS_BYTES)
    if archived_alert is None and archived_analysis is None:
        return "markdown_only", None, None
    if archived_alert is None:
        return "missing_alert", None, _with_normalized_verdict(archived_analysis)
    if archived_analysis is None:
        return "missing_analysis", archived_alert, None
    return "complete", archived_alert, _with_normalized_verdict(archived_analysis)


def _bounded_value(value: Any, max_bytes: int) -> Any | None:
    try:
        encoded = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return value if len(encoded) <= max_bytes else None


def _with_normalized_verdict(analysis: Any) -> Any:
    if not isinstance(analysis, dict):
        return analysis
    stored = dict(analysis)
    reconciliation = stored.get("alert_reconciliation")
    if isinstance(reconciliation, dict):
        normalized = dict(reconciliation)
        normalized["verdict"] = normalize_verdict(reconciliation.get("verdict"))
        stored["alert_reconciliation"] = normalized
    return stored


def _extract_artifact_keys(sink_result: dict[str, Any]) -> dict[str, str]:
    blob_result = sink_result.get("blob_result")
    source = blob_result if isinstance(blob_result, dict) else sink_result
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
    item = {
        "case_id": case_id,
        "finding_id": finding_id,
        "processed_at": _format_utc(processed_at),
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
    }
    if correlation_id:
        item["correlation_id"] = correlation_id
    return item


def _extract_search_name(alert_payload: Any) -> str:
    return _extract_first_string(
        alert_payload, ("search_name", "searchName", "savedsearch_name", "rule_name")
    )


def _extract_risk_score(alert_payload: Any) -> str:
    return _extract_first_string(alert_payload, ("risk_score", "riskScore", "urgency"))


def _capability_snapshot(config: Config) -> dict[str, Any]:
    return {
        "capability_profiles": config.CAPABILITY_PROFILES,
        "case_archive_enabled": config.CASE_ARCHIVE_ENABLED,
        "portal_enabled": config.PORTAL_ENABLED,
        "case_qa_enabled": config.CASE_QA_ENABLED,
        "html_report_enabled": config.HTML_REPORT_ENABLED,
        "splunk_sink_mode": config.REPORT_SINK_MODE,
    }


def _identity_matches(
    item: dict[str, Any], *, source_filename: str, correlation_id: str, finding_id: str
) -> bool:
    return bool(
        str(item.get("source_filename", "")) == source_filename
        or (correlation_id and str(item.get("correlation_id", "")) == correlation_id)
        or (finding_id and str(item.get("finding_id", "")) == finding_id)
    )


def _coerce_utc_datetime(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = ["ArchiveWriteResult", "SourceContext", "archive_case"]
