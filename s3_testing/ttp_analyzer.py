#!/usr/bin/env python3
"""
TTP Analyzer module for AWS Lambda + Bedrock Nova Pro.
Ports the core logic from notable_analysis.py without modifying the original.
"""

import json
import re
import time
import os
import logging
from typing import List, Dict, Any, Set, Optional, Tuple
from pathlib import Path
import boto3
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Some models / intermediaries occasionally wrap the JSON payload in an extra
# top-level container key (e.g., {"ttp_analyzer": {...}}). This helper unwraps
# common container shapes so downstream schema validation is robust.
_COMMON_RESULT_WRAPPER_KEYS = (
    "ttp_analyzer",
    "analyze_notable",
    "analysis",
    "result",
    "data",
    "payload",
)


def _normalize_llm_result_shape(result: Any) -> Any:
    """Normalize common wrapper shapes around the expected top-level schema.

    Expected schema is a dict with keys like 'ttp_analysis', 'ioc_extraction', etc.
    Sometimes responses come back wrapped under a single container key; unwrap it.
    """
    if not isinstance(result, dict):
        return result

    # 1) Explicit wrapper keys (best effort)
    for k in _COMMON_RESULT_WRAPPER_KEYS:
        v = result.get(k)
        if isinstance(v, dict):
            logger.warning(f"Unwrapping LLM result from container key: {k!r}")
            return v

    # 2) Singleton dict wrapper: {"something": {...}}
    if len(result) == 1:
        (only_key, only_val), = result.items()
        if isinstance(only_val, dict):
            logger.warning(f"Unwrapping singleton LLM result container key: {only_key!r}")
            return only_val

    return result


# If tool use fails with a Bedrock ModelErrorException, we fall back to raw-JSON mode
# (no toolConfig) to keep the pipeline operational.

# Tool schema for Bedrock converse API - enforces structured JSON output
ANALYZE_NOTABLE_TOOL = {
    "toolSpec": {
        "name": "analyze_notable",
        "description": "Analyze a security alert and return structured TTP analysis",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "ttp_analysis": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "ttp_id": {"type": "string"},
                                "ttp_name": {"type": "string"},
                                "confidence_score": {"type": "number"},
                                "explanation": {"type": "string"},
                                "evidence_fields": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": [
                                "ttp_id",
                                "ttp_name",
                                "confidence_score",
                                "explanation",
                                "evidence_fields",
                            ],
                        },
                    },
                    "ioc_extraction": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "ip_addresses": {"type": "array", "items": {"type": "string"}},
                            "domains": {"type": "array", "items": {"type": "string"}},
                            "user_accounts": {"type": "array", "items": {"type": "string"}},
                            "hostnames": {"type": "array", "items": {"type": "string"}},
                            "file_paths": {"type": "array", "items": {"type": "string"}},
                            "process_names": {"type": "array", "items": {"type": "string"}},
                            "file_hashes": {"type": "array", "items": {"type": "string"}},
                            "event_ids": {"type": "array", "items": {"type": "string"}},
                            "urls": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": [
                            "ip_addresses",
                            "domains",
                            "user_accounts",
                            "hostnames",
                            "file_paths",
                            "process_names",
                            "file_hashes",
                            "event_ids",
                            "urls",
                        ],
                    },
                    "evidence_vs_inference": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "evidence": {"type": "array", "items": {"type": "string"}},
                            "inferences": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["evidence", "inferences"],
                    },
                    "competing_hypotheses": {
                        "type": "array",
                        "minItems": 6,
                        "maxItems": 6,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "hypothesis_type": {"type": "string", "enum": ["benign", "adversary"]},
                                "hypothesis": {"type": "string"},
                                "evidence_support": {"type": "array", "items": {"type": "string"}},
                                "evidence_gaps": {"type": "array", "items": {"type": "string"}},
                                "best_pivots": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "properties": {
                                            "log_source": {"type": "string"},
                                            "key_fields": {"type": "array", "items": {"type": "string"}},
                                        },
                                        "required": ["log_source", "key_fields"],
                                    },
                                },
                            },
                            "required": [
                                "hypothesis_type",
                                "hypothesis",
                                "evidence_support",
                                "evidence_gaps",
                                "best_pivots",
                            ],
                        },
                    },
                },
                "required": ["ttp_analysis", "ioc_extraction",
                             "evidence_vs_inference",
                             "competing_hypotheses"],
                "additionalProperties": False,
            }
        }
    }
}

# Required keys and their expected types for schema validation
REQUIRED_RESPONSE_KEYS = {
    "ttp_analysis": list,
    "ioc_extraction": dict,
    "evidence_vs_inference": dict,
    "competing_hypotheses": list,
}

