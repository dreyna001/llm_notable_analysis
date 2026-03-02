"""Output sinks for on-prem notable analysis service.

Supports:
- Filesystem sink (markdown reports to REPORT_DIR)
- Splunk notable REST API update (optional)
"""

import logging
import requests
from pathlib import Path
from typing import Dict, Any

from .config import Config

logger = logging.getLogger(__name__)


def write_markdown_to_file(notable_id: str, markdown: str, config: Config) -> Path:
    """Write markdown report to filesystem.
    
    Args:
        notable_id: Sanitized notable ID for filename.
        markdown: Generated markdown content.
        config: Service configuration.
        
    Returns:
        Path to the written markdown file.
    """
    config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = config.REPORT_DIR / f"{notable_id}.md"
    
    # Handle collision by appending suffix
    if output_path.exists():
        counter = 1
        while output_path.exists():
            output_path = config.REPORT_DIR / f"{notable_id}_{counter}.md"
            counter += 1
    
    output_path.write_text(markdown, encoding="utf-8")
    logger.info(f"Wrote markdown report to {output_path}")
    return output_path


def update_splunk_notable(
    notable_id: str,
    markdown: str,
    finding_id: str,
    config: Config
) -> Dict[str, Any]:
    """Update notable via Splunk REST API /services/notable_update.
    
    NOTE: Splunk ES deployments can vary. Confirm with your Splunk ES admin that this
    endpoint and identifier contract match your environment.
    
    Args:
        notable_id: Notable ID for logging.
        markdown: Generated markdown report (used as comment).
        finding_id: Correlation ID for writeback (derived from input filename stem).
        config: Service configuration.
        
    Returns:
        Dict with sink operation status.
    """
    if not config.SPLUNK_SINK_ENABLED:
        logger.debug("Splunk sink disabled, skipping notable update")
        return {"status": "skipped", "message": "Splunk sink disabled"}
    
    if not config.SPLUNK_BASE_URL or not config.SPLUNK_API_TOKEN:
        logger.error("SPLUNK_BASE_URL or SPLUNK_API_TOKEN not configured")
        return {"status": "error", "message": "Splunk REST credentials not configured"}
    
    if not finding_id:
        logger.warning(f"No finding_id provided for notable {notable_id}")
        return {"status": "error", "message": "Cannot identify notable to update"}
    
    # Build REST API request
    endpoint_path = config.SPLUNK_NOTABLE_UPDATE_PATH or "/services/notable_update"
    if not endpoint_path.startswith("/"):
        endpoint_path = f"/{endpoint_path}"
    rest_url = f"{config.SPLUNK_BASE_URL.rstrip('/')}{endpoint_path}"
    headers = {
        "Authorization": f"Bearer {config.SPLUNK_API_TOKEN}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data: Dict[str, Any] = {
        "finding_id": finding_id,
        "comment": markdown,
        "status": "2"  # In Progress
    }
    
    # TLS verification: use custom CA bundle if configured, else system trust store
    verify_tls = config.SPLUNK_CA_BUNDLE if config.SPLUNK_CA_BUNDLE else True
    
    try:
        response = requests.post(rest_url, data=data, headers=headers, timeout=30, verify=verify_tls)
        response.raise_for_status()
        
        logger.info(f"Successfully updated notable via REST API: {response.status_code}")
        
        return {
            "status": "success",
            "rest_response": response.text,
            "status_code": response.status_code,
            "finding_id": finding_id
        }
        
    except requests.RequestException as e:
        logger.error(f"Error writing to Splunk REST: {e}")
        return {"status": "error", "message": str(e)}

