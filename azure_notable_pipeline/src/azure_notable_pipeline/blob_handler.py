"""Azure-native Blob intake and core notable-analysis orchestration."""

from __future__ import annotations

import gzip
import io
import json
import logging
import os
import re
import time
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any, Callable, Mapping

from .analyzer_job import AnalyzerQueueJob
from .blob_store import (
    BlobConditionFailedError,
    BlobReadResult,
    read_blob_result,
    write_text_blob,
)
from .config import Config, load_config
from .html_generator import generate_html_report
from .idempotency import (
    begin_side_effect,
    complete_side_effect_success,
    release_side_effect_lock,
)
from .markdown_generator import generate_markdown_report
from .queue_publisher import enqueue_analyzer_job, enqueue_case_embed
from .runtime_security import validate_https_url
from .secret_provider import read_secret_field
from .ttp_analyzer import AnthropicAnalyzer

logger = logging.getLogger(__name__)

PLACEHOLDER_FILENAMES = frozenset(
    {".keep", ".gitkeep", "_success", ".placeholder"}
)
DEFAULT_MAX_DECOMPRESSED_INPUT_BYTES = 1_048_576
FINDING_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class PipelineSinkError(RuntimeError):
    """A durable report or configured downstream sink did not complete."""


class UnsupportedPipelineCapabilityError(RuntimeError):
    """A later-phase capability was enabled before its native workflow exists."""


@dataclass(frozen=True)
class BlobCreatedInput:
    """Normalized internal observation from the strict analyzer queue job."""

    container_name: str
    blob_name: str
    etag: str
    size_bytes: int
    last_modified: str

    @classmethod
    def from_analyzer_job(cls, job: AnalyzerQueueJob) -> BlobCreatedInput:
        return cls(
            container_name=job.container_name,
            blob_name=job.blob_name,
            etag=job.etag,
            size_bytes=job.size_bytes,
            last_modified=job.last_modified,
        )


@dataclass(frozen=True)
class CaseEnvelopeReference:
    """Native reference produced by the deferred case-archive workflow."""

    container_name: str
    blob_name: str

    def __post_init__(self) -> None:
        if not isinstance(self.container_name, str) or not self.container_name.strip():
            raise ValueError("case envelope container_name must be a non-empty string")
        if not isinstance(self.blob_name, str) or not self.blob_name.strip():
            raise ValueError("case envelope blob_name must be a non-empty string")


@dataclass(frozen=True)
class DecodedNotable:
    """Decoded notable text and format metadata used by the analyzer."""

    content: str
    content_type: str
    was_compressed: bool


def normalize_analyzer_queue_message(payload: str | bytes) -> BlobCreatedInput:
    """Validate the strict v1 job before it crosses into orchestration."""

    return BlobCreatedInput.from_analyzer_job(AnalyzerQueueJob.from_json(payload))


