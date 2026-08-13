"""
Lambda handler for S3-triggered notable analysis pipeline.

Processes notables from S3, analyzes with Bedrock, and outputs to
configurable sinks (S3 or Splunk notable REST API).
"""

import gzip
import hashlib
import io
import json
import os
import logging
import time
import traceback
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
from urllib.parse import quote, unquote_plus
from typing import Dict, Any

from .aws_clients import s3_client as make_s3_client
from .aws_clients import secretsmanager_client as make_secretsmanager_client
from .aws_clients import dynamodb_client as make_dynamodb_client
from .aws_clients import lambda_client as make_lambda_client
from .aws_clients import sqs_client as make_sqs_client
from .bedrock_kb_retrieval import RetrievalResult, retrieve_soc_context
from .historical_closed_ticket_grounding import (
    retrieve_historical_closed_tickets_for_first_pass,
)
from .case_archive import SourceContext, archive_case
from .config import Config, load_config
from .html_generator import generate_html_report
from .idempotency import (
    begin_side_effect,
    complete_side_effect_success,
    mark_side_effect_uncertain,
    release_side_effect_lock,
)
from .elasticsearch_investigation import execute_hypothesis_elasticsearch_queries
from .elasticsearch_query_grounding import retrieve_elasticsearch_grounding
from .query_result_enrichment import enrich_analysis_with_query_results
from .servicenow import (
    build_servicenow_incident_draft,
    create_servicenow_incident,
    extract_servicenow_create_approval,
)
from .runtime_security import read_bounded_bytes, resolve_secret_string, validate_https_url
from .spl_query_grounding import retrieve_spl_query_grounding
from .splunk_investigation import HttpSplunkMcpClient, execute_hypothesis_queries
from .ttp_analyzer import BedrockAnalyzer
from .markdown_generator import generate_markdown_report
from .spl_query_grounding import SplGroundingResult
from .elasticsearch_query_grounding import ElasticsearchGroundingResult

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients through the centralized factory so tests can use
# mocked clients and local integration can use AWS_ENDPOINT_URL.
s3_client = make_s3_client()
secretsmanager_client = make_secretsmanager_client()
_dynamodb_client: Any | None = None
_lambda_client: Any | None = None
_sqs_client: Any | None = None

# Placeholder filenames to skip (case-insensitive basename match)
PLACEHOLDER_FILENAMES = frozenset({'.keep', '.gitkeep', '_success', '.placeholder'})
DEFAULT_MAX_DECOMPRESSED_INPUT_BYTES = 1_048_576
DEFAULT_MAX_COMPRESSED_INPUT_BYTES = 2_097_152
GZIP_CONTENT_ENCODINGS = frozenset({'gzip', 'x-gzip'})
FINDING_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def get_dynamodb_client() -> Any:
    """Return the DynamoDB client lazily because archive is default-off."""

    global _dynamodb_client  # pylint: disable=global-statement
    if _dynamodb_client is None:
        _dynamodb_client = make_dynamodb_client()
    return _dynamodb_client


def get_lambda_client() -> Any:
    """Return the Lambda client lazily because archive is default-off."""

    global _lambda_client  # pylint: disable=global-statement
    if _lambda_client is None:
        _lambda_client = make_lambda_client()
    return _lambda_client


def get_sqs_client() -> Any:
    """Return the SQS client lazily because archive is default-off."""

    global _sqs_client  # pylint: disable=global-statement
    if _sqs_client is None:
        _sqs_client = make_sqs_client()
    return _sqs_client


@dataclass(frozen=True)
class DecodedNotable:
    """Decoded notable content plus metadata needed by the analysis flow."""

    content: str
    content_type: str
    was_compressed: bool


