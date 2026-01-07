"""Output sinks for on-prem notable analysis service.

Supports:
- Filesystem sink (markdown reports to REPORT_DIR)
- Splunk notable REST API update (optional)
"""

import logging
import requests
from pathlib import Path
from typing import Dict, Any, Optional

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
    original_notable: Dict[str, Any],
    config: Config
) -> Dict[str, Any]:
    """Update notable via Splunk REST API /services/notable_update.
    
    NOTE: The endpoint and payload are placeholders. Confirm with your Splunk ES admin
    that /services/notable_update is correct for your environment. Adjust the endpoint,
    headers, and payload fields as needed for your Splunk ES version/configuration.
    
    Args:
        notable_id: Notable ID for logging.
        markdown: Generated markdown report (used as comment).
        original_notable: Original notable data (should contain notable_id or search_name).
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
    
    # Extract notable identifier
    rule_uid = original_notable.get("notable_id") or original_notable.get("event_id")
    search_name = original_notable.get("search_name")
    
    if not rule_uid and not search_name:
        logger.warning("No notable_id or search_name found in original notable")
        return {"status": "error", "message": "Cannot identify notable to update"}
    
    # Build REST API request
    rest_url = f"{config.SPLUNK_BASE_URL.rstrip('/')}/services/notable_update"
    headers = {
        "Authorization": f"Bearer {config.SPLUNK_API_TOKEN}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data: Dict[str, Any] = {
        "comment": markdown,
        "status": "2"  # In Progress
    }
    
    if rule_uid:
        data["ruleUIDs"] = rule_uid
    elif search_name:
        data["search_name"] = search_name
    
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
            "notable_id": rule_uid or search_name
        }
        
    except requests.RequestException as e:
        logger.error(f"Error writing to Splunk REST: {e}")
        return {"status": "error", "message": str(e)}

