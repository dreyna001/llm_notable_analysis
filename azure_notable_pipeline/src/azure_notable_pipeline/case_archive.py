"""Canonical case archive orchestration over native Blob and Cosmos boundaries."""

from __future__ import annotations

import hashlib
import json
import re
from uuid import uuid4
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
    source_version_id: str = ""
    source_etag: str = ""
    processing_id: str = ""


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
    """Claim, write, and publish one immutable case run."""

    if not config.CASE_ARCHIVE_ENABLED:
        return ArchiveWriteResult(status="skipped", message="case archive disabled")
    store = cosmos or CosmosStore.from_config(config)
    processed = _coerce_utc_datetime(processed_at)
    expires = processed + timedelta(days=config.CASE_RETENTION_DAYS)
    alert_payload = analysis_result.get("alert_payload")
    analysis = analysis_result.get("llm_response")
    finding_id = _resolve_finding_id(
        alert_payload,
        source.input_key,
        source_bucket=source.input_bucket,
    )
    case_id = _build_case_id(finding_id)
    processing_id = source.processing_id or _build_processing_id(source)
    immutable_run = bool(source.source_etag or source.processing_id or source.source_version_id)
    run_id = _build_run_id(finding_id, processing_id)
    correlation_id = _extract_first_string(alert_payload, CORRELATION_FIELDS)
    completeness, archived_alert, archived_analysis = _bounded_archive_values(
        alert_payload=alert_payload,
        analysis=analysis,
        config=config,
    )
    artifacts = _extract_artifact_keys(sink_result)
    retrieval_status = "pending" if config.CASE_QA_ENABLED else "not_indexed"
    envelope_key = _build_envelope_key(config, processed, case_id, run_id, immutable_run)

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
            "processing_id": processing_id,
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
    item["processing_id"] = processing_id
    if not immutable_run:
        write_blob(
            config.CASE_ARCHIVE_CONTAINER,
            envelope_key,
            json.dumps(envelope, ensure_ascii=False, default=str).encode("utf-8"),
            content_type="application/json",
            overwrite=True,
            store=blob_store,
        )
        outcome = store.create_case_if_absent(config.CASE_INDEX_CONTAINER, item)
        if not outcome.created:
            winner = store.get_case(config.CASE_INDEX_CONTAINER, case_id)
            if winner:
                return _replay_result(
                    winner,
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
    existing_run = _run_from_item(existing, run_id) if existing else None
    if existing_run is not None:
        if str(existing_run.get("state")) == "completed":
            return _run_result(existing, existing_run, retrieval_status, completeness)
        return ArchiveWriteResult(
            status="skipped",
            case_id=case_id,
            case_envelope_key=str(existing_run.get("envelope_key") or envelope_key),
            message="case run is already claimed",
        )
    if existing and not immutable_run:
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
    run_record = {
        "run_id": run_id,
        "processing_id": processing_id,
        "state": "claimed",
        "fencing_token": uuid4().hex,
        "envelope_key": envelope_key,
        "claimed_at": _format_utc(processed),
        "source_key": source.input_key,
    }
    item["runs"] = {run_id: run_record}
    item.pop("case_envelope_key", None)
    if not existing:
        outcome = store.create_case_if_absent(config.CASE_INDEX_CONTAINER, item)
        if not outcome.created:
            winner = store.get_case(config.CASE_INDEX_CONTAINER, case_id)
            winner_run = _run_from_item(winner, run_id) if winner else None
            if winner_run and str(winner_run.get("state")) == "completed":
                return _run_result(winner, winner_run, retrieval_status, completeness)
            if winner and immutable_run:
                claimed = _claim_run(store, config, winner, run_id, run_record)
                if claimed is None:
                    return ArchiveWriteResult(status="skipped", case_id=case_id, case_envelope_key=envelope_key, message="case run claim is already held")
                existing = claimed
            else:
                raise RuntimeError("case index create conflicted but the item could not be read")
    elif immutable_run:
        existing = _claim_run(store, config, existing, run_id, run_record)
        if existing is None:
            return ArchiveWriteResult(status="skipped", case_id=case_id, case_envelope_key=envelope_key, message="case run claim is already held")
    write_blob(
        config.CASE_ARCHIVE_CONTAINER,
        envelope_key,
        json.dumps(envelope, ensure_ascii=False, default=str).encode("utf-8"),
        content_type="application/json",
        overwrite=not immutable_run,
        store=blob_store,
    )
    current = store.get_case(config.CASE_INDEX_CONTAINER, case_id)
    if current is None:
        raise RuntimeError("case index disappeared before run publication")
    current_run = _run_from_item(current, run_id)
    if current_run is None or current_run.get("fencing_token") != run_record["fencing_token"]:
        return ArchiveWriteResult(status="skipped", case_id=case_id, case_envelope_key=envelope_key, message="case run fence was lost")
    completed = {**run_record, "state": "completed", "completed_at": _format_utc(processed)}
    publication = store.publish_case_run_if_latest(
        config.CASE_INDEX_CONTAINER,
        case_id=case_id,
        run_id=run_id,
        run_record=completed,
        expected_etag=str(current.get("_etag") or ""),
        processed_at=_format_utc(processed),
    )
    if not publication.applied:
        return ArchiveWriteResult(status="skipped", case_id=case_id, case_envelope_key=envelope_key, message=f"case latest-run publication failed: {publication.outcome}")
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


def _resolve_finding_id(
    alert_payload: Any,
    source_key: str,
    *,
    source_bucket: str = "",
) -> str:
    candidate = _extract_first_string(alert_payload, IDENTIFIER_FIELDS)
    if not candidate:
        filename = PurePosixPath(source_key).name
        lower = filename.lower()
        if lower.endswith(".gzip"):
            filename = filename[:-5]
        elif lower.endswith(".gz"):
            filename = filename[:-3]
        raw_stem = filename.rsplit(".", 1)[0]
        stem = re.sub(r"[^A-Za-z0-9_.:-]+", "_", raw_stem).strip("._:-") or "source"
        digest_source = f"{source_bucket}/{source_key}" if source_bucket else source_key
        digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:16]
        candidate = f"{stem[:111]}-{digest}"
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