@dataclass(frozen=True)
class S3ProcessingIdentity:
    """Immutable identity for one S3 delivery/version of a notable."""

    bucket: str
    key: str
    version_id: str = ""
    etag: str = ""
    sequencer: str = ""

    @property
    def processing_id(self) -> str:
        """Return a stable, non-sensitive processing identifier."""

        material = "\x1f".join(
            (
                self.bucket,
                self.key,
                self.version_id or self.etag or "unversioned",
                self.etag,
                self.sequencer,
            )
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


class BedrockAnalysisFailure(RuntimeError):
    """Core Bedrock analysis failed and must not become an empty report."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class S3ReportArtifactMismatchError(ValueError):
    """Existing S3 report artifact content does not match the intended payload."""


def _is_s3_precondition_failed(exc: Exception) -> bool:
    response = getattr(exc, "response", {})
    if isinstance(response, dict):
        error = response.get("Error", {})
        if isinstance(error, dict):
            code = str(error.get("Code", ""))
            if code in {"PreconditionFailed", "412"}:
                return True
    return exc.__class__.__name__ in {"PreconditionFailed", "PreconditionFailedException"}


def _put_s3_report_artifact(
    *,
    bucket: str,
    key: str,
    body: bytes,
    content_type: str,
    create_only: bool,
) -> None:
    """Write one report artifact, reconciling create-only conflicts on replay."""

    if not create_only:
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )
        return
    try:
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            IfNoneMatch="*",
        )
    except Exception as exc:
        if not _is_s3_precondition_failed(exc):
            raise
        existing = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
        if existing != body:
            raise S3ReportArtifactMismatchError(
                f"existing report artifact s3://{bucket}/{key} does not match intended content"
            )


def _s3_event_records(record: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """Unwrap direct S3 records and S3 notifications delivered through SQS."""

    if record.get("eventSource") != "aws:sqs":
        return [record], None
    message_id = str(record.get("messageId", "")).strip() or None
    try:
        body = json.loads(record.get("body", ""))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("SQS message body is not valid JSON") from exc
    nested = body.get("Records") if isinstance(body, dict) else None
    if not isinstance(nested, list) or not nested or not all(isinstance(item, dict) for item in nested):
        raise ValueError("SQS message body is not an S3 notification")
    return nested, message_id


def _processing_identity(record: dict[str, Any], response: dict[str, Any], bucket: str, key: str) -> S3ProcessingIdentity:
    """Build identity from all available S3 version/replay ordering fields."""

    obj = record.get("s3", {}).get("object", {})
    return S3ProcessingIdentity(
        bucket=bucket,
        key=key,
        version_id=str(obj.get("versionId", "") or ""),
        etag=str(obj.get("eTag", "") or response.get("ETag", "")).strip('"'),
        sequencer=str(obj.get("sequencer", "") or ""),
    )


def _report_stem(source_key: str) -> str:
    """Preserve source prefixes while constraining report path components."""

    decoded_key = unquote_plus(source_key or "").lstrip("/")
    path = PurePosixPath(decoded_key)
    parts = [quote(part, safe="-_.~") for part in path.parts if part not in ("", ".", "..")]
    if not parts:
        return "unknown"
    filename = parts[-1]
    original_filename = path.name
    stripped_filename = strip_gzip_suffix(original_filename)
    stem = Path(stripped_filename).stem
    parts[-1] = quote(stem, safe="-_.~")
    return "/".join(parts)


def _report_key(output_prefix: str, source_key: str, extension: str, identity: S3ProcessingIdentity | None) -> str:
    # Keep direct helper calls backward-compatible; event-driven calls always pass identity.
    stem = _report_stem(source_key) if identity is not None else source_key_stem(source_key)
    suffix = ""
    if identity is not None:
        suffix = f"--{identity.processing_id}"
    prefix = str(output_prefix or "reports").strip("/")
    return f"{prefix}/{stem}{suffix}.{extension}" if prefix else f"{stem}{suffix}.{extension}"


def _optional_call(label: str, operation: Any, fallback: Any, degraded: list[str]) -> Any:
    """Run noncritical enrichment without converting it into a false core success."""

    try:
        return operation()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("Optional enrichment %s degraded: %s", label, exc)
        degraded.append(label)
        return fallback


def should_skip_object(key: str, size: int) -> tuple[bool, str]:
    """Check if an S3 object should be skipped (folder marker, placeholder, or empty).

    Args:
        key: S3 object key.
        size: Object size in bytes (from S3 event metadata).

    Returns:
        Tuple of (should_skip: bool, reason: str). If should_skip is False, reason is empty.
    """
    # Skip folder markers (keys ending with '/')
    if key.endswith('/'):
        return True, "folder marker (key ends with '/')"

    # Skip 0-byte objects
    if size == 0:
        return True, "empty object (0 bytes)"

    # Skip common placeholder filenames
    basename = key.rsplit('/', 1)[-1].lower()
    if basename in PLACEHOLDER_FILENAMES:
        return True, f"placeholder file ({basename})"

    return False, ""


def normalize_notable(content: str, content_type: str = 'text') -> Any:
    """Normalize S3 notable content into a format-agnostic alert payload.

    Args:
        content: Raw content from S3 object (JSON string or plain text).
        content_type: Type hint for content ('json' or 'text').

    Returns:
        Parsed JSON object for JSON alerts when valid; otherwise raw text.
    """
    stripped = (content or "").strip()
    if content_type == 'json' or stripped.startswith('{') or stripped.startswith('['):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Failed to parse content as JSON, treating as raw text")
    return content


def get_max_decompressed_input_bytes(config: Config | None = None) -> int:
    """Return the configured decompressed input byte limit.

    Returns:
        Positive byte limit used for gzip input.

    Raises:
        ValueError: If MAX_DECOMPRESSED_INPUT_BYTES is not a positive integer.
    """
    raw_limit = (
        str(config.MAX_DECOMPRESSED_INPUT_BYTES)
        if config is not None
        else os.environ.get(
            'MAX_DECOMPRESSED_INPUT_BYTES',
            str(DEFAULT_MAX_DECOMPRESSED_INPUT_BYTES),
        )
    )
    try:
        limit = int(raw_limit)
    except ValueError as exc:
        raise ValueError("MAX_DECOMPRESSED_INPUT_BYTES must be an integer") from exc
    if limit < 1:
        raise ValueError("MAX_DECOMPRESSED_INPUT_BYTES must be greater than 0")
    return limit


def get_max_compressed_input_bytes(config: Config | None = None) -> int:
    """Return the maximum number of compressed bytes read from one S3 object."""

    raw_limit = (
        str(config.MAX_COMPRESSED_INPUT_BYTES)
        if config is not None
        else os.environ.get('MAX_COMPRESSED_INPUT_BYTES', str(DEFAULT_MAX_COMPRESSED_INPUT_BYTES))
    )
    try:
        limit = int(raw_limit)
    except ValueError as exc:
        raise ValueError("MAX_COMPRESSED_INPUT_BYTES must be an integer") from exc
    if limit < 1:
        raise ValueError("MAX_COMPRESSED_INPUT_BYTES must be greater than 0")
    return limit


def content_encoding_includes_gzip(content_encoding: str | None) -> bool:
    """Check whether an S3 ContentEncoding value includes gzip."""
    if not content_encoding:
        return False
    encodings = {part.strip().lower() for part in content_encoding.split(',')}
    return bool(encodings & GZIP_CONTENT_ENCODINGS)


def strip_gzip_suffix(filename: str) -> str:
    """Remove one gzip suffix from a filename when present."""
    lower_filename = filename.lower()
    if lower_filename.endswith('.gzip'):
        return filename[:-5]
    if lower_filename.endswith('.gz'):
        return filename[:-3]
    return filename


def source_key_stem(source_key: str) -> str:
    """Derive a stable source stem, stripping one gzip suffix before the data extension."""
    decoded_key = unquote_plus(source_key or "")
    filename = PurePosixPath(decoded_key).name
    if not filename:
        return ""
    return Path(strip_gzip_suffix(filename)).stem


def validate_finding_id(value: str) -> str:
    """Validate external notable/finding identifiers before writeback."""

    finding_id = str(value or "").strip()
    if not FINDING_ID_RE.fullmatch(finding_id):
        raise ValueError("finding_id must be 1-128 chars using letters, digits, dot, underscore, colon, or dash")
    return finding_id


def resolve_finding_id_for_writeback(
    analysis_result: Dict[str, Any],
    source_key: str,
    config: Config,
) -> str:
    """Resolve a writeback finding id with optional payload/key consistency checks."""

    source_finding_id = validate_finding_id(extract_finding_id_from_s3_key(source_key))
    alert_payload = analysis_result.get("alert_payload")
    payload_finding_id = ""
    if isinstance(alert_payload, dict):
        for field in ("finding_id", "notable_id", "sid"):
            candidate = alert_payload.get(field)
            if candidate:
                payload_finding_id = validate_finding_id(str(candidate))
                break
    if payload_finding_id and payload_finding_id != source_finding_id:
        raise ValueError("payload finding_id does not match S3 object key stem")
    if getattr(config, "SPLUNK_REQUIRE_PAYLOAD_FINDING_ID", False) and not payload_finding_id:
        raise ValueError("payload finding_id is required for Splunk writeback")
    return payload_finding_id or source_finding_id


def is_gzip_input(source_key: str, content_encoding: str | None = None) -> bool:
    """Return whether an S3 object should be treated as gzip-compressed input."""
    decoded_key = unquote_plus(source_key or "")
    lower_key = decoded_key.lower()
    return (
        lower_key.endswith('.gz')
        or lower_key.endswith('.gzip')
        or content_encoding_includes_gzip(content_encoding)
    )


def infer_content_type_from_key(source_key: str) -> str:
    """Infer notable content type from the object key after removing gzip suffixes."""
    decoded_key = unquote_plus(source_key or "")
    filename = PurePosixPath(decoded_key).name
    inner_filename = strip_gzip_suffix(filename).lower()
    return 'json' if inner_filename.endswith('.json') else 'text'


def decompress_gzip_bounded(raw_bytes: bytes, max_bytes: int) -> bytes:
    """Decompress gzip bytes while enforcing a maximum decompressed size."""
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
                    f"Decompressed input exceeds MAX_DECOMPRESSED_INPUT_BYTES ({max_bytes})"
                )
            chunks.append(chunk)

    return b''.join(chunks)


def decode_s3_notable_object(
    source_key: str,
    raw_bytes: bytes,
    content_encoding: str | None = None,
    config: Config | None = None,
) -> DecodedNotable:
    """Decode an S3 notable object, including bounded gzip decompression.

    Args:
        source_key: S3 object key used for compression and content-type detection.
        raw_bytes: Raw object bytes read from S3.
        content_encoding: Optional S3 ContentEncoding header.

    Returns:
        DecodedNotable with UTF-8 content and content type hint.

    Raises:
        ValueError: If gzip input is malformed, oversized, or not valid UTF-8.
    """
    was_compressed = is_gzip_input(source_key, content_encoding)
    content_bytes = raw_bytes
    max_bytes = get_max_decompressed_input_bytes(config)
    if not was_compressed and len(content_bytes) > max_bytes:
        raise ValueError(
            f"S3 object {source_key!r} exceeds MAX_DECOMPRESSED_INPUT_BYTES ({max_bytes})"
        )
    if was_compressed:
        try:
            content_bytes = decompress_gzip_bounded(
                raw_bytes,
                max_bytes,
            )
        except (gzip.BadGzipFile, EOFError, zlib.error) as exc:
            raise ValueError(f"Invalid gzip content for S3 object {source_key!r}") from exc

    try:
        content = content_bytes.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ValueError(f"S3 object {source_key!r} must contain UTF-8 text") from exc

    return DecodedNotable(
        content=content,
        content_type=infer_content_type_from_key(source_key),
        was_compressed=was_compressed,
    )


def extract_finding_id_from_s3_key(source_key: str) -> str:
    """Derive finding_id from S3 object filename (without extension).

    Args:
        source_key: S3 object key (may be URL-encoded in event payload).

    Returns:
        Filename stem used as finding_id. Returns empty string if no basename.
    """
    return source_key_stem(source_key)


def write_to_s3_sink(
    source_key: str,
    markdown: str,
    analysis_result: Dict[str, Any],
    config: Config | None = None,
    processing_identity: S3ProcessingIdentity | None = None,
) -> Dict[str, Any]:
    """Write markdown analysis report and Bedrock JSON to S3 output bucket.

    Args:
        source_key: Original S3 key from input bucket.
        markdown: Generated markdown report.
        analysis_result: Full analysis result; ``llm_response`` is serialized as sibling ``.json``.

    Returns:
        Dict with sink operation status.
    """
    try:
        config = config or load_config()
        output_bucket = config.OUTPUT_BUCKET_NAME
        output_prefix = config.OUTPUT_PREFIX

        if not output_bucket:
            logger.error("OUTPUT_BUCKET_NAME not set for s3/notable_rest sink mode")
            return {"status": "error", "message": "OUTPUT_BUCKET_NAME not configured"}

        # Generate output key based on source key
        md_key = _report_key(output_prefix, source_key, "md", processing_identity)
        json_key = _report_key(output_prefix, source_key, "json", processing_identity)
        html_key = _report_key(output_prefix, source_key, "html", processing_identity)

        llm_response = analysis_result.get("llm_response")
        if llm_response is None:
            llm_response = {}
        json_body = json.dumps(llm_response, ensure_ascii=False, indent=2, default=str)
        create_only = processing_identity is not None
        md_bytes = markdown.encode("utf-8")
        json_bytes = json_body.encode("utf-8")

        _put_s3_report_artifact(
            bucket=output_bucket,
            key=md_key,
            body=md_bytes,
            content_type="text/markdown",
            create_only=create_only,
        )
        logger.info(f"Wrote markdown report to s3://{output_bucket}/{md_key}")

        _put_s3_report_artifact(
            bucket=output_bucket,
            key=json_key,
            body=json_bytes,
            content_type="application/json",
            create_only=create_only,
        )
        logger.info(f"Wrote Bedrock JSON to s3://{output_bucket}/{json_key}")

        html_report = analysis_result.get("html")
        if config.HTML_REPORT_ENABLED and isinstance(html_report, str) and html_report:
            _put_s3_report_artifact(
                bucket=output_bucket,
                key=html_key,
                body=html_report.encode("utf-8"),
                content_type="text/html",
                create_only=create_only,
            )
            logger.info(f"Wrote HTML report to s3://{output_bucket}/{html_key}")

        result = {
            "status": "success",
            "markdown_key": md_key,
            "json_key": json_key,
            "bucket": output_bucket
        }
        if config.HTML_REPORT_ENABLED and isinstance(html_report, str) and html_report:
            result["html_key"] = html_key
        return result

    except S3ReportArtifactMismatchError as e:
        logger.error("S3 report artifact mismatch: %s", e)
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Error writing to S3 sink: {str(e)}")
        return {"status": "error", "message": str(e)}


def write_to_notable_rest_sink(
    source_key: str,
    analysis_result: Dict[str, Any],
    config: Config | None = None,
    processing_identity: S3ProcessingIdentity | None = None,
) -> Dict[str, Any]:
    """Write the markdown report to S3, then update the Splunk notable via REST.

    Args:
        source_key: Original S3 key; reused for report naming and finding_id derivation.
        analysis_result: Full analysis result including markdown and TTPs.

    Returns:
        Dict with the combined sink operation status and per-sink results.
    """
    config = config or load_config()
    s3_result = write_to_s3_sink(
        source_key,
        analysis_result["markdown"],
        analysis_result,
        config,
        processing_identity,
    )
    if s3_result.get("status") != "success":
        return {
            "status": "error",
            "s3_result": s3_result,
            "rest_result": {"status": "skipped", "message": "Skipped Splunk writeback because S3 sink failed"},
        }
    rest_result = write_to_splunk_rest(analysis_result, source_key, config)
    combined_status = (
        "success"
        if s3_result.get("status") == "success" and rest_result.get("status") in {"success", "skipped", "uncertain"}
        else "error"
    )

    return {
        "status": combined_status,
        "s3_result": s3_result,
        "rest_result": rest_result,
    }


def write_case_archive_after_sink(
    *,
    analysis_result: Dict[str, Any],
    config: Config,
    source_bucket: str,
    source_key: str,
    decoded_notable: DecodedNotable,
    processing_identity: S3ProcessingIdentity | None = None,
    sink_result: Dict[str, Any],
    processed_at: str | None = None,
) -> Dict[str, Any]:
    """Archive a completed case after the report sink succeeds."""

    if not config.CASE_ARCHIVE_ENABLED:
        return {"status": "skipped", "message": "case archive disabled"}
    if sink_result.get("status") != "success":
        return {
            "status": "skipped",
            "message": "Skipped archive because report sink failed",
        }
    try:
        source = SourceContext(
            input_bucket=source_bucket,
            input_key=source_key,
            source_filename=PurePosixPath(source_key).name,
            content_type=decoded_notable.content_type,
            was_compressed=decoded_notable.was_compressed,
            source_version_id=processing_identity.version_id if processing_identity else "",
            source_etag=processing_identity.etag if processing_identity else "",
            source_sequencer=processing_identity.sequencer if processing_identity else "",
            processing_id=processing_identity.processing_id if processing_identity else "",
        )
        result = archive_case(
            analysis_result=analysis_result,
            config=config,
            source=source,
            sink_result=sink_result,
            s3_client=s3_client,
            dynamodb_client=get_dynamodb_client(),
            sqs_client=(
                get_sqs_client()
                if config.CASE_QA_ENABLED and config.CASE_EMBED_QUEUE_URL
                else None
            ),
            lambda_client=(
                get_lambda_client()
                if config.CASE_QA_ENABLED and not config.CASE_EMBED_QUEUE_URL
                else None
            ),
            processed_at=processed_at,
        )
        return {
            "status": result.status,
            "case_id": result.case_id,
            "case_envelope_key": result.case_envelope_key,
            "retrieval_status": result.retrieval_status,
            "source_completeness": result.source_completeness,
            "message": result.message,
        }
    except Exception as exc:
        if config.CASE_ARCHIVE_FAILURE_MODE == "fail_closed":
            raise
        logger.error("Case archive failed for %s: %s", source_key, exc)
        return {"status": "error", "message": str(exc)}


def get_splunk_api_token(config: Config | None = None) -> str:
    """Resolve Splunk API token from env var or Secrets Manager.

    Returns:
        API token value, or an empty string if not available.
    """
    # Backward-compatible direct env var support.
    direct_token = os.environ.get('SPLUNK_API_TOKEN')
    if direct_token:
        return direct_token

    config = config or load_config()
    secret_arn = (config.SPLUNK_API_TOKEN_SECRET_ARN or '').strip()
    secret_field = (config.SPLUNK_API_TOKEN_SECRET_FIELD or 'token').strip() or 'token'
    if not secret_arn or secret_arn == "*":
        return ""

    try:
        return resolve_secret_string(
            secret_arn=secret_arn,
            setting_name="Splunk API token",
            secret_field=secret_field,
            client=secretsmanager_client,
        )
    except Exception as e:
        logger.error("Error resolving Splunk API token from Secrets Manager: %s", str(e))
        return ""


def get_splunk_mcp_token(config: Config | None = None) -> str:
    """Resolve optional Splunk MCP bearer token from Secrets Manager."""

    config = config or load_config()
    secret_arn = (config.SPLUNK_MCP_AUTH_SECRET_ARN or '').strip()
    secret_field = (config.SPLUNK_MCP_AUTH_SECRET_FIELD or 'token').strip() or 'token'
    if not secret_arn or secret_arn == "*":
        return ""

    try:
        return resolve_secret_string(
            secret_arn=secret_arn,
            setting_name="Splunk MCP token",
            secret_field=secret_field,
            client=secretsmanager_client,
        )
    except Exception as e:
        logger.error("Error resolving Splunk MCP token from Secrets Manager: %s", str(e))
        return ""


def get_servicenow_api_token(config: Config | None = None) -> str:
    """Resolve ServiceNow API token from Secrets Manager."""

    config = config or load_config()
    secret_arn = (config.SERVICENOW_API_TOKEN_SECRET_ARN or '').strip()
    if not secret_arn or secret_arn == "*":
        return ""

    try:
        return resolve_secret_string(
            secret_arn=secret_arn,
            setting_name="ServiceNow API token",
            secret_field="token",
            client=secretsmanager_client,
        )
    except Exception as e:
        logger.error("Error resolving ServiceNow API token from Secrets Manager: %s", str(e))
        return ""


def get_servicenow_approval_hmac_key(config: Config | None = None) -> str:
    """Resolve ServiceNow approval HMAC key from Secrets Manager."""

    config = config or load_config()
    secret_arn = (config.SERVICENOW_APPROVAL_HMAC_SECRET_ARN or '').strip()
    try:
        return resolve_secret_string(
            secret_arn=secret_arn,
            setting_name="ServiceNow approval HMAC key",
            secret_field="hmac_key",
            fallback_fields=("secret", "token"),
            client=secretsmanager_client,
        )
    except Exception as e:
        logger.error("Error resolving ServiceNow approval HMAC key from Secrets Manager: %s", str(e))
        return ""


def get_elasticsearch_api_key(config: Config | None = None) -> str:
    """Resolve Elasticsearch API key from Secrets Manager."""

    config = config or load_config()
    secret_arn = (config.ELASTICSEARCH_API_KEY_SECRET_ARN or '').strip()
    if not secret_arn or secret_arn == "*":
        return ""

    try:
        return resolve_secret_string(
            secret_arn=secret_arn,
            setting_name="Elasticsearch API key",
            secret_field="api_key",
            fallback_fields=("token",),
            client=secretsmanager_client,
        )
    except Exception as e:
        logger.error("Error resolving Elasticsearch API key from Secrets Manager: %s", str(e))
        return ""


def write_to_splunk_rest(
    analysis_result: Dict[str, Any],
    source_key: str,
    config: Config | None = None,
) -> Dict[str, Any]:
    """Update notable comment via Splunk REST API using finding_id.

    Args:
        analysis_result: Full analysis result including markdown and TTPs.
        source_key: Original S3 key; filename stem is used as finding_id.

    Returns:
        Dict with sink operation status.
    """
    try:
        import requests

        config = config or load_config()
        splunk_base_url = config.SPLUNK_BASE_URL
        splunk_api_token = get_splunk_api_token(config)

        if not splunk_base_url or not splunk_api_token:
            logger.error(
                "SPLUNK_BASE_URL or Splunk token source not set "
                "(SPLUNK_API_TOKEN_SECRET_ARN or SPLUNK_API_TOKEN)"
            )
            return {"status": "error", "message": "Splunk REST credentials not configured"}

        try:
            finding_id = resolve_finding_id_for_writeback(analysis_result, source_key, config)
        except ValueError as exc:
            logger.warning("Could not resolve safe finding_id for source key %r: %s", source_key, exc)
            return {"status": "error", "message": str(exc)}

        reservation = begin_side_effect(
            config,
            operation="splunk_notable_update",
            key=finding_id,
        )
        if not reservation.should_execute:
            marker_status = (reservation.existing_marker or {}).get("status", "unknown")
            return {
                "status": "skipped",
                "message": f"Splunk notable update already reserved with status={marker_status}",
                "finding_id": finding_id,
                "idempotency_status": marker_status,
            }

        # Use the full markdown report as the comment
        comment = analysis_result["markdown"]

        # Build REST API request
        endpoint_path = config.SPLUNK_NOTABLE_UPDATE_PATH
        if not endpoint_path.startswith('/'):
            endpoint_path = f"/{endpoint_path}"
        splunk_base_url = validate_https_url(
            splunk_base_url,
            setting_name="SPLUNK_BASE_URL",
            allow_private=config.ALLOW_PRIVATE_OUTBOUND_ENDPOINTS,
        )
        rest_url = f"{splunk_base_url.rstrip('/')}{endpoint_path}"
        headers = {
            "Authorization": f"Bearer {splunk_api_token}",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        data = {
            "finding_id": finding_id,
            "comment": comment,
            "status": "2"  # In Progress (adjust as needed)
        }

        response = requests.post(rest_url, data=data, headers=headers, timeout=30, verify=True)
        response.raise_for_status()

        logger.info(f"Successfully updated notable via REST API: {response.status_code}")
        idempotency_recorded = complete_side_effect_success(
            reservation,
            metadata={"status_code": response.status_code, "finding_id": finding_id},
        )

        result = {
            "status": "success",
            "rest_response": response.text,
            "status_code": response.status_code,
            "finding_id": finding_id
        }
        if reservation.enabled:
            result["idempotency_recorded"] = idempotency_recorded
            if not idempotency_recorded:
                result["status"] = "uncertain"
                result["idempotency_status"] = "uncertain"
                result["idempotency_warning"] = (
                    "external Splunk update may have completed; marker reconciliation is required"
                )
        return result

    except Exception as e:
        if "reservation" in locals():
            marker_recorded = mark_side_effect_uncertain(
                reservation,
                metadata={
                    "external_success": "unknown",
                    "uncertain_reason": "splunk_request_outcome_unknown",
                },
            )
            if marker_recorded:
                return {
                    "status": "uncertain",
                    "message": str(e),
                    "idempotency_status": "uncertain",
                }
        logger.error(f"Error writing to Splunk REST: {str(e)}")
        return {"status": "error", "message": str(e)}


def handler(event, context):
    """Lambda handler for S3 events.

    Args:
        event: S3 event containing bucket and key information.
        context: Lambda context object.

    Returns:
        Dict with statusCode and processing results.
    """
    logger.info(f"Received event with {len(event.get('Records', []))} record(s)")
    config = load_config()

    results = []
    failed_sqs_message_ids: set[str] = set()
    deliveries: list[dict[str, Any]] = []
    for delivery in event.get("Records", []):
        try:
            nested_records, message_id = _s3_event_records(delivery)
        except ValueError as exc:
            message_id = str(delivery.get("messageId", "")).strip()
            if message_id:
                failed_sqs_message_ids.add(message_id)
            deliveries.append(
                {
                    "_delivery_error": str(exc),
                    "_sqs_message_id": str(delivery.get("messageId", "")).strip(),
                }
            )
            continue
        for nested_record in nested_records:
            prepared_record = dict(nested_record)
            if message_id:
                prepared_record["_sqs_message_id"] = message_id
            deliveries.append(prepared_record)

    for record in deliveries:
        try:
            if record.get("_delivery_error"):
                results.append(
                    {
                        "status": "terminal",
                        "message_id": record.get("_sqs_message_id", ""),
                        "error": record["_delivery_error"],
                    }
                )
                continue
            # Extract S3 bucket, key, and size from event
            bucket = record['s3']['bucket']['name']
            key = unquote_plus(record['s3']['object']['key'])
            size = record['s3']['object'].get('size', -1)

            logger.info(f"Processing s3://{bucket}/{key} (size={size})")

            # Skip folder markers, placeholders, and empty objects
            skip, reason = should_skip_object(key, size)
            if skip:
                logger.info(f"Skipping s3://{bucket}/{key}: {reason}")
                results.append({
                    "key": key,
                    "status": "skipped",
                    "reason": reason
                })
                continue

            # Read object from S3
            get_object_kwargs = {"Bucket": bucket, "Key": key}
            version_id = str(record["s3"]["object"].get("versionId", "") or "").strip()
            if version_id:
                get_object_kwargs["VersionId"] = version_id
            response = s3_client.get_object(**get_object_kwargs)
            processing_identity = _processing_identity(record, response, bucket, key)
            content_encoding = response.get('ContentEncoding')
            max_input_bytes = get_max_decompressed_input_bytes(config)
            compressed = is_gzip_input(key, content_encoding)
            read_limit = get_max_compressed_input_bytes(config) if compressed else max_input_bytes
            response_size = response.get("ContentLength")
            if response_size is not None and int(response_size) > read_limit:
                raise ValueError(f"S3 object {key!r} exceeds configured input byte limit ({read_limit})")
            if (
                isinstance(size, int)
                and size > max_input_bytes
                and not compressed
            ):
                raise ValueError(
                    f"S3 object {key!r} exceeds MAX_DECOMPRESSED_INPUT_BYTES ({max_input_bytes})"
                )
            decoded_notable = decode_s3_notable_object(
                key,
                read_bounded_bytes(
                    response['Body'],
                    max_bytes=read_limit,
                    setting_name=(
                        "MAX_COMPRESSED_INPUT_BYTES" if compressed else "MAX_DECOMPRESSED_INPUT_BYTES"
                    ),
                ),
                content_encoding,
                config,
            )
            content = decoded_notable.content

            logger.info(
                "Read %d characters from S3%s",
                len(content),
                " after gzip decompression" if decoded_notable.was_compressed else "",
            )

            # Keep the alert payload format-agnostic:
            # - valid JSON stays JSON
            # - text stays text
            content_type = decoded_notable.content_type
            alert_payload = normalize_notable(content, content_type)

            # Initialize analyzer
            model_id = config.BEDROCK_MODEL_ID
            if not model_id:
                raise ValueError("BEDROCK_MODEL_ID is not configured")
            logger.info(f"Initializing analyzer with model: {model_id}")
            analyzer = BedrockAnalyzer(model_id=model_id)
            degraded_enrichments: list[str] = []

            # Format alert text
            alert_text = analyzer.format_alert_input(
                alert_payload,
                raw_content=content,
                content_type=content_type,
            )

            rag_result = _optional_call(
                "soc_rag",
                lambda: retrieve_soc_context(alert_text, config),
                RetrievalResult(status="failed", message="SOC RAG enrichment unavailable"),
                degraded_enrichments,
            )

            closed_ticket_grounding = retrieve_historical_closed_tickets_for_first_pass(
                config,
                alert_text,
            )
            if closed_ticket_grounding.status == "degraded":
                degraded_enrichments.append("closed_ticket_rag")

            # Run analysis
            start_time = time.time()
            logger.info("Starting TTP analysis")
            scored_ttps = analyzer.analyze_ttp(
                alert_text,
                advisory_context=rag_result.context,
                historical_closed_tickets_context=closed_ticket_grounding.context,
            )

            # Get the full LLM response
            llm_response = analyzer.last_llm_response or {}
            if isinstance(llm_response, dict):
                metadata = llm_response.setdefault("metadata", {})
                if isinstance(metadata, dict):
                    metadata["rag_status"] = rag_result.status
                    metadata["rag_snippet_count"] = rag_result.snippet_count
                    if rag_result.message:
                        metadata["rag_message"] = rag_result.message
                    metadata.update(closed_ticket_grounding.metadata)

            if (
                isinstance(llm_response, dict)
                and config.INVESTIGATION_QUERY_BACKEND == "splunk"
                and config.SPL_QUERY_GENERATION_ENABLED
            ):
                spl_grounding = _optional_call(
                    "spl_query_grounding",
                    lambda: retrieve_spl_query_grounding(
                        alert_text=alert_text,
                        hypotheses=llm_response.get("competing_hypotheses", []),
                        config=config,
                    ),
                    SplGroundingResult(status="failed", message="SPL grounding unavailable"),
                    degraded_enrichments,
                )
                llm_response = _optional_call(
                    "spl_query_generation",
                    lambda: analyzer.generate_spl_queries(
                        alert_text=alert_text,
                        analysis_result=llm_response,
                        config=config,
                        soc_operational_context=rag_result.context,
                        spl_query_grounding_context=spl_grounding.context,
                    ),
                    llm_response,
                    degraded_enrichments,
                )
                metadata = llm_response.setdefault("metadata", {})
                if isinstance(metadata, dict):
                    metadata["spl_query_rag_status"] = spl_grounding.status
                    metadata["spl_query_rag_snippet_count"] = spl_grounding.snippet_count
                    if spl_grounding.message:
                        metadata["spl_query_rag_message"] = spl_grounding.message

            if (
                isinstance(llm_response, dict)
                and config.INVESTIGATION_QUERY_BACKEND == "splunk"
                and config.INVESTIGATION_QUERY_EXECUTION_ENABLED
            ):
                mcp_client = None
                if config.INVESTIGATION_QUERY_EXECUTOR == "mcp" and config.SPLUNK_MCP_ENDPOINT:
                    mcp_client = HttpSplunkMcpClient(
                        endpoint=config.SPLUNK_MCP_ENDPOINT,
                        bearer_token=get_splunk_mcp_token(config),
                        timeout_seconds=config.SPLUNK_MCP_HTTP_TIMEOUT_SECONDS,
                        allow_private=config.ALLOW_PRIVATE_OUTBOUND_ENDPOINTS,
                    )
                query_results = _optional_call(
                    "spl_query_execution",
                    lambda: execute_hypothesis_queries(
                        llm_response,
                        config=config,
                        api_token=get_splunk_api_token(config),
                        mcp_client=mcp_client,
                    ),
                    [],
                    degraded_enrichments,
                )
                llm_response["investigation_query_results"] = query_results
                llm_response = enrich_analysis_with_query_results(llm_response, query_results)
                if config.QUERY_RESULT_INTERPRETATION_ENABLED:
                    llm_response = _optional_call(
                        "spl_query_interpretation",
                        lambda: analyzer.interpret_query_results(
                            alert_text=alert_text,
                            analysis_result=llm_response,
                            config=config,
                        ),
                        llm_response,
                        degraded_enrichments,
                    )
                metadata = llm_response.setdefault("metadata", {})
                if isinstance(metadata, dict):
                    metadata["investigation_query_backend"] = config.INVESTIGATION_QUERY_BACKEND
                    metadata["investigation_query_executor"] = config.INVESTIGATION_QUERY_EXECUTOR
                    metadata["investigation_query_result_count"] = len(query_results)

            if (
                isinstance(llm_response, dict)
                and config.INVESTIGATION_QUERY_BACKEND == "elasticsearch"
                and config.ELASTIC_QUERY_GENERATION_ENABLED
            ):
                elastic_grounding = _optional_call(
                    "elasticsearch_grounding",
                    lambda: retrieve_elasticsearch_grounding(
                        alert_text=alert_text,
                        hypotheses=llm_response.get("competing_hypotheses", []),
                        config=config,
                    ),
                    ElasticsearchGroundingResult(status="failed", message="Elasticsearch grounding unavailable"),
                    degraded_enrichments,
                )
                llm_response = _optional_call(
                    "elasticsearch_query_generation",
                    lambda: analyzer.generate_elastic_queries(
                        alert_text=alert_text,
                        analysis_result=llm_response,
                        config=config,
                        soc_operational_context=rag_result.context,
                        elasticsearch_grounding_context=elastic_grounding.context,
                    ),
                    llm_response,
                    degraded_enrichments,
                )
                metadata = llm_response.setdefault("metadata", {})
                if isinstance(metadata, dict):
                    metadata["elasticsearch_grounding_status"] = elastic_grounding.status
                    metadata["elasticsearch_grounding_snippet_count"] = elastic_grounding.snippet_count
                    if elastic_grounding.message:
                        metadata["elasticsearch_grounding_message"] = elastic_grounding.message

            if (
                isinstance(llm_response, dict)
                and config.INVESTIGATION_QUERY_BACKEND == "elasticsearch"
                and config.INVESTIGATION_QUERY_EXECUTION_ENABLED
            ):
                query_results = _optional_call(
                    "elasticsearch_query_execution",
                    lambda: execute_hypothesis_elasticsearch_queries(
                        llm_response,
                        config=config,
                        api_key=get_elasticsearch_api_key(config),
                    ),
                    [],
                    degraded_enrichments,
                )
                llm_response["investigation_query_results"] = query_results
                llm_response = enrich_analysis_with_query_results(llm_response, query_results)
                if config.QUERY_RESULT_INTERPRETATION_ENABLED:
                    llm_response = _optional_call(
                        "elasticsearch_query_interpretation",
                        lambda: analyzer.interpret_query_results(
                            alert_text=alert_text,
                            analysis_result=llm_response,
                            config=config,
                        ),
                        llm_response,
                        degraded_enrichments,
                    )
                metadata = llm_response.setdefault("metadata", {})
                if isinstance(metadata, dict):
                    metadata["investigation_query_backend"] = config.INVESTIGATION_QUERY_BACKEND
                    metadata["investigation_query_executor"] = "elasticsearch"
                    metadata["investigation_query_result_count"] = len(query_results)

            analysis_status = "degraded" if degraded_enrichments else "success"
            if isinstance(llm_response, dict):
                metadata = llm_response.setdefault("metadata", {})
                if isinstance(metadata, dict):
                    metadata["analysis_status"] = analysis_status
                    if degraded_enrichments:
                        metadata["degraded_enrichments"] = sorted(set(degraded_enrichments))

            if isinstance(llm_response, dict) and (
                config.SERVICENOW_DRAFT_ENABLED or config.SERVICENOW_CREATE_ENABLED
            ):
                finding_id = extract_finding_id_from_s3_key(key)
                draft_result = build_servicenow_incident_draft(
                    llm_response,
                    config=config,
                    notable_id=source_key_stem(key),
                    finding_id=finding_id,
                )
                servicenow_section = {"draft": draft_result}
                if (
                    config.SERVICENOW_CREATE_ENABLED
                    and draft_result.get("status") == "success"
                    and isinstance(draft_result.get("incident_payload"), dict)
                ):
                    servicenow_section["create"] = create_servicenow_incident(
                        draft_result["incident_payload"],
                        config=config,
                        api_token=get_servicenow_api_token(config),
                        approval=extract_servicenow_create_approval(alert_payload),
                        approval_hmac_key=get_servicenow_approval_hmac_key(config),
                    )
                llm_response["servicenow_section"] = servicenow_section

            # Generate markdown report
            logger.info("Generating markdown report")
            markdown = generate_markdown_report(alert_text, llm_response, scored_ttps)
            html = None
            if config.HTML_REPORT_ENABLED:
                html = generate_html_report(alert_text, llm_response, scored_ttps, markdown)

            end_time = time.time()

            # Build analysis result
            analysis_result = {
                "markdown": markdown,
                "html": html,
                "llm_response": llm_response,
                "scored_ttps": scored_ttps,
                "alert_payload": alert_payload,
                "meta": {
                    "model_id": model_id,
                    "execution_time_seconds": round(end_time - start_time, 2),
                    "ttp_count": len(scored_ttps),
                    "source_bucket": bucket,
                    "source_key": key,
                    "processing_id": processing_identity.processing_id,
                    "analysis_status": analysis_status,
                    "degraded_enrichments": sorted(set(degraded_enrichments)),
                }
            }

            # Route to configured sink
            sink_mode = config.SPLUNK_SINK_MODE
            logger.info(f"Routing to sink: {sink_mode}")

            if sink_mode == 's3':
                sink_result = write_to_s3_sink(
                    key,
                    markdown,
                    analysis_result,
                    config,
                    processing_identity,
                )
            elif sink_mode == 'notable_rest':
                sink_result = write_to_notable_rest_sink(
                    key,
                    analysis_result,
                    config,
                    processing_identity,
                )
            else:
                logger.error(f"Unknown sink mode: {sink_mode}")
                sink_result = {"sink": sink_mode, "status": "error", "message": "Unknown sink mode"}

            archive_result = write_case_archive_after_sink(
                analysis_result=analysis_result,
                config=config,
                source_bucket=bucket,
                source_key=key,
                decoded_notable=decoded_notable,
                sink_result=sink_result,
                processed_at=record.get("eventTime"),
                processing_identity=processing_identity,
            )
            if config.CASE_ARCHIVE_ENABLED or archive_result.get("status") != "skipped":
                sink_result["case_archive_result"] = archive_result

            record_status = "success" if sink_result.get("status") == "success" else "error"
            results.append({
                "key": key,
                "status": record_status,
                "ttp_count": len(scored_ttps),
                "sink_result": sink_result
            })
            if record_status != "success":
                message_id = str(record.get("_sqs_message_id", "")).strip()
                if message_id:
                    failed_sqs_message_ids.add(message_id)
                logger.error("Sink failed for %s: %s", key, sink_result)
            else:
                logger.info(f"Successfully processed {key}")

        except Exception as e:
            logger.error(f"Error processing record: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            retryable = getattr(e, "retryable", not isinstance(e, (ValueError, KeyError, TypeError)))
            message_id = str(record.get("_sqs_message_id", "")).strip()
            if message_id:
                failed_sqs_message_ids.add(message_id)
            results.append({
                "key": unquote_plus(record.get('s3', {}).get('object', {}).get('key', 'unknown')),
                "status": "retryable_error" if retryable else "terminal_error",
                "error": str(e),
                "message_id": message_id,
            })

    failed_count = sum(1 for item in results if item.get("status") == "error")
    if failed_sqs_message_ids:
        return {
            "statusCode": 200,
            "batchItemFailures": [
                {"itemIdentifier": message_id}
                for message_id in sorted(failed_sqs_message_ids)
            ],
            "body": json.dumps({"processed": len(results), "results": results}),
        }
    failed_count += sum(
        1 for item in results if item.get("status") in {"retryable_error", "terminal_error"}
        and not item.get("message_id")
    )
    if failed_count:
        raise RuntimeError(f"Failed to process {failed_count} S3 record(s)")

    return {
        'statusCode': 200,
        'body': json.dumps({
            'processed': len(results),
            'results': results
        })
    }
