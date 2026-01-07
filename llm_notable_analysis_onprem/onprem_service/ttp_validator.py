"""MITRE ATT&CK TTP ID Validator.

Validates technique IDs against a local JSON file containing pre-extracted
IDs from the MITRE ATT&CK framework.

Ported from s3_notable_pipeline/ttp_analyzer.py (TTPValidator class only).
"""

import json
import logging
from typing import List, Dict, Any, Set
from pathlib import Path

logger = logging.getLogger(__name__)


class TTPValidator:
    """Validator for MITRE ATT&CK TTP IDs using local data.
    
    This class loads and validates MITRE ATT&CK technique IDs from a local
    JSON file containing pre-extracted IDs from the MITRE ATT&CK framework.
    """
    
    def __init__(self, ids_file_path: Path):
        """Initialize with cached valid TTPs from local file.
        
        Args:
            ids_file_path: Path to the JSON file containing valid TTP IDs.
        """
        self._valid_subtechniques: Set[str] = set()
        self._valid_parent_techniques: Set[str] = set()
        self._load_valid_ttps(ids_file_path)
    
    def _load_valid_ttps(self, ids_file_path: Path):
        """Load valid technique IDs from pre-extracted MITRE ATT&CK IDs file.
        
        Args:
            ids_file_path: Path to the JSON file containing valid TTP IDs.
            
        Raises:
            ValueError: If no TTPs are loaded from the file.
            IOError: If the file cannot be read.
            json.JSONDecodeError: If the file contains invalid JSON.
        """
        try:
            with open(ids_file_path, 'r') as f:
                ttp_ids = json.load(f)
            
            # Separate parent techniques from sub-techniques
            for ttp_id in ttp_ids:
                if "." in ttp_id:
                    self._valid_subtechniques.add(ttp_id)
                else:
                    self._valid_parent_techniques.add(ttp_id)
            
            total_ttps = len(self._valid_subtechniques) + len(self._valid_parent_techniques)
            logger.info(f"Loaded {len(self._valid_subtechniques)} valid sub-techniques and {len(self._valid_parent_techniques)} parent techniques (total: {total_ttps})")
            
            if total_ttps == 0:
                raise ValueError("No TTPs loaded from pre-extracted IDs file.")
                
        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"Error reading pre-extracted IDs file {ids_file_path}: {e}")
            raise
    
    def is_valid_ttp(self, ttp_id: str) -> bool:
        """Check if TTP ID is valid.
        
        Args:
            ttp_id: The MITRE ATT&CK technique ID to validate.
            
        Returns:
            True if the TTP ID is valid, False otherwise.
        """
        return ttp_id in self._valid_subtechniques or ttp_id in self._valid_parent_techniques
    
    def get_valid_ttps_for_prompt(self) -> str:
        """Get formatted list of valid TTPs for inclusion in prompt.
        
        Returns:
            Comma-separated string of all valid TTP IDs.
        """
        all_ttps = sorted(list(self._valid_subtechniques)) + sorted(list(self._valid_parent_techniques))
        return ", ".join(all_ttps)
    
    def filter_valid_ttps(self, scored_ttps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter out invalid TTPs and return only valid ones.
        
        Args:
            scored_ttps: List of TTP dictionaries with 'ttp_id' keys.
            
        Returns:
            List of valid TTPs with invalid ones removed.
        """
        valid_ttps = []
        invalid_ttps = []
        
        for ttp in scored_ttps:
            ttp_id = ttp.get("ttp_id", "")
            if self.is_valid_ttp(ttp_id):
                valid_ttps.append(ttp)
            else:
                invalid_ttps.append(ttp_id)
        
        if invalid_ttps:
            logger.warning(f"Filtered out invalid TTPs: {invalid_ttps}")
        
        return valid_ttps
    
    def get_ttp_count(self) -> int:
        """Get total count of loaded TTPs.
        
        Returns:
            Total number of valid TTPs (sub-techniques + parent techniques).
        """
        return len(self._valid_subtechniques) + len(self._valid_parent_techniques)