# Stable, deterministic list of required top-level keys for logging/debugging
REQUIRED_RESPONSE_KEYS_LIST = list(REQUIRED_RESPONSE_KEYS.keys())

# Repair prompt template for content retry when parsing fails
REPAIR_PROMPT_TEMPLATE = """Your previous response could not be parsed.

Error: {error}

Previous output (truncated):
{prior_output}

Please use the analyze_notable tool to return your analysis. Return ONLY the tool call with valid JSON matching the schema. Do not include any text outside the tool call."""

# Repair prompt for raw-JSON mode (no tool use)
REPAIR_PROMPT_TEMPLATE_RAW_JSON = """Your previous response could not be parsed.

Error: {error}

Previous output (truncated):
{prior_output}

Return ONLY a single valid JSON object matching the schema. Do not include markdown fences, tool calls, or any extra text."""

# =============================================================================
# PROMPT SECTIONS - Modular prompt components for maintainability
# =============================================================================

SYSTEM_PROMPT = "You are a cybersecurity expert specializing in MITRE ATT&CK TTP analysis."

ANALYST_DOCTRINE = """
ANALYST DOCTRINE (apply to every case)
- MITRE ATT&CK is many-to-many: a single technique may support several tactics. Always state (a) the tactic you're assigning in this alert AND (b) other plausible tactics this technique commonly serves (tactic-span note). Base on MITRE ATT&CK v17.
- FACT vs. INFERENCE: List literal, direct alert evidence first (field=value from the alert), then inferences and assumptions separately (with uncertainty).
- IOC labeling hygiene: Do not list core OS/generic binaries as IOCs without explicit malicious context. Instead, list as "system_components_observed" if present in the alert.
- STATELESS ANALYSIS: Reasoning must rely only on observable fields in this notable. If a required fact is not present, state "unknown" and list what would disambiguate.
"""

EVIDENCE_GATE = """
EVIDENCE-GATE: Only include a technique (TTP) if:
A. There is a direct data-component match in the alert (quote it).
B. Your explanation cites the matching field/value.
C. No inference or external context is necessary.
D. If evidence correctness depends on context not in the log (e.g., domain internal/external, IP a DC), drop to the parent technique or reduce confidence by >=0.20 and state the missing context in your explanation.
"""

SCORING_RUBRIC = """
Scoring Rubric:
- high >= 0.80 = direct, unambiguous
- med 0.50-0.79 = strongly suggestive; one element missing
- low < 0.30 = plausible but needs corroboration
"""

CAUSAL_HUMILITY = """
CAUSAL HUMILITY + PIVOT STRATEGY (Stateless)
Do not assume a single root cause from one notable. Use this reasoning procedure:

1) Generate EXACTLY 6 competing hypotheses for how the observable could occur:
   - EXACTLY 3 benign hypotheses
   - EXACTLY 3 adversary hypotheses (different initial vectors)

2) For each hypothesis:
   - hypothesis_type: "benign" or "adversary"
   - hypothesis: string description
   - evidence_support: list of field=value pairs from the notable that support it
   - evidence_gaps: list of critical evidence that is missing
   - best_pivots: list of 1-2 pivots (each with log_source and key_fields)

3) Pivot selection rules (use what is available; do not invent telemetry):
   - If network origin matters: pivot to VPN/jump host/PAM session logs and firewall allow logs.
   - If identity is in question: pivot to IdP sign-in logs (if federated/hybrid) and AD authentication trails.
   - If local compromise is suspected: pivot to endpoint telemetry (Sysmon/EDR) and process/access signals.
   - If only Windows Security logs exist, state limitations explicitly and downgrade confidence.
"""

MITIGATION_RULES = """
MITIGATIONS (Containment + Hardening only)
When proposing mitigations, do NOT list generic best practices. Use this procedure:

1) Identify the likely ATT&CK technique(s) implicated by the evidence.

2) Propose mitigations in TWO tiers only (max 5 total, ranked by risk reduction):
   - Containment (hours): actions that reduce immediate risk
   - Hardening (days/weeks): controls that reduce recurrence

3) For each mitigation, include:
   - rationale: which evidence/inference it addresses (cite fields/observables)
   - preconditions: environment dependencies inferred from notable, or "unknown" if not determinable
   - tradeoffs: operational impact or failure modes
   - confidence_effect: what would increase/decrease confidence that this mitigation is the right priority

4) Ensure mitigations match the scenario:
   - Only include controls relevant to the technique and feasible under inferred conditions
   - Avoid suggesting disruptive actions (e.g., "isolate DC") without a narrower, safer alternative
   - Cite ATT&CK mitigations by ID where relevant (e.g., M1032, M1026, M1030)
"""