def _build_envelope_key(
    config: Config,
    processed_at: datetime,
    case_id: str,
    run_id: str = "",
    immutable_run: bool = False,
) -> str:
    filename = f"{case_id}/{run_id}.json" if immutable_run else f"{case_id}.json"
    return (
        f"{config.CASE_ARCHIVE_PREFIX}/"
        f"{processed_at.year:04d}/{processed_at.month:02d}/{processed_at.day:02d}/"
        f"{filename}"
    )


def _build_processing_id(source: SourceContext) -> str:
    material = "\x1f".join(
        (
            source.input_bucket,
            source.input_key,
            source.source_version_id or "",
            source.source_etag or "",
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _build_run_id(finding_id: str, processing_id: str) -> str:
    digest = hashlib.sha256(f"{finding_id}:{processing_id}".encode("utf-8")).hexdigest()[:24]
    return f"run-{digest}"


def _run_from_item(item: dict[str, Any] | None, run_id: str) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    runs = item.get("runs")
    if isinstance(runs, dict) and isinstance(runs.get(run_id), dict):
        return dict(runs[run_id])
    return None


def _claim_run(
    store: Any,
    config: Config,
    current: dict[str, Any],
    run_id: str,
    run_record: dict[str, Any],
) -> dict[str, Any] | None:
    etag = str(current.get("_etag") or "")
    if not etag:
        raise RuntimeError("case index is missing its concurrency token")
    runs = current.get("runs")
    run_map = dict(runs) if isinstance(runs, dict) else {}
    if run_id in run_map:
        return current if str(run_map[run_id].get("state")) == "claimed" else None
    replacement = dict(current)
    run_map[run_id] = run_record
    replacement["runs"] = run_map
    outcome = store.replace_if_match(
        config.CASE_INDEX_CONTAINER,
        replacement,
        expected_etag=etag,
    )
    return outcome.item if outcome.applied else None


def _run_result(
    item: dict[str, Any] | None,
    run: dict[str, Any],
    retrieval_status: str,
    source_completeness: str,
) -> ArchiveWriteResult:
    return ArchiveWriteResult(
        status="success",
        case_id=str((item or {}).get("case_id") or ""),
        case_envelope_key=str(run.get("envelope_key") or (item or {}).get("case_envelope_key") or ""),
        retrieval_status=str((item or {}).get("retrieval_status") or retrieval_status),
        source_completeness=str((item or {}).get("source_completeness") or source_completeness),
        message="case archive run replay matched existing identity",
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
        "source_etag": source.source_etag,
        "source_version_id": source.source_version_id,
        "processing_id": source.processing_id,
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
