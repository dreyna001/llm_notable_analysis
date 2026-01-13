"""
Simplified Lambda handler for S3-triggered notable analysis pipeline.

- Reads UTF-8 (text or JSON) from S3 under incoming/
- Runs a reduced LLM prompt that focuses on alert-local evidence
- Writes JSON output to S3 (no markdown generation)
"""

import json
import os
import logging
import time
import boto3
from typing import Dict, Any

from ttp_analyzer import SimpleBedrockAnalyzer

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client("s3")

# Placeholder filenames to skip (case-insensitive basename match)
PLACEHOLDER_FILENAMES = frozenset({".keep", ".gitkeep", "_success", ".placeholder"})


def should_skip_object(key: str, size: int) -> tuple[bool, str]:
    if key.endswith("/"):
        return True, "folder marker (key ends with '/')"
    if size == 0:
        return True, "empty object (0 bytes)"
    basename = key.rsplit("/", 1)[-1].lower()
    if basename in PLACEHOLDER_FILENAMES:
        return True, f"placeholder file ({basename})"
    return False, ""


def normalize_notable(content: str) -> Dict[str, Any]:
    """Normalize S3 object content into a minimal alert structure."""
    # Try JSON first; otherwise treat as raw text
    raw_log: Dict[str, Any]
    if content.strip().startswith("{"):
        try:
            parsed = json.loads(content)
            raw_log = parsed if isinstance(parsed, dict) else {"raw_event": content}
        except json.JSONDecodeError:
            raw_log = {"raw_event": content}
    else:
        raw_log = {"raw_event": content}

    return {
        "summary": "S3-submitted notable",
        "risk_index": {
            "risk_score": "N/A",
            "source_product": "S3_Pipeline_Simple",
            "threat_category": "N/A",
        },
        "raw_log": raw_log,
    }


def write_json_to_s3(source_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    output_bucket = os.environ.get("OUTPUT_BUCKET_NAME")
    output_prefix = os.environ.get("OUTPUT_PREFIX", "reports")
    if not output_bucket:
        return {"status": "error", "message": "OUTPUT_BUCKET_NAME not configured"}

    base_name = source_key.split("/")[-1].rsplit(".", 1)[0]
    out_key = f"{output_prefix}/{base_name}.json"

    body = json.dumps(payload, ensure_ascii=True, indent=2).encode("utf-8")
    s3_client.put_object(
        Bucket=output_bucket,
        Key=out_key,
        Body=body,
        ContentType="application/json",
    )
    return {"status": "success", "bucket": output_bucket, "key": out_key}


def handler(event, context):
    logger.info(f"Received event with {len(event.get('Records', []))} record(s)")

    results = []
    for record in event.get("Records", []):
        try:
            bucket = record["s3"]["bucket"]["name"]
            key = record["s3"]["object"]["key"]
            size = record["s3"]["object"].get("size", -1)

            logger.info(f"Processing s3://{bucket}/{key} (size={size})")

            skip, reason = should_skip_object(key, size)
            if skip:
                logger.info(f"Skipping s3://{bucket}/{key}: {reason}")
                results.append({"key": key, "status": "skipped", "reason": reason})
                continue

            response = s3_client.get_object(Bucket=bucket, Key=key)
            content = response["Body"].read().decode("utf-8")
            logger.info(f"Read {len(content)} characters from S3")

            alert_obj = normalize_notable(content)

            model_id = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-pro-v1:0")
            analyzer = SimpleBedrockAnalyzer(model_id=model_id)

            alert_text = analyzer.format_alert_input(
                alert_obj["summary"], alert_obj["risk_index"], alert_obj["raw_log"]
            )

            start_time = time.time()
            analysis = analyzer.analyze(alert_text)
            end_time = time.time()

            output = {
                "analysis": analysis,
                "meta": {
                    "model_id": model_id,
                    "execution_time_seconds": round(end_time - start_time, 2),
                    "source_bucket": bucket,
                    "source_key": key,
                },
            }

            sink_result = write_json_to_s3(key, output)
            results.append({"key": key, "status": "success", "sink_result": sink_result})

        except Exception as e:
            logger.exception(f"Error processing record: {e}")
            results.append(
                {
                    "key": record.get("s3", {}).get("object", {}).get("key", "unknown"),
                    "status": "error",
                    "error": str(e),
                }
            )

    return {"statusCode": 200, "body": json.dumps({"processed": len(results), "results": results})}

