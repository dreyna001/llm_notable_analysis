"""
Lambda handler for S3-triggered notable analysis pipeline.

Processes notables from S3, analyzes with Bedrock, and outputs to
configurable sinks (S3 or Splunk notable REST API).
"""

import gzip
import io
import json
import os
import logging
import time
import traceback
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote_plus
from typing import Dict, Any

from .aws_clients import s3_client as make_s3_client
from .aws_clients import secretsmanager_client as make_secretsmanager_client
from .bedrock_kb_retrieval import retrieve_soc_context
from .config import Config, load_config
from .html_generator import generate_html_report
from .ttp_analyzer import BedrockAnalyzer
from .markdown_generator import generate_markdown_report

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients through the centralized factory so tests can use
# mocked clients and local integration can use AWS_ENDPOINT_URL.
s3_client = make_s3_client()
secretsmanager_client = make_secretsmanager_client()

# Placeholder filenames to skip (case-insensitive basename match)
PLACEHOLDER_FILENAMES = frozenset({'.keep', '.gitkeep', '_success', '.placeholder'})
DEFAULT_MAX_DECOMPRESSED_INPUT_BYTES = 1_048_576
GZIP_CONTENT_ENCODINGS = frozenset({'gzip', 'x-gzip'})


@dataclass(frozen=True)
class DecodedNotable:
    """Decoded notable content plus metadata needed by the analysis flow."""

    content: str
    content_type: str
    was_compressed: bool


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
    if was_compressed:
        try:
            content_bytes = decompress_gzip_bounded(
                raw_bytes,
                get_max_decompressed_input_bytes(config),
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
        base_name = source_key_stem(source_key)
        md_key = f"{output_prefix}/{base_name}.md"
        json_key = f"{output_prefix}/{base_name}.json"
        html_key = f"{output_prefix}/{base_name}.html"

        llm_response = analysis_result.get("llm_response")
        if llm_response is None:
            llm_response = {}
        json_body = json.dumps(llm_response, ensure_ascii=False, indent=2, default=str)

        # Write markdown report
        s3_client.put_object(
            Bucket=output_bucket,
            Key=md_key,
            Body=markdown.encode('utf-8'),
            ContentType='text/markdown'
        )
        logger.info(f"Wrote markdown report to s3://{output_bucket}/{md_key}")

        s3_client.put_object(
            Bucket=output_bucket,
            Key=json_key,
            Body=json_body.encode('utf-8'),
            ContentType="application/json",
        )
        logger.info(f"Wrote Bedrock JSON to s3://{output_bucket}/{json_key}")

        html_report = analysis_result.get("html")
        if config.HTML_REPORT_ENABLED and isinstance(html_report, str) and html_report:
            s3_client.put_object(
                Bucket=output_bucket,
                Key=html_key,
                Body=html_report.encode('utf-8'),
                ContentType="text/html",
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
        
    except Exception as e:
        logger.error(f"Error writing to S3 sink: {str(e)}")
        return {"status": "error", "message": str(e)}


def write_to_notable_rest_sink(
    source_key: str,
    analysis_result: Dict[str, Any],
    config: Config | None = None,
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
    )
    rest_result = write_to_splunk_rest(analysis_result, source_key, config)
    combined_status = (
        "success"
        if s3_result.get("status") == "success" and rest_result.get("status") == "success"
        else "error"
    )

    return {
        "status": combined_status,
        "s3_result": s3_result,
        "rest_result": rest_result,
    }


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
        secret_response = secretsmanager_client.get_secret_value(SecretId=secret_arn)
        secret_string = secret_response.get('SecretString') or ''
        if not secret_string:
            logger.error("Splunk API token secret has no SecretString content")
            return ""

        try:
            parsed = json.loads(secret_string)
        except json.JSONDecodeError:
            # Allow plain-text secret values.
            return secret_string

        if isinstance(parsed, dict):
            token_value = parsed.get(secret_field)
            if isinstance(token_value, str) and token_value.strip():
                return token_value
            logger.error(
                "Splunk API token secret JSON missing required field '%s'",
                secret_field,
            )
            return ""

        logger.error("Splunk API token secret JSON must be an object or plain string")
        return ""
    except Exception as e:
        logger.error("Error resolving Splunk API token from Secrets Manager: %s", str(e))
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

        finding_id = extract_finding_id_from_s3_key(source_key)
        if not finding_id:
            logger.warning(f"Could not derive finding_id from source key: {source_key!r}")
            return {"status": "error", "message": "Cannot derive finding_id from source key"}
        
        # Use the full markdown report as the comment
        comment = analysis_result["markdown"]
        
        # Build REST API request
        endpoint_path = config.SPLUNK_NOTABLE_UPDATE_PATH
        if not endpoint_path.startswith('/'):
            endpoint_path = f"/{endpoint_path}"
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
        
        return {
            "status": "success",
            "rest_response": response.text,
            "status_code": response.status_code,
            "finding_id": finding_id
        }
        
    except Exception as e:
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
    
    for record in event.get('Records', []):
        try:
            # Extract S3 bucket, key, and size from event
            bucket = record['s3']['bucket']['name']
            key = record['s3']['object']['key']
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
            response = s3_client.get_object(Bucket=bucket, Key=key)
            decoded_notable = decode_s3_notable_object(
                key,
                response['Body'].read(),
                response.get('ContentEncoding'),
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
            
            # Format alert text
            alert_text = analyzer.format_alert_input(
                alert_payload,
                raw_content=content,
                content_type=content_type,
            )

            rag_result = retrieve_soc_context(alert_text, config)
            
            # Run analysis
            start_time = time.time()
            logger.info("Starting TTP analysis")
            scored_ttps = analyzer.analyze_ttp(
                alert_text,
                advisory_context=rag_result.context,
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
                "meta": {
                    "model_id": model_id,
                    "execution_time_seconds": round(end_time - start_time, 2),
                    "ttp_count": len(scored_ttps),
                    "source_bucket": bucket,
                    "source_key": key
                }
            }
            
            # Route to configured sink
            sink_mode = config.SPLUNK_SINK_MODE
            logger.info(f"Routing to sink: {sink_mode}")
            
            if sink_mode == 's3':
                sink_result = write_to_s3_sink(key, markdown, analysis_result, config)
            elif sink_mode == 'notable_rest':
                sink_result = write_to_notable_rest_sink(key, analysis_result, config)
            else:
                logger.error(f"Unknown sink mode: {sink_mode}")
                sink_result = {"sink": sink_mode, "status": "error", "message": "Unknown sink mode"}
            
            results.append({
                "key": key,
                "status": "success",
                "ttp_count": len(scored_ttps),
                "sink_result": sink_result
            })
            
            logger.info(f"Successfully processed {key}")
            
        except Exception as e:
            logger.error(f"Error processing record: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            results.append({
                "key": record.get('s3', {}).get('object', {}).get('key', 'unknown'),
                "status": "error",
                "error": str(e)
            })
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'processed': len(results),
            'results': results
        })
    }

