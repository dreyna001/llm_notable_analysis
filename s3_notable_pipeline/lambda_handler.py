"""
Lambda handler for S3-triggered notable analysis pipeline.

Processes notables from S3, analyzes with Bedrock, and outputs to
configurable sinks (S3 or Splunk notable REST API).
"""

import json
import os
import logging
import time
import traceback
import boto3
from pathlib import Path, PurePosixPath
from urllib.parse import unquote_plus
from typing import Dict, Any

from ttp_analyzer import BedrockAnalyzer
from markdown_generator import generate_markdown_report

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize S3 client
s3_client = boto3.client('s3')
secretsmanager_client = boto3.client('secretsmanager')

# Placeholder filenames to skip (case-insensitive basename match)
PLACEHOLDER_FILENAMES = frozenset({'.keep', '.gitkeep', '_success', '.placeholder'})


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


def extract_finding_id_from_s3_key(source_key: str) -> str:
    """Derive finding_id from S3 object filename (without extension).

    Args:
        source_key: S3 object key (may be URL-encoded in event payload).

    Returns:
        Filename stem used as finding_id. Returns empty string if no basename.
    """
    decoded_key = unquote_plus(source_key or "")
    filename = PurePosixPath(decoded_key).name
    if not filename:
        return ""
    return Path(filename).stem


def write_to_s3_sink(source_key: str, markdown: str, analysis_result: Dict[str, Any]) -> Dict[str, Any]:
    """Write markdown analysis report to S3 output bucket.
    
    Args:
        source_key: Original S3 key from input bucket.
        markdown: Generated markdown report.
        analysis_result: Full analysis result (not written to S3, kept for signature compatibility).
        
    Returns:
        Dict with sink operation status.
    """
    try:
        output_bucket = os.environ.get('OUTPUT_BUCKET_NAME')
        output_prefix = os.environ.get('OUTPUT_PREFIX', 'reports')
        
        if not output_bucket:
            logger.error("OUTPUT_BUCKET_NAME not set for s3/notable_rest sink mode")
            return {"status": "error", "message": "OUTPUT_BUCKET_NAME not configured"}
        
        # Generate output key based on source key
        base_name = source_key.split('/')[-1].rsplit('.', 1)[0]
        md_key = f"{output_prefix}/{base_name}.md"
        
        # Write markdown report
        s3_client.put_object(
            Bucket=output_bucket,
            Key=md_key,
            Body=markdown.encode('utf-8'),
            ContentType='text/markdown'
        )
        logger.info(f"Wrote markdown report to s3://{output_bucket}/{md_key}")
        
        return {
            "status": "success",
            "markdown_key": md_key,
            "bucket": output_bucket
        }
        
    except Exception as e:
        logger.error(f"Error writing to S3 sink: {str(e)}")
        return {"status": "error", "message": str(e)}


def write_to_notable_rest_sink(source_key: str, analysis_result: Dict[str, Any]) -> Dict[str, Any]:
    """Write the markdown report to S3, then update the Splunk notable via REST.

    Args:
        source_key: Original S3 key; reused for report naming and finding_id derivation.
        analysis_result: Full analysis result including markdown and TTPs.

    Returns:
        Dict with the combined sink operation status and per-sink results.
    """
    s3_result = write_to_s3_sink(source_key, analysis_result["markdown"], analysis_result)
    rest_result = write_to_splunk_rest(analysis_result, source_key)
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


def get_splunk_api_token() -> str:
    """Resolve Splunk API token from env var or Secrets Manager.

    Returns:
        API token value, or an empty string if not available.
    """
    # Backward-compatible direct env var support.
    direct_token = os.environ.get('SPLUNK_API_TOKEN')
    if direct_token:
        return direct_token

    secret_arn = (os.environ.get('SPLUNK_API_TOKEN_SECRET_ARN') or '').strip()
    secret_field = (os.environ.get('SPLUNK_API_TOKEN_SECRET_FIELD') or 'token').strip() or 'token'
    if not secret_arn:
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


def write_to_splunk_rest(analysis_result: Dict[str, Any], source_key: str) -> Dict[str, Any]:
    """Update notable comment via Splunk REST API using finding_id.
    
    Args:
        analysis_result: Full analysis result including markdown and TTPs.
        source_key: Original S3 key; filename stem is used as finding_id.
        
    Returns:
        Dict with sink operation status.
    """
    try:
        import requests
        
        splunk_base_url = os.environ.get('SPLUNK_BASE_URL')
        splunk_api_token = get_splunk_api_token()

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
        endpoint_path = os.environ.get('SPLUNK_NOTABLE_UPDATE_PATH', '/services/notable_update')
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
            content = response['Body'].read().decode('utf-8')
            
            logger.info(f"Read {len(content)} characters from S3")
            
            # Keep the alert payload format-agnostic:
            # - valid JSON stays JSON
            # - text stays text
            content_type = 'json' if key.lower().endswith('.json') else 'text'
            alert_payload = normalize_notable(content, content_type)
            
            # Initialize analyzer
            model_id = os.environ.get('BEDROCK_MODEL_ID')
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
            
            # Run analysis
            start_time = time.time()
            logger.info("Starting TTP analysis")
            scored_ttps = analyzer.analyze_ttp(alert_text)
            
            # Get the full LLM response
            llm_response = analyzer.last_llm_response or {}
            
            # Generate markdown report
            logger.info("Generating markdown report")
            markdown = generate_markdown_report(alert_text, llm_response, scored_ttps)
            
            end_time = time.time()
            
            # Build analysis result
            analysis_result = {
                "markdown": markdown,
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
            sink_mode = os.environ.get('SPLUNK_SINK_MODE', 's3')
            logger.info(f"Routing to sink: {sink_mode}")
            
            if sink_mode == 's3':
                sink_result = write_to_s3_sink(key, markdown, analysis_result)
            elif sink_mode == 'notable_rest':
                sink_result = write_to_notable_rest_sink(key, analysis_result)
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