PROCEDURE = """
PROCEDURE:
1. **Think silently**: classify activity -> tactics -> candidate techniques.
2. Self-check against the tactic checklist.
3. Decode/deobfuscate common encodings (Base64, hex, URL-encoded, gzip) if found.
4. Use sub-techniques when specific variant is confirmed (e.g., T1059.001 for PowerShell).
5. Default to parent techniques when sub-technique cannot be precisely assigned.
6. Apply Causal Humility reasoning.
"""

OUTPUT_SCHEMA = """
Use the analyze_notable tool to return your analysis. The tool expects the following schema:

OUTPUT FORMAT: Return a single valid JSON object with these top-level keys:
- `ttp_analysis`
- `ioc_extraction`
- `evidence_vs_inference`
- `competing_hypotheses`

SCHEMA:
- ttp_analysis: list of objects, each with:
    - ttp_id: string (MITRE ATT&CK ID, e.g. "T1059.001")
    - ttp_name: string (official technique name)
    - confidence_score: float (0.0-1.0)
    - explanation: string (A brief explanation of why this TTP was inferred, using quoted evidence from the alert. End with "Uncertainty: [brief statement]" acknowledging what is inferred vs. direct evidence, and any missing context like geo/VPN metadata, edge telemetry, etc.)
    - evidence_fields: list of strings (Specific alert field=value pairs that directly support this TTP)

- ioc_extraction: object with:
    - ip_addresses: list of strings
    - domains: list of strings
    - user_accounts: list of strings
    - hostnames: list of strings
    - file_paths: list of strings
    - process_names: list of strings
    - file_hashes: list of strings
    - event_ids: list of strings
    - urls: list of strings

- evidence_vs_inference: object with:
    - evidence: list of strings (Literal field=value facts from the alert)
    - inferences: list of strings (Hypotheses with noted uncertainties)

- competing_hypotheses: list of EXACTLY 6 objects (EXACTLY 3 benign + EXACTLY 3 adversary), each with:
    - hypothesis_type: "benign" or "adversary"
    - hypothesis: string
    - evidence_support: list of strings (field=value pairs supporting this)
    - evidence_gaps: list of strings (critical missing evidence)
    - best_pivots: list of objects with log_source and key_fields
"""

OUTPUT_SCHEMA_RAW_JSON = OUTPUT_SCHEMA.replace(
    "Use the analyze_notable tool to return your analysis. The tool expects the following schema:",
    "Return ONLY a single JSON object matching the schema below. Do not include markdown fences or any extra text."
)

RULES = """
RULES:
- CRITICAL: NO EMOJIS OR UNICODE SYMBOLS; Use only plain ASCII text characters.
- TIME WINDOWS: If ALERT_TIME is provided, previous queries use earliest=-24h@h latest=ALERT_TIME, next queries use earliest=ALERT_TIME latest=+24h@h. If not provided, use relative time.
- EVIDENCE VS INFERENCE: Populate "evidence" with only direct field=value facts. Populate "inferences" with hypotheses and note uncertainties.
- URL POLICY:
  - Never output example.com (or any example/test domain) anywhere.
  - Never output the word PLACEHOLDER/placeholder anywhere.
- TTP EXPLANATIONS: Always end with "Uncertainty: [brief statement]".
- IOC EXTRACTION: Extract ALL IOCs; leave arrays empty [] if not found. Do not label core OS components as IOCs without malicious context.
- STATELESS: If context is missing (e.g., IP ownership, VPN status), state "unknown" and list what would disambiguate.
- All fields and keys must match the schema exactly.
"""


