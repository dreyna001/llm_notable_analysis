"""File-drop ingestion for on-prem notable analysis service.

Handles discovery, normalization, ID extraction, and atomic file movement
for the file_drop ingest mode.
"""

import json
import logging
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional

from .config import Config

logger = logging.getLogger(__name__)


def discover_files(config: Config) -> List[Path]:
    """Discover unprocessed notable files in INCOMING_DIR.
    
    Looks for .json and .txt files. Does not recurse into subdirectories.
    
    Args:
        config: Service configuration.
        
    Returns:
        List of file paths to process (sorted by modification time, oldest first).
    """
    incoming = config.INCOMING_DIR
    if not incoming.exists():
        logger.warning(f"INCOMING_DIR does not exist: {incoming}")
        return []
    
    files = list(incoming.glob("*.json")) + list(incoming.glob("*.txt"))
    # Sort by modification time (oldest first for FIFO processing)
    files.sort(key=lambda f: f.stat().st_mtime)
    return files


def normalize_notable(content: str, content_type: str = "text") -> Dict[str, Any]:
    """Normalize notable content into internal alert structure.
    
    Mirrors the normalize_notable() function from lambda_handler.py.
    
    Args:
        content: Raw content from file (JSON string or plain text).
        content_type: Type hint for content ('json' or 'text').
        
    Returns:
        Dict with normalized alert containing summary, risk_index, and raw_log.
    """
    summary = ""
    risk_index = {
        "risk_score": "N/A",
        "source_product": "OnPrem_Pipeline",
        "threat_category": "N/A"
    }
    raw_log: Dict[str, Any] = {}
    
    # Try to parse as JSON first
    if content_type == "json" or content.strip().startswith("{"):
        try:
            parsed_json = json.loads(content)
            if isinstance(parsed_json, dict):
                summary = parsed_json.get("summary", "File-submitted notable")
                # Extract risk_index fields if present
                if "risk_score" in parsed_json:
                    risk_index["risk_score"] = parsed_json["risk_score"]
                if "source_product" in parsed_json:
                    risk_index["source_product"] = parsed_json["source_product"]
                if "threat_category" in parsed_json:
                    risk_index["threat_category"] = parsed_json["threat_category"]
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


def get_notable_id(raw_log: Dict[str, Any], file_path: Path) -> str:
    """Extract or generate a notable ID for output file naming.
    
    Args:
        raw_log: Parsed notable data (may contain notable_id, event_id, etc.).
        file_path: Original file path (used as fallback).
        
    Returns:
        Sanitized notable ID string (safe for filenames).
    """
    # Priority: notable_id > event_id > search_name > file stem
    raw_id = (
        raw_log.get("notable_id") or
        raw_log.get("event_id") or
        raw_log.get("search_name", "")[:50].replace(" ", "_") or
        file_path.stem
    )
    
    # Sanitize for filename safety (no path traversal, no special chars)
    sanitized = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(raw_id))
    return sanitized[:100] or "unknown"


def move_to_processed(file_path: Path, config: Config) -> Path:
    """Move a successfully processed file to PROCESSED_DIR.
    
    Args:
        file_path: Original file path.
        config: Service configuration.
        
    Returns:
        New path in PROCESSED_DIR.
    """
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.PROCESSED_DIR / file_path.name
    # Handle collision by appending suffix
    if dest.exists():
        stem = file_path.stem
        suffix = file_path.suffix
        counter = 1
        while dest.exists():
            dest = config.PROCESSED_DIR / f"{stem}_{counter}{suffix}"
            counter += 1
    shutil.move(str(file_path), str(dest))
    logger.info(f"Moved processed file to {dest}")
    return dest


def move_to_quarantine(file_path: Path, config: Config, reason: Optional[str] = None) -> Path:
    """Move a failed file to QUARANTINE_DIR.
    
    Args:
        file_path: Original file path.
        config: Service configuration.
        reason: Optional reason for quarantine (logged).
        
    Returns:
        New path in QUARANTINE_DIR.
    """
    config.QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.QUARANTINE_DIR / file_path.name
    # Handle collision
    if dest.exists():
        stem = file_path.stem
        suffix = file_path.suffix
        counter = 1
        while dest.exists():
            dest = config.QUARANTINE_DIR / f"{stem}_{counter}{suffix}"
            counter += 1
    shutil.move(str(file_path), str(dest))
    logger.warning(f"Quarantined file to {dest}" + (f": {reason}" if reason else ""))
    return dest