def _mapping_or_attr(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _first_value(value: Any, names: tuple[str, ...]) -> Any:
    for name in names:
        selected = _mapping_or_attr(value, name)
        if selected is not None and selected != "":
            return selected
    return None


def _format_utc_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("Blob last_modified must include a UTC timezone")
        normalized = value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return normalized
    text = str(value or "").strip()
    if not text:
        raise ValueError("Blob trigger input is missing last_modified")
    return text


def _blob_name_from_trigger(source_blob: Any, container_name: str) -> str:
    raw_name = str(_first_value(source_blob, ("name", "blob_name")) or "").strip()
    if not raw_name:
        raise ValueError("Blob trigger input is missing its Blob name")
    raw_name = raw_name.lstrip("/")
    container_prefix = f"{container_name}/"
    if raw_name.startswith(container_prefix):
        raw_name = raw_name[len(container_prefix) :]
    return raw_name


def publish_blob_trigger_input(
    source_blob: object,
    *,
    config: Config | None = None,
    publisher: Any | None = None,
    enqueue: Callable[..., None] = enqueue_analyzer_job,
) -> dict[str, object]:
    """Publish one strict analyzer job from a polling Blob-trigger observation."""

    runtime_config = config or load_config()
    container_name = runtime_config.INPUT_CONTAINER_NAME
    blob_name = _blob_name_from_trigger(source_blob, container_name)
    metadata = _mapping_or_attr(source_blob, "metadata", {}) or {}
    properties = _mapping_or_attr(source_blob, "blob_properties", {}) or {}
    etag = str(
        _first_value(source_blob, ("etag", "e_tag"))
        or _first_value(properties, ("etag", "ETag", "eTag"))
        or _first_value(metadata, ("etag", "eTag", "ETag"))
        or ""
    ).strip()
    size_value = _first_value(source_blob, ("length", "size", "size_bytes"))
    if size_value is None:
        size_value = _first_value(
            properties,
            ("ContentLength", "Length", "content_length", "size"),
        )
    if size_value is None:
        size_value = _first_value(metadata, ("length", "size", "size_bytes"))
    if isinstance(size_value, bool):
        raise ValueError("Blob trigger size must be a non-negative integer")
    try:
        size_bytes = int(size_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Blob trigger size must be a non-negative integer") from exc
    last_modified_value = _first_value(
        source_blob,
        ("last_modified", "lastModified"),
    ) or _first_value(
        properties,
        ("LastModified", "last_modified", "lastModified"),
    ) or _first_value(metadata, ("last_modified", "lastModified"))
    last_modified = _format_utc_timestamp(last_modified_value)

    job = AnalyzerQueueJob.create(
        container_name=container_name,
        blob_name=blob_name,
        etag=etag,
        size_bytes=size_bytes,
        last_modified=last_modified,
    )
    enqueue(
        container_name=job.container_name,
        blob_name=job.blob_name,
        etag=job.etag,
        size_bytes=job.size_bytes,
        last_modified=job.last_modified,
        publisher=publisher,
    )
    logger.info(
        "Published analyzer job container=%s blob=%s size_bytes=%d etag=%s",
        container_name,
        blob_name,
        size_bytes,
        etag,
    )
    return job.to_dict()


def should_skip_blob(blob_name: str, size_bytes: int) -> tuple[bool, str]:
    """Return whether a marker, placeholder, or empty Blob should be ignored."""

    if blob_name.endswith("/"):
        return True, "folder marker (Blob name ends with '/')"
    if size_bytes == 0:
        return True, "empty Blob (0 bytes)"
    basename = blob_name.rsplit("/", 1)[-1].lower()
    if basename in PLACEHOLDER_FILENAMES:
        return True, f"placeholder file ({basename})"
    return False, ""


def strip_gzip_suffix(filename: str) -> str:
    """Remove one gzip suffix from a filename."""

    lower = filename.lower()
    if lower.endswith(".gzip"):
        return filename[:-5]
    if lower.endswith(".gz"):
        return filename[:-3]
    return filename


def source_blob_stem(blob_name: str) -> str:
    """Return the deterministic report stem for one source Blob name."""

    filename = PurePosixPath(blob_name).name
    if not filename:
        return ""
    return PurePosixPath(strip_gzip_suffix(filename)).stem


def extract_finding_id_from_blob_name(blob_name: str) -> str:
    """Derive the finding identifier from the Blob filename."""

    return source_blob_stem(blob_name)


def validate_finding_id(value: str) -> str:
    """Validate an external finding identifier before a writeback."""

    finding_id = str(value or "").strip()
    if not FINDING_ID_RE.fullmatch(finding_id):
        raise ValueError(
            "finding_id must be 1-128 chars using letters, digits, dot, "
            "underscore, colon, or dash"
        )
    return finding_id


def is_gzip_input(blob_name: str) -> bool:
    lower_name = blob_name.lower()
    return lower_name.endswith(".gz") or lower_name.endswith(".gzip")


def infer_content_type_from_blob_name(blob_name: str) -> str:
    filename = PurePosixPath(blob_name).name
    return "json" if strip_gzip_suffix(filename).lower().endswith(".json") else "text"


def decompress_gzip_bounded(raw_bytes: bytes, max_bytes: int) -> bytes:
    """Decompress gzip bytes without allowing a decompression bomb."""

    chunks: list[bytes] = []
    total_bytes = 0
    with gzip.GzipFile(fileobj=io.BytesIO(raw_bytes)) as gzip_file:
        while True:
            chunk = gzip_file.read(64 * 1024)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                raise ValueError(
                    "Decompressed input exceeds MAX_DECOMPRESSED_INPUT_BYTES "
                    f"({max_bytes})"
                )
            chunks.append(chunk)
    return b"".join(chunks)


def decode_blob_notable(
    blob_name: str,
    raw_bytes: bytes,
    *,
    config: Config | None = None,
) -> DecodedNotable:
    """Decode UTF-8 text or bounded gzip content from one input Blob."""

    runtime_config = config or load_config()
    max_bytes = int(runtime_config.MAX_DECOMPRESSED_INPUT_BYTES)
    if max_bytes < 1:
        raise ValueError("MAX_DECOMPRESSED_INPUT_BYTES must be greater than 0")
    compressed = is_gzip_input(blob_name)
    content_bytes = raw_bytes
    if compressed:
        try:
            content_bytes = decompress_gzip_bounded(raw_bytes, max_bytes)
        except (gzip.BadGzipFile, EOFError, zlib.error) as exc:
            raise ValueError(f"Invalid gzip content for Blob {blob_name!r}") from exc
    elif len(content_bytes) > max_bytes:
        raise ValueError(
            f"Blob {blob_name!r} exceeds MAX_DECOMPRESSED_INPUT_BYTES ({max_bytes})"
        )
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Blob {blob_name!r} must contain UTF-8 text") from exc
    return DecodedNotable(
        content=content,
        content_type=infer_content_type_from_blob_name(blob_name),
        was_compressed=compressed,
    )


def normalize_notable(content: str, content_type: str = "text") -> Any:
    """Preserve valid JSON objects/arrays and otherwise retain raw alert text."""

    stripped = (content or "").strip()
    if content_type == "json" or stripped.startswith(("{", "[")):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON notable; preserving the input as raw text")
    return content


def _validate_intake_scope(intake: BlobCreatedInput, config: Config) -> None:
    if intake.container_name != config.INPUT_CONTAINER_NAME:
        raise ValueError("Analyzer job container does not match INPUT_CONTAINER_NAME")
    parts = PurePosixPath(intake.blob_name).parts
    if not parts or parts[0] != "incoming" or any(part in {".", ".."} for part in parts):
        raise ValueError("Analyzer job Blob name must be under incoming/")


def write_to_blob_sink(
    source_blob_name: str,
    markdown: str,
    analysis_result: dict[str, Any],
    *,
    config: Config | None = None,
    store: Any | None = None,
) -> dict[str, Any]:
    """Write deterministic Markdown/JSON and optional HTML report Blobs."""

    runtime_config = config or load_config()
    container = runtime_config.OUTPUT_CONTAINER_NAME.strip()
    if not container:
        raise PipelineSinkError("OUTPUT_CONTAINER_NAME is required")
    base_name = source_blob_stem(source_blob_name)
    if not base_name:
        raise PipelineSinkError("Source Blob name cannot produce a report name")
    output_prefix = runtime_config.OUTPUT_PREFIX.strip().strip("/")
    if not output_prefix:
        raise PipelineSinkError("OUTPUT_PREFIX is required")
    markdown_key = f"{output_prefix}/{base_name}.md"
    json_key = f"{output_prefix}/{base_name}.json"
    html_key = f"{output_prefix}/{base_name}.html"
    llm_response = analysis_result.get("llm_response")
    json_body = json.dumps(
        llm_response if llm_response is not None else {},
        ensure_ascii=False,
        indent=2,
        default=str,
    )

    write_text_blob(
        container,
        markdown_key,
        markdown,
        content_type="text/markdown",
        overwrite=True,
        store=store,
    )
    write_text_blob(
        container,
        json_key,
        json_body,
        content_type="application/json",
        overwrite=True,
        store=store,
    )
    result: dict[str, Any] = {
        "status": "success",
        "container": container,
        "markdown_key": markdown_key,
        "json_key": json_key,
    }
    html = analysis_result.get("html")
    if runtime_config.HTML_REPORT_ENABLED and isinstance(html, str) and html:
        write_text_blob(
            container,
            html_key,
            html,
            content_type="text/html",
            overwrite=True,
            store=store,
        )
        result["html_key"] = html_key
    return result


def _resolve_finding_id_for_writeback(
    analysis_result: dict[str, Any],
    source_blob_name: str,
    config: Config,
) -> str:
    source_finding_id = validate_finding_id(
        extract_finding_id_from_blob_name(source_blob_name)
    )
    alert_payload = analysis_result.get("alert_payload")
    payload_finding_id = ""
    if isinstance(alert_payload, dict):
        for field in ("finding_id", "notable_id", "sid"):
            candidate = alert_payload.get(field)
            if candidate:
                payload_finding_id = validate_finding_id(str(candidate))
                break
    if payload_finding_id and payload_finding_id != source_finding_id:
        raise ValueError("payload finding_id does not match Blob name stem")
    if config.SPLUNK_REQUIRE_PAYLOAD_FINDING_ID and not payload_finding_id:
        raise ValueError("payload finding_id is required for Splunk writeback")
    return payload_finding_id or source_finding_id


def _splunk_api_token(config: Config) -> str:
    secret_name = config.SPLUNK_API_TOKEN_SECRET_NAME.strip()
    if not secret_name:
        return ""
    return read_secret_field(
        secret_name,
        field=config.SPLUNK_API_TOKEN_SECRET_FIELD,
        allow_plain_text=True,
    )


def write_to_splunk_rest(
    analysis_result: dict[str, Any],
    source_blob_name: str,
    *,
    config: Config | None = None,
) -> dict[str, Any]:
    """Perform the bounded, idempotent Splunk notable writeback."""

    import requests

    runtime_config = config or load_config()
    finding_id = _resolve_finding_id_for_writeback(
        analysis_result,
        source_blob_name,
        runtime_config,
    )
    token = _splunk_api_token(runtime_config)
    if not runtime_config.SPLUNK_BASE_URL or not token:
        return {"status": "error", "message": "Splunk REST credentials not configured"}
    reservation = begin_side_effect(
        runtime_config,
        operation="splunk_notable_update",
        key=finding_id,
    )
    if not reservation.should_execute:
        marker_status = (reservation.existing_marker or {}).get("status", "unknown")
        return {
            "status": "skipped",
            "finding_id": finding_id,
            "idempotency_status": marker_status,
            "message": f"Splunk notable update already reserved with status={marker_status}",
        }
    endpoint_path = runtime_config.SPLUNK_NOTABLE_UPDATE_PATH
    if not endpoint_path.startswith("/"):
        endpoint_path = f"/{endpoint_path}"
    base_url = validate_https_url(
        runtime_config.SPLUNK_BASE_URL,
        setting_name="SPLUNK_BASE_URL",
        allow_private=runtime_config.ALLOW_PRIVATE_OUTBOUND_ENDPOINTS,
    )
    try:
        response = requests.post(
            f"{base_url.rstrip('/')}{endpoint_path}",
            data={
                "finding_id": finding_id,
                "comment": analysis_result["markdown"],
                "status": "2",
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=30,
            verify=True,
        )
        response.raise_for_status()
        recorded = complete_side_effect_success(
            reservation,
            metadata={"status_code": response.status_code, "finding_id": finding_id},
        )
        result: dict[str, Any] = {
            "status": "success",
            "status_code": response.status_code,
            "finding_id": finding_id,
        }
        if reservation.enabled:
            result["idempotency_recorded"] = recorded
        return result
    except requests.RequestException as exc:
        release_side_effect_lock(reservation)
        return {"status": "error", "message": str(exc), "finding_id": finding_id}


def write_to_notable_rest_sink(
    source_blob_name: str,
    analysis_result: dict[str, Any],
    *,
    config: Config,
    store: Any | None = None,
) -> dict[str, Any]:
    """Write durable Blob reports before attempting Splunk REST writeback."""

    blob_result = write_to_blob_sink(
        source_blob_name,
        analysis_result["markdown"],
        analysis_result,
        config=config,
        store=store,
    )
    rest_result = write_to_splunk_rest(
        analysis_result,
        source_blob_name,
        config=config,
    )
    return {
        "status": (
            "success" if rest_result.get("status") in {"success", "skipped"} else "error"
        ),
        "blob_result": blob_result,
        "rest_result": rest_result,
    }


def _assert_phase1_capabilities(
    config: Config,
    *,
    case_archive_workflow: Callable[..., CaseEnvelopeReference | None] | None,
) -> None:
    unsupported: list[str] = []
    if config.RAG_ENABLED:
        unsupported.append("rag")
    if config.SPL_QUERY_GENERATION_ENABLED or config.INVESTIGATION_QUERY_EXECUTION_ENABLED:
        unsupported.append("investigation queries")
    if config.ELASTIC_QUERY_GENERATION_ENABLED:
        unsupported.append("Elasticsearch query generation")
    if config.SERVICENOW_DRAFT_ENABLED or config.SERVICENOW_CREATE_ENABLED:
        unsupported.append("ServiceNow")
    if config.CASE_ARCHIVE_ENABLED and case_archive_workflow is None:
        unsupported.append("case archive")
    if unsupported:
        raise UnsupportedPipelineCapabilityError(
            "Native workflow not yet available for enabled capability: "
            + ", ".join(unsupported)
        )


def process_blob_created(
    intake: BlobCreatedInput,
    *,
    config: Config | None = None,
    store: Any | None = None,
    analyzer: Any | None = None,
    case_archive_workflow: Callable[..., CaseEnvelopeReference | None] | None = None,
    embed_publisher: Any | None = None,
    enqueue_embed: Callable[..., None] = enqueue_case_embed,
) -> dict[str, Any]:
    """Process one normalized Blob observation and write durable reports.

    A stale ETag is a terminal superseded outcome. A later-phase archive workflow
    may be injected and must return a native reference; this function never
    fabricates archive or Cosmos state. All other failures propagate so Azure
    Functions can retry and eventually poison the analyzer queue message.
    """

    runtime_config = config or load_config()
    _validate_intake_scope(intake, runtime_config)
    _assert_phase1_capabilities(
        runtime_config,
        case_archive_workflow=case_archive_workflow,
    )
    skip, reason = should_skip_blob(intake.blob_name, intake.size_bytes)
    if skip:
        logger.info("Skipping Blob %s: %s", intake.blob_name, reason)
        return {"blob_name": intake.blob_name, "status": "skipped", "reason": reason}

    max_bytes = runtime_config.MAX_DECOMPRESSED_INPUT_BYTES
    if intake.size_bytes > max_bytes and not is_gzip_input(intake.blob_name):
        raise ValueError(
            f"Blob {intake.blob_name!r} exceeds MAX_DECOMPRESSED_INPUT_BYTES "
            f"({max_bytes})"
        )
    try:
        downloaded: BlobReadResult = read_blob_result(
            intake.container_name,
            intake.blob_name,
            if_match=intake.etag,
            max_bytes=None if is_gzip_input(intake.blob_name) else max_bytes,
            store=store,
        )
    except BlobConditionFailedError:
        logger.info(
            "Analyzer job superseded by a newer Blob version container=%s blob=%s etag=%s",
            intake.container_name,
            intake.blob_name,
            intake.etag,
        )
        return {
            "blob_name": intake.blob_name,
            "status": "superseded",
            "reason": "stale_etag",
        }
    if downloaded.info.etag and downloaded.info.etag != intake.etag:
        logger.info(
            "Analyzer job superseded after read container=%s blob=%s queued_etag=%s current_etag=%s",
            intake.container_name,
            intake.blob_name,
            intake.etag,
            downloaded.info.etag,
        )
        return {
            "blob_name": intake.blob_name,
            "status": "superseded",
            "reason": "stale_etag",
        }

    decoded = decode_blob_notable(
        intake.blob_name,
        downloaded.body,
        config=runtime_config,
    )
    alert_payload = normalize_notable(decoded.content, decoded.content_type)
    analysis_engine = analyzer or AnthropicAnalyzer(
        deployment=runtime_config.AZURE_AI_FOUNDRY_ANALYSIS_DEPLOYMENT,
        base_url=runtime_config.AZURE_AI_FOUNDRY_ANTHROPIC_BASE_URL,
        propagate_retryable=True,
    )
    alert_text = analysis_engine.format_alert_input(
        alert_payload,
        raw_content=decoded.content,
        content_type=decoded.content_type,
    )
    started = time.monotonic()
    scored_ttps = analysis_engine.analyze_ttp(alert_text)
    llm_response = analysis_engine.last_llm_response or {}
    markdown = generate_markdown_report(alert_text, llm_response, scored_ttps)
    html = None
    if runtime_config.HTML_REPORT_ENABLED:
        html = generate_html_report(alert_text, llm_response, scored_ttps, markdown)
    analysis_result = {
        "markdown": markdown,
        "html": html,
        "llm_response": llm_response,
        "scored_ttps": scored_ttps,
        "alert_payload": alert_payload,
        "meta": {
            "model_deployment": runtime_config.AZURE_AI_FOUNDRY_ANALYSIS_DEPLOYMENT,
            "execution_time_seconds": round(time.monotonic() - started, 2),
            "ttp_count": len(scored_ttps),
            "source_container": intake.container_name,
            "source_blob_name": intake.blob_name,
            "source_etag": intake.etag,
        },
    }
    if runtime_config.REPORT_SINK_MODE == "blob":
        sink_result = write_to_blob_sink(
            intake.blob_name,
            markdown,
            analysis_result,
            config=runtime_config,
            store=store,
        )
    elif runtime_config.REPORT_SINK_MODE == "notable_rest":
        sink_result = write_to_notable_rest_sink(
            intake.blob_name,
            analysis_result,
            config=runtime_config,
            store=store,
        )
    else:  # Config validates this, but keep the orchestration boundary fail-closed.
        raise ValueError(f"Unsupported REPORT_SINK_MODE: {runtime_config.REPORT_SINK_MODE}")
    if sink_result.get("status") != "success":
        raise PipelineSinkError(
            f"Configured report sink failed for {intake.blob_name}: {sink_result}"
        )
    case_envelope_reference = None
    if runtime_config.CASE_ARCHIVE_ENABLED:
        workflow = case_archive_workflow
        if workflow is None:  # Kept explicit if preflight validation changes.
            raise UnsupportedPipelineCapabilityError(
                "Native workflow not yet available for enabled capability: case archive"
            )
        case_envelope_reference = workflow(
            analysis_result=analysis_result,
            config=runtime_config,
            intake=intake,
            decoded_notable=decoded,
            sink_result=sink_result,
        )
        if (
            case_envelope_reference is not None
            and not isinstance(case_envelope_reference, CaseEnvelopeReference)
        ):
            raise TypeError(
                "case archive workflow must return CaseEnvelopeReference or None"
            )
    case_embed_queued = False
    if runtime_config.CASE_QA_ENABLED and case_envelope_reference is not None:
        enqueue_embed(
            case_envelope_reference.container_name,
            case_envelope_reference.blob_name,
            publisher=embed_publisher,
        )
        case_embed_queued = True
    logger.info(
        "Processed Blob container=%s blob=%s ttp_count=%d sink=%s case_embed_queued=%s",
        intake.container_name,
        intake.blob_name,
        len(scored_ttps),
        runtime_config.REPORT_SINK_MODE,
        case_embed_queued,
    )
    return {
        "blob_name": intake.blob_name,
        "status": "success",
        "ttp_count": len(scored_ttps),
        "sink_result": sink_result,
        "case_embed_queued": case_embed_queued,
    }


__all__ = [
    "BlobCreatedInput",
    "CaseEnvelopeReference",
    "DecodedNotable",
    "PipelineSinkError",
    "UnsupportedPipelineCapabilityError",
    "decode_blob_notable",
    "decompress_gzip_bounded",
    "extract_finding_id_from_blob_name",
    "infer_content_type_from_blob_name",
    "is_gzip_input",
    "normalize_analyzer_queue_message",
    "normalize_notable",
    "process_blob_created",
    "publish_blob_trigger_input",
    "should_skip_blob",
    "source_blob_stem",
    "strip_gzip_suffix",
    "validate_finding_id",
    "write_to_blob_sink",
    "write_to_notable_rest_sink",
    "write_to_splunk_rest",
]
