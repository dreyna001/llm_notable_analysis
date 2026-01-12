"""
Lambda handler for S3-triggered notable analysis pipeline.

Processes notables from S3, analyzes with Bedrock Nova Pro, and outputs to
configurable sinks (S3, Splunk HEC, or Splunk REST API).
"""

import json
import os
import logging
import time
import boto3
from pathlib import Path
from typing import Dict, Any

from ttp_analyzer import BedrockAnalyzer
from markdown_generator import generate_markdown_report

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize S3 client
s3_client = boto3.client('s3')

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


def normalize_notable(content: str, content_type: str = 'text') -> Dict[str, Any]:
    """Normalize S3 notable content into internal alert structure.
    
    Mirrors the normalize_alert() function from backend.py, adapted for S3 objects.
    
    Args:
        content: Raw content from S3 object (JSON string or plain text).
        content_type: Type hint for content ('json' or 'text').
        
    Returns:
        Dict with normalized alert containing summary, risk_index, and raw_log.
    """
    summary = ""
    risk_index = {
        "risk_score": "N/A",
        "source_product": "S3_Pipeline",
        "threat_category": "N/A"
    }
    raw_log = {}
    
    # Try to parse as JSON first
    if content_type == 'json' or content.strip().startswith('{'):
        try:
            parsed_json = json.loads(content)
            if isinstance(parsed_json, dict):
                summary = "S3-submitted notable"
                raw_log = parsed_json
            else:
                summary = content[:400] if len(content) > 400 else content
                raw_log = {"raw_event": content}
        except json.JSONDecodeError:
            logger.warning("Failed to parse content as JSON, treating as raw text")
            summary = content[:400] if len(content) > 400 else content
            raw_log = {"raw_event": content}
    else:
        summary = content[:400] if len(content) > 400 else content
        raw_log = {"raw_event": content}
    
    return {
        "summary": summary,
        "risk_index": risk_index,
        "raw_log": raw_log
    }


def write_to_s3_sink(source_key: str, markdown: str, analysis_result: Dict[str, Any]) -> Dict[str, Any]:
    """Write markdown analysis report to S3 output bucket (test mode).
    
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
            logger.error("OUTPUT_BUCKET_NAME not set for s3 sink mode")
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


def write_to_splunk_hec(analysis_result: Dict[str, Any], original_notable: Dict[str, Any]) -> Dict[str, Any]:
    """Write analysis results to Splunk HTTP Event Collector.
    
    Args:
        analysis_result: Full analysis result including markdown and TTPs.
        original_notable: Not used (kept for signature compatibility).
        
    Returns:
        Dict with sink operation status.
    """
    try:
        import requests
        
        hec_url = os.environ.get('SPLUNK_HEC_URL')
        hec_token = os.environ.get('SPLUNK_HEC_TOKEN')
        
        if not hec_url or not hec_token:
            logger.error("SPLUNK_HEC_URL or SPLUNK_HEC_TOKEN not set")
            return {"status": "error", "message": "HEC credentials not configured"}
        
        # Build HEC event payload
        event_payload = {
            "event": {
                "notable_analysis": {
                    "markdown": analysis_result["markdown"],
                    "ttp_count": analysis_result["meta"]["ttp_count"],
                    "scored_ttps": analysis_result["scored_ttps"],
                    "execution_time": analysis_result["meta"]["execution_time_seconds"],
                    "model_id": analysis_result["meta"]["model_id"]
                }
            },
            "sourcetype": "notable:analysis",
            "source": "aws:lambda:notable-analyzer"
        }
        
        # POST to HEC
        headers = {
            "Authorization": f"Splunk {hec_token}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(hec_url, json=event_payload, headers=headers, timeout=30)
        response.raise_for_status()
        
        logger.info(f"Successfully posted to Splunk HEC: {response.status_code}")
        
        return {
            "status": "success",
            "hec_response": response.json() if response.text else {},
            "status_code": response.status_code
        }
        
    except Exception as e:
        logger.error(f"Error writing to Splunk HEC: {str(e)}")
        return {"status": "error", "message": str(e)}


def write_to_splunk_rest(analysis_result: Dict[str, Any], original_notable: Dict[str, Any]) -> Dict[str, Any]:
    """Update notable via Splunk REST API /services/notable_update.
    
    Args:
        analysis_result: Full analysis result including markdown and TTPs.
        original_notable: Original notable data from S3 (should contain notable_id or search_name).
        
    Returns:
        Dict with sink operation status.
    """
    try:
        import requests
        
        splunk_base_url = os.environ.get('SPLUNK_BASE_URL')
        splunk_api_token = os.environ.get('SPLUNK_API_TOKEN')
        
        if not splunk_base_url or not splunk_api_token:
            logger.error("SPLUNK_BASE_URL or SPLUNK_API_TOKEN not set")
            return {"status": "error", "message": "Splunk REST credentials not configured"}
        
        # Extract notable identifier (assume it's in the original notable data)
        notable_id = original_notable.get('notable_id') or original_notable.get('event_id')
        search_name = original_notable.get('search_name')
        
        if not notable_id and not search_name:
            logger.warning("No notable_id or search_name found in original notable")
            return {"status": "error", "message": "Cannot identify notable to update"}
        
        # Use the full markdown report as the comment
        comment = analysis_result["markdown"]
        
        # Build REST API request
        rest_url = f"{splunk_base_url}/services/notable_update"
        headers = {
            "Authorization": f"Bearer {splunk_api_token}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        data = {
            "comment": comment,
            "status": "2"  # In Progress (adjust as needed)
        }
        
        if notable_id:
            data["ruleUIDs"] = notable_id
        elif search_name:
            data["search_name"] = search_name
        
        response = requests.post(rest_url, data=data, headers=headers, timeout=30, verify=True)
        response.raise_for_status()
        
        logger.info(f"Successfully updated notable via REST API: {response.status_code}")
        
        return {
            "status": "success",
            "rest_response": response.text,
            "status_code": response.status_code,
            "notable_id": notable_id or search_name
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
            
            # Normalize the notable
            alert_obj = normalize_notable(content)
            
            # Initialize analyzer
            model_id = os.environ.get('BEDROCK_MODEL_ID', 'amazon.nova-pro-v1:0')
            logger.info(f"Initializing analyzer with model: {model_id}")
            analyzer = BedrockAnalyzer(model_id=model_id)
            
            # Format alert text
            alert_text = analyzer.format_alert_input(
                alert_obj['summary'],
                alert_obj['risk_index'],
                alert_obj['raw_log']
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
            elif sink_mode == 'hec':
                sink_result = write_to_splunk_hec(analysis_result, alert_obj.get('raw_log', {}))
            elif sink_mode == 'notable_rest':
                sink_result = write_to_splunk_rest(analysis_result, alert_obj.get('raw_log', {}))
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
            import traceback
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