def validate_response_schema(result: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Validate parsed result has all required keys with correct types.
    
    Args:
        result: Parsed dict from LLM response.
        
    Returns:
        Tuple of (is_valid, error_message):
        - is_valid: True if all required keys present with correct types.
        - error_message: Description of first validation failure, or None if valid.
    """
    if not isinstance(result, dict):
        return False, f"Expected dict, got {type(result).__name__}"
    
    for key, expected_type in REQUIRED_RESPONSE_KEYS.items():
        if key not in result:
            return False, f"Missing required key: {key}"
        if not isinstance(result[key], expected_type):
            return False, f"Key '{key}' must be {expected_type.__name__}, got {type(result[key]).__name__}"
    
    return True, None


def validate_competing_hypotheses_balance(result: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Enforce competing_hypotheses contains EXACTLY 3 benign + EXACTLY 3 adversary items."""
    ch = result.get("competing_hypotheses")
    if not isinstance(ch, list):
        return False, "competing_hypotheses must be a list"
    if len(ch) != 6:
        return False, f"competing_hypotheses must contain exactly 6 items (got {len(ch)})"

    benign = 0
    adversary = 0
    for i, item in enumerate(ch):
        if not isinstance(item, dict):
            return False, f"competing_hypotheses[{i}] must be an object"
        t = item.get("hypothesis_type")
        if t == "benign":
            benign += 1
        elif t == "adversary":
            adversary += 1
        else:
            return False, f"competing_hypotheses[{i}].hypothesis_type must be 'benign' or 'adversary'"

    if benign != 3 or adversary != 3:
        return False, f"competing_hypotheses must include exactly 3 benign + 3 adversary (got benign={benign}, adversary={adversary})"

    return True, None


def _iter_strings(obj: Any, *, path: str = "") -> List[Tuple[str, str]]:
    """Collect (path, value) for all string leaves in a nested structure."""
    found: List[Tuple[str, str]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            child_path = f"{path}.{k}" if path else str(k)
            found.extend(_iter_strings(v, path=child_path))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            child_path = f"{path}[{i}]"
            found.extend(_iter_strings(v, path=child_path))
    elif isinstance(obj, str):
        found.append((path, obj))
    return found


def validate_content_policies(result: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Validate policy constraints that are hard to express purely via JSON schema.

    Enforces:
    - No example.com (or other example/test domains) anywhere
    - No PLACEHOLDER tokens except inside query strings
    - URLs only allowed in ioc_extraction.urls[]
    """
    # 1) Global string policy scan
    for p, s in _iter_strings(result):
        s_lower = s.lower()

        if "example.com" in s_lower:
            return False, f"Disallowed placeholder domain in {p}"

        # Allow PLACEHOLDER only within query strings (we intentionally use it for index/sourcetype templates)
        if "placeholder" in s_lower:
            return False, f"Disallowed PLACEHOLDER token in {p}"

        # URLs: allow only within ioc_extraction.urls[]
        if ("http://" in s_lower or "https://" in s_lower):
            if not p.startswith("ioc_extraction.urls["):
                return False, f"Disallowed URL outside ioc_extraction.urls: {p}"
    
    return True, None


def extract_json_object(raw_text: str) -> Tuple[str, Optional[str]]:
    """Extract a JSON object from text that may contain fences, preamble, or trailing content.
    
    Args:
        raw_text: Raw text that may contain a JSON object with surrounding content.
        
    Returns:
        Tuple of (candidate_json_text, extraction_note).
        - candidate_json_text: The extracted/cleaned JSON string, or original if no extraction needed.
        - extraction_note: Description of what was done, or None if text was used as-is.
    """
    if not raw_text:
        return raw_text, None
    
    text = raw_text
    notes = []
    
    # Step 1: Strip leading/trailing whitespace
    text = text.strip()
    
    # Step 2: Strip UTF-8 BOM if present
    if text.startswith('\ufeff'):
        text = text[1:]
        notes.append("stripped BOM")
    
    # Step 3: Strip markdown code fences if present
    # Match ```json or ``` at start and ``` at end
    fence_pattern = r'^```(?:json)?\s*\n?(.*?)\n?```\s*$'
    fence_match = re.match(fence_pattern, text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1).strip()
        notes.append("stripped code fences")
    
    # Step 4: Check if text starts with '{' - if so, it's likely already clean JSON
    text_stripped = text.strip()
    if text_stripped.startswith('{'):
        # Try to extract brace-balanced JSON object (handles trailing content)
        extracted = _extract_brace_balanced_object(text_stripped)
        if extracted and extracted != text_stripped:
            notes.append("extracted brace-balanced object")
            text = extracted
        elif extracted:
            text = extracted
        # If extraction failed, we'll still try with what we have
    else:
        # Text doesn't start with '{', try to find first '{' and extract from there
        first_brace = text.find('{')
        if first_brace != -1:
            notes.append(f"skipped {first_brace} chars of preamble")
            extracted = _extract_brace_balanced_object(text[first_brace:])
            if extracted:
                text = extracted
                notes.append("extracted brace-balanced object")
            else:
                # Fallback: just use from first brace onward
                text = text[first_brace:]
    
    extraction_note = "; ".join(notes) if notes else None
    return text, extraction_note


def _extract_brace_balanced_object(text: str) -> Optional[str]:
    """Extract the first complete brace-balanced JSON object from text.
    
    Handles braces inside JSON strings correctly by tracking quote state.
    
    Args:
        text: Text starting with '{'.
        
    Returns:
        The extracted JSON object substring, or None if extraction fails.
    """
    if not text or not text.startswith('{'):
        return None
    
    depth = 0
    in_string = False
    escape_next = False
    
    for i, char in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        
        if char == '\\' and in_string:
            escape_next = True
            continue
        
        if char == '"' and not escape_next:
            in_string = not in_string
            continue
        
        if in_string:
            continue
        
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                # Found the end of the first complete object
                return text[:i + 1]
    
    # Unbalanced braces - return None to indicate extraction failed
    return None


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
            ttp_id = ttp["ttp_id"]
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


class BedrockAnalyzer:
    """LLM-based TTP analyzer using Bedrock Nova Pro.
    
    This class coordinates TTP analysis by formatting alerts, calling the Bedrock
    LLM API, and validating returned TTPs against the MITRE ATT&CK framework.
    """
    
    def __init__(self, model_id: str = "amazon.nova-pro-v1:0"):
        """Initialize the analyzer with Bedrock client.
        
        Args:
            model_id: The Bedrock model ID to use (default: amazon.nova-pro-v1:0).
        """
        self.bedrock_client = boto3.client('bedrock-runtime')
        self.model_id = model_id
        
        # Initialize validator
        ids_file = Path(__file__).parent / "enterprise_attack_v17.1_ids.json"
        self.validator = TTPValidator(ids_file)
        
        # Store last response for markdown generation
        self.last_llm_response = None
        # Store raw content for retry/debugging
        self.last_raw_content = None

    def _build_prompt(self, alert_text: str, alert_time: Optional[str], valid_ttps_list: str, *, use_tool: bool) -> str:
        """Assemble the full prompt from modular sections.
        
        Args:
            alert_text: Formatted alert text to analyze.
            alert_time: Optional ISO timestamp of the alert.
            valid_ttps_list: Comma-separated list of valid TTP IDs.
            
        Returns:
            Complete prompt string for LLM.
        """
        alert_time_str = f"\n**ALERT_TIME:** {alert_time}\n" if alert_time else ""
        output_schema = OUTPUT_SCHEMA if use_tool else OUTPUT_SCHEMA_RAW_JSON
        
        return f"""You are a cybersecurity expert mapping MITRE ATT&CK techniques from a single alert.
{alert_time_str}
---

{ANALYST_DOCTRINE}

{EVIDENCE_GATE}

{SCORING_RUBRIC}

{CAUSAL_HUMILITY}

{MITIGATION_RULES}

{PROCEDURE}

Use only the ATT&CK techniques from this allowed list:
{valid_ttps_list}

SECURITY ALERT INPUT:
{alert_text}

---

{output_schema}

---

{RULES}
"""
    
    @staticmethod
    def _is_tooluse_model_error(err: ClientError) -> bool:
        """Return True if this ClientError looks like a tool-use invalid sequence ModelErrorException."""
        try:
            code = (err.response or {}).get("Error", {}).get("Code", "")
            msg = (err.response or {}).get("Error", {}).get("Message", "") or str(err)
        except Exception:
            return False
        return code == "ModelErrorException" and "ToolUse" in msg and "invalid sequence" in msg.lower()

    def _converse(self, prompt: str, *, use_tool: bool) -> Dict[str, Any]:
        """Call Bedrock converse with optional toolConfig."""
        default_max_tokens = 4096
        try:
            max_tokens = int(os.environ.get("MAX_OUTPUT_TOKENS", str(default_max_tokens)))
        except ValueError:
            max_tokens = default_max_tokens
        # Clamp to a sane range to avoid accidental runaway costs / invalid values
        max_tokens = max(256, min(max_tokens, 8192))

        kwargs: Dict[str, Any] = {
            "modelId": self.model_id,
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {
                "maxTokens": max_tokens,
                # Lower temperature reduces the chance of malformed tool-call sequences
                "temperature": 0.1,
            },
        }
        if use_tool:
            kwargs["toolConfig"] = {
                "tools": [ANALYZE_NOTABLE_TOOL],
                "toolChoice": {"tool": {"name": "analyze_notable"}},
            }
        return self.bedrock_client.converse(**kwargs)
    
    def _parse_bedrock_response(
        self,
        response: Dict[str, Any],
        *,
        allow_text_fallback: bool,
    ) -> Tuple[Optional[Dict], Optional[str], Optional[str]]:
        """Parse Bedrock converse API response, extracting structured output.
        
        Args:
            response: Raw response from bedrock_client.converse().
            
        Returns:
            Tuple of (parsed_result, error_message, raw_content):
            - parsed_result: Parsed dict if successful, None otherwise.
            - error_message: Error description if parsing failed, None otherwise.
            - raw_content: Raw text content (for retry prompt), None if toolUse succeeded.
        """
        # Log minimal response metadata (helps diagnose truncation/stop reasons without dumping content)
        try:
            stop_reason = (response.get("stopReason") or response.get("output", {}).get("stopReason") or "unknown")
            usage = response.get("usage") or response.get("output", {}).get("usage") or {}
            if isinstance(usage, dict) and usage:
                logger.info(f"Bedrock stopReason={stop_reason} usage={usage}")
            else:
                logger.info(f"Bedrock stopReason={stop_reason}")
        except Exception:
            # Keep parsing resilient; logging should never break execution
            pass

        content_blocks = response['output']['message']['content']
        try:
            logger.info(f"Bedrock content block types: {[list(b.keys()) for b in content_blocks]}")
        except Exception:
            pass
        
        # Try toolUse block first (preferred path with forced tool choice)
        for block in content_blocks:
            if 'toolUse' in block:
                tool_input = block['toolUse'].get('input', {})
                if isinstance(tool_input, dict):
                    try:
                        tool_name = block["toolUse"].get("name", "unknown")
                        tool_id = block["toolUse"].get("toolUseId", "unknown")
                        logger.info(f"Parsed response from toolUse block name={tool_name} toolUseId={tool_id}")
                        logger.info(f"tool_input keys: {list(tool_input.keys())}")
                    except Exception:
                        logger.info("Parsed response from toolUse block")
                    return tool_input, None, None
        
        if not allow_text_fallback:
            # In tool-use mode, treat non-tool responses as invalid and force a repair retry.
            error_msg = "No toolUse block found in response (tool_use required)"
            logger.error(error_msg)
            return None, error_msg, str(content_blocks)[:2000]

        # Fallback: try text extraction if no toolUse (raw JSON mode only)
        for block in content_blocks:
            if 'text' in block:
                raw_text = block['text']
                logger.info(f"Raw LLM response length: {len(raw_text)} characters")
                
                # Pre-parse cleanup: extract JSON from fences/preamble/trailing content
                candidate_text, extraction_note = extract_json_object(raw_text)
                if extraction_note:
                    logger.info(f"JSON extraction: {extraction_note}")
                
                try:
                    result = json.loads(candidate_text)
                    logger.info("Parsed response from text block (fallback)")
                    return result, None, raw_text
                except json.JSONDecodeError as e:
                    error_msg = f"JSON parse error: {e}"
                    logger.error(f"Failed to parse JSON response: {e}")
                    logger.error(f"Raw response (first 500 chars): {raw_text[:500]}")
                    if candidate_text != raw_text:
                        logger.error(f"Extracted candidate (first 500 chars): {candidate_text[:500]}")
                    return None, error_msg, raw_text
        
        # No toolUse or text block found
        error_msg = "No toolUse or text block found in response"
        logger.error(error_msg)
        return None, error_msg, str(content_blocks)
    
    def format_alert_input(self, summary: str, risk_index: Dict[str, Any], raw_log: Dict[str, Any]) -> str:
        """Format alert data into a structured text block.
        
        Args:
            summary: Alert summary text.
            risk_index: Dictionary containing risk score, source product, and threat category.
            raw_log: Dictionary of raw log fields.
            
        Returns:
            Formatted string with [SUMMARY], [RISK INDEX], and [RAW EVENT] sections.
        """
        # TODO: Revisit this alert_text envelope once the final Splunk alert/notable input schema is finalized.
        #       - Decide whether to pass raw JSON (pretty-printed) vs flattened k=v pairs.
        #       - Preserve canonical Splunk field names and include any required metadata (e.g., index/sourcetype/source)
        #         without overfitting the prompt to today's placeholder format.
        risk_text = "\n".join([
            f"Risk Score: {risk_index.get('risk_score', 'N/A')}",
            f"Source Product: {risk_index.get('source_product', 'N/A')}",
            f"Threat Category: {risk_index.get('threat_category', 'N/A')}",
        ])
        raw_text = " ".join(f"{k}={v}" for k, v in raw_log.items())
        return f"""[SUMMARY]
{summary or 'N/A'}

[RISK INDEX]
{risk_text}

[RAW EVENT]
{raw_text}"""
    
    def analyze_ttp(self, alert_text: str, alert_time: Optional[str] = None) -> List[Dict[str, Any]]:
        """Use LLM to analyze the alert and identify relevant MITRE ATT&CK TTPs.
        
        This method constructs a detailed prompt with analyst doctrine, sends it to
        Bedrock Nova Pro, parses the structured JSON response, and filters out invalid TTPs.
        
        Args:
            alert_text: Formatted alert text to analyze.
            alert_time: Optional ISO timestamp of the alert for enrichment queries.
            
        Returns:
            List of valid TTP dictionaries with scores, explanations, and metadata.
            Returns empty list if analysis fails or no valid TTPs are found.
        """
        logger.info("Starting TTP analysis")
        start_time = time.time()
        
        # Get valid TTPs for the prompt
        valid_ttps_list = self.validator.get_valid_ttps_for_prompt()
        total_ttps = self.validator.get_ttp_count()
        logger.info(f"Loaded {total_ttps} valid TTPs for prompt")
        
        # Build prompt using modular sections (start in tool-use mode)
        prompt_tool = self._build_prompt(alert_text, alert_time, valid_ttps_list, use_tool=True)
        prompt_raw = self._build_prompt(alert_text, alert_time, valid_ttps_list, use_tool=False)
        
        # Input validation
        if not alert_text or not alert_text.strip():
            logger.error("Alert text is empty or whitespace only")
            return []
        
        try:
            logger.info("Making Bedrock API call...")
            api_start_time = time.time()
            
            # Call Bedrock with retry logic
            max_retries = 3
            retry_delay = 5
            
            response: Optional[Dict[str, Any]] = None
            used_tool = True

            # Phase 1: Tool-use mode (preferred)
            for attempt in range(max_retries):
                try:
                    logger.info(f"API call attempt {attempt + 1}/{max_retries} (tool_use=True)")
                    response = self._converse(prompt_tool, use_tool=True)
                    api_end_time = time.time()
                    logger.info(f"API call completed in {api_end_time - api_start_time:.2f} seconds")
                    break
                except ClientError as api_error:
                    # If Bedrock reports a tool-use invalid sequence, immediately fall back to raw JSON mode.
                    if self._is_tooluse_model_error(api_error):
                        logger.warning("Tool-use mode failed with ModelErrorException (invalid ToolUse sequence). Falling back to raw JSON mode.")
                        used_tool = False
                        response = None
                        break

                    logger.warning(f"API call attempt {attempt + 1} failed: {str(api_error)}")
                    if attempt < max_retries - 1:
                        logger.info(f"Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                        retry_delay *= 2
                    else:
                        logger.error(f"All {max_retries} API call attempts failed")
                        raise

            # Phase 2: Raw JSON mode (no toolConfig), only if tool-use mode was abandoned
            if response is None and used_tool is False:
                retry_delay = 5
                for attempt in range(max_retries):
                    try:
                        logger.info(f"API call attempt {attempt + 1}/{max_retries} (tool_use=False)")
                        response = self._converse(prompt_raw, use_tool=False)
                        api_end_time = time.time()
                        logger.info(f"API call completed in {api_end_time - api_start_time:.2f} seconds")
                        break
                    except ClientError as api_error:
                        logger.warning(f"Raw JSON API call attempt {attempt + 1} failed: {str(api_error)}")
                        if attempt < max_retries - 1:
                            logger.info(f"Retrying in {retry_delay} seconds...")
                            time.sleep(retry_delay)
                            retry_delay *= 2
                        else:
                            logger.error(f"All {max_retries} raw JSON API call attempts failed")
                            raise

            if response is None:
                raise RuntimeError("Bedrock converse did not return a response")
            
            # Parse the response using helper method
            logger.info("Parsing LLM response")
            result, error_msg, raw_content = self._parse_bedrock_response(
                response,
                allow_text_fallback=(used_tool is False),
            )
            
            # Store raw content for debugging
            if raw_content:
                self.last_raw_content = raw_content
            
            # Validate schema if parse succeeded
            if result is not None:
                # Normalize wrapper shapes (e.g., {"ttp_analyzer": {...}}) before validation
                result = _normalize_llm_result_shape(result)

                # Log raw structure for debugging
                logger.info(f"Parsed result keys: {list(result.keys()) if isinstance(result, dict) else type(result).__name__}")
                logger.info(f"Required top-level keys: {REQUIRED_RESPONSE_KEYS_LIST}")
                
                is_valid, validation_error = validate_response_schema(result)
                if not is_valid:
                    logger.warning(f"Schema validation failed: {validation_error}")
                    logger.warning(f"Got keys: {list(result.keys()) if isinstance(result, dict) else 'N/A'}")
                    error_msg = f"Schema validation: {validation_error}"
                    raw_content = raw_content or str(result)[:2000]
                    result = None  # treat as parse failure, triggers retry
                else:
                    ch_ok, ch_err = validate_competing_hypotheses_balance(result)
                    if not ch_ok:
                        logger.warning(f"Competing hypotheses validation failed: {ch_err}")
                        error_msg = f"Competing hypotheses: {ch_err}"
                        raw_content = raw_content or str(result)[:2000]
                        result = None
                    else:
                        policy_ok, policy_err = validate_content_policies(result)
                        if not policy_ok:
                            logger.warning(f"Content policy validation failed: {policy_err}")
                            error_msg = f"Content policy: {policy_err}"
                            raw_content = raw_content or str(result)[:2000]
                            result = None
            
            # Content retry: if parsing or validation failed, try once more with a repair prompt
            if result is None and error_msg:
                logger.warning(f"Initial parse failed: {error_msg}. Attempting content retry...")
                
                # Build repair prompt with truncated prior output
                prior_output = (raw_content or "")[:2000]
                repair_template = REPAIR_PROMPT_TEMPLATE if used_tool else REPAIR_PROMPT_TEMPLATE_RAW_JSON
                repair_prompt = repair_template.format(
                    error=error_msg,
                    prior_output=prior_output
                )
                
                try:
                    logger.info("Content retry: calling Bedrock with repair prompt")
                    retry_response = self._converse(repair_prompt, use_tool=used_tool)
                    
                    # Parse retry response
                    result, retry_error, retry_raw = self._parse_bedrock_response(
                        retry_response,
                        allow_text_fallback=(used_tool is False),
                    )
                    
                    # Validate schema if retry parse succeeded
                    if result is not None:
                        # Normalize wrapper shapes before validation (retry path)
                        result = _normalize_llm_result_shape(result)

                        logger.info(f"Retry parsed result keys: {list(result.keys()) if isinstance(result, dict) else type(result).__name__}")
                        
                        is_valid, validation_error = validate_response_schema(result)
                        if not is_valid:
                            logger.error(f"Retry schema validation failed: {validation_error}")
                            logger.error(f"Retry got keys: {list(result.keys()) if isinstance(result, dict) else 'N/A'}")
                            self.last_llm_response = {"raw_error": retry_raw or str(result)[:2000]}
                            return []
                        ch_ok, ch_err = validate_competing_hypotheses_balance(result)
                        if not ch_ok:
                            logger.error(f"Retry competing hypotheses validation failed: {ch_err}")
                            self.last_llm_response = {"raw_error": retry_raw or str(result)[:2000]}
                            return []
                        policy_ok, policy_err = validate_content_policies(result)
                        if not policy_ok:
                            logger.error(f"Retry content policy validation failed: {policy_err}")
                            self.last_llm_response = {"raw_error": retry_raw or str(result)[:2000]}
                            return []
                        logger.info("Content retry succeeded")
                        if retry_raw:
                            self.last_raw_content = retry_raw
                    else:
                        logger.error(f"Content retry also failed: {retry_error}")
                        self.last_llm_response = {"raw_error": retry_raw or raw_content or str(error_msg)}
                        return []
                        
                except ClientError as retry_error:
                    logger.error(f"Content retry API call failed: {retry_error}")
                    self.last_llm_response = {"raw_error": raw_content or str(error_msg)}
                    return []
            
            # Final check: if still no result after retry opportunity
            if result is None:
                self.last_llm_response = {"raw_error": raw_content or str(error_msg)}
                return []
            
            logger.info(f"Parsed result type: {type(result)}")
            
            # Store the last LLM response for markdown generation
            self.last_llm_response = result
            
            # Extract TTPs from the structured response
            scored_ttps = []
            
            if not isinstance(result, dict):
                logger.error(f"Expected dict response, got {type(result)}")
                return []
            
            # Handle the structured response with ttp_analysis
            if "ttp_analysis" in result:
                logger.info(f"Processing structured response with ttp_analysis")
                if not isinstance(result["ttp_analysis"], list):
                    logger.error(f"ttp_analysis must be a list, got {type(result['ttp_analysis'])}")
                    return []
                
                for i, item in enumerate(result["ttp_analysis"]):
                    if not isinstance(item, dict):
                        logger.warning(f"Skipping invalid TTP item at index {i}: not a dict")
                        continue
                    if "ttp_id" not in item:
                        logger.warning(f"Skipping invalid TTP item at index {i}: missing ttp_id")
                        continue
                    
                    scored_ttps.append({
                        "ttp_id": item["ttp_id"],
                        "ttp_name": item.get("ttp_name", ""),
                        "score": float(item.get("confidence_score", item.get("score", item.get("confidence", 0)))),
                        "explanation": item.get("explanation", ""),
                        "evidence_fields": item.get("evidence_fields", []),
                    })
                logger.info(f"Extracted {len(scored_ttps)} TTPs from ttp_analysis")
            
            # Filter out invalid TTPs
            logger.info("Filtering invalid TTPs")
            valid_ttps = self.validator.filter_valid_ttps(scored_ttps)
            logger.info(f"Final valid TTPs: {len(valid_ttps)}")
            
            total_time = time.time() - start_time
            logger.info(f"Total TTP analysis completed in {total_time:.2f} seconds")
            
            return valid_ttps
            
        except Exception as e:
            logger.error(f"Unexpected error calling LLM: {str(e)}")
            logger.error(f"Exception type: {type(e).__name__}")
            return []


def extract_score(ttp: Dict[str, Any]) -> float:
    """Extract score from TTP dict.
    
    Args:
        ttp: TTP dictionary containing score/confidence fields.
        
    Returns:
        Float score value, or 0.0 if no score field is found.
    """
    for key in ("score", "confidence_score", "confidence"):
        if key in ttp:
            return ttp[key]
    return 0.0

