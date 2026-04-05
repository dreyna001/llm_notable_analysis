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
from botocore.config import Config

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

    Args:
        result: Parsed model output object.

    Returns:
        Unwrapped dict when a known wrapper shape is detected; otherwise returns
        `result` unchanged.
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
                    "alert_reconciliation": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "verdict": {
                                "type": "string",
                                "enum": [
                                    "likely_true_positive",
                                    "likely_benign",
                                    "likely_false_positive",
                                    "unknown",
                                ],
                            },
                            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                            "one_sentence_summary": {"type": "string"},
                            "decision_drivers": {"type": "array", "items": {"type": "string"}},
                            "recommended_actions": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": [
                            "verdict",
                            "confidence",
                            "one_sentence_summary",
                            "decision_drivers",
                            "recommended_actions",
                        ],
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
                             "alert_reconciliation",
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
    "alert_reconciliation": dict,
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

PROCEDURE = """
PROCEDURE:
1. Decode/deobfuscate common encodings (Base64, hex, URL-encoded, gzip) if found.
2. Use sub-techniques when specific variant is confirmed (e.g., T1059.001 for PowerShell); default to parent techniques otherwise.
"""

ALERT_RECONCILIATION = """
ALERT RECONCILIATION (required):
- Provide a direct, actionable verdict about what to do with THIS alert right now.
- Use only evidence present in the notable; if you cannot decide, use verdict "unknown".
- decision_drivers must cite field=value facts from the notable and/or explicitly state unknowns as "unknown: <missing fact>".
- recommended_actions must be concrete next steps (pivots, validation checks, containment). Do not assume telemetry that is not present.
"""

OUTPUT_SCHEMA = """
Use the analyze_notable tool to return your analysis. Follow the tool's JSON schema exactly.

Additional constraints (not enforceable in JSON schema):
- explanation: must end with "Uncertainty: [brief statement]".
- URLs are only allowed in ioc_extraction.urls[]; no URLs elsewhere.
- Leave arrays empty [] when no items apply.
- alert_reconciliation: object with verdict, confidence, one_sentence_summary, decision_drivers (list), recommended_actions (list).
- Top-level keys (required): alert_reconciliation, competing_hypotheses, evidence_vs_inference, ioc_extraction, ttp_analysis.
- Return ONLY the tool call; no extra text.
"""

OUTPUT_SCHEMA_RAW_JSON = """
Return ONLY a single JSON object matching the schema. Do not include markdown fences or any extra text.

Additional constraints:
- explanation: must end with "Uncertainty: [brief statement]".
- URLs are only allowed in ioc_extraction.urls[]; no URLs elsewhere.
- Leave arrays empty [] when no items apply.
- alert_reconciliation: object with verdict, confidence, one_sentence_summary, decision_drivers (list), recommended_actions (list).

Top-level keys (required):
- alert_reconciliation
- competing_hypotheses
- evidence_vs_inference
- ioc_extraction
- ttp_analysis
"""

RULES = """
RULES:
- NO EMOJIS OR UNICODE SYMBOLS; use only plain ASCII text.
- Never output example.com or PLACEHOLDER anywhere.
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


def validate_competing_hypotheses_balance(
    result: Dict[str, Any], *, strict: bool = False
) -> Tuple[bool, Optional[str]]:
    """Validate competing_hypotheses shape.

    In non-strict mode, this enforces only "list of objects" for resilience.
    In strict mode, it enforces EXACTLY 3 benign + 3 adversary hypotheses.

    Args:
        result: Parsed structured model output.

    Returns:
        Tuple of `(is_valid, error_message)`.
    """
    ch = result.get("competing_hypotheses")
    if ch is None:
        return True, None
    if not isinstance(ch, list):
        return False, "competing_hypotheses must be a list"
    for i, item in enumerate(ch):
        if not isinstance(item, dict):
            return False, f"competing_hypotheses[{i}] must be an object"
    if not strict:
        return True, None
    if len(ch) != 6:
        return (
            False,
            f"competing_hypotheses must contain exactly 6 items (got {len(ch)})",
        )

    benign = 0
    adversary = 0
    for i, item in enumerate(ch):
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
    """Collect string leaf nodes from a nested dict/list structure.

    Args:
        obj: Nested object to walk.
        path: Current JSON-like path during recursion.

    Returns:
        List of `(path, value)` string pairs.
    """
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

    Args:
        result: Parsed structured model output.

    Returns:
        Tuple of `(is_valid, error_message)`.
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


URL_RE = re.compile(r"https?://[^\s\]\[<>\")'}]+", re.IGNORECASE)


def _sanitize_urls_for_content_policy(result: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Relocate disallowed URLs into ioc_extraction.urls and redact them elsewhere.

    This prevents repeated failures where the model includes MITRE/reference links in free-text
    fields like ttp_analysis[].explanation, which violates our content policy.

    Args:
        result: Parsed structured model output.

    Returns:
        Tuple of `(sanitized_result, moved_urls)` where URLs outside the
        permitted IOC field are redacted and appended to `ioc_extraction.urls`.
    """
    if not isinstance(result, dict):
        return result, []

    collected: List[str] = []

    def _walk(obj: Any, *, path: str) -> Any:
        # Allowed location: ioc_extraction.urls[*]
        allowed_prefix = "ioc_extraction.urls["

        if isinstance(obj, dict):
            for k, v in list(obj.items()):
                child_path = f"{path}.{k}" if path else str(k)
                obj[k] = _walk(v, path=child_path)
            return obj
        if isinstance(obj, list):
            for i, v in enumerate(obj):
                child_path = f"{path}[{i}]"
                obj[i] = _walk(v, path=child_path)
            return obj
        if isinstance(obj, str):
            # Keep URLs inside ioc_extraction.urls[] (but still collect them for de-dupe)
            urls = URL_RE.findall(obj)
            if not urls:
                return obj
            for u in urls:
                collected.append(u)
            if path.startswith(allowed_prefix):
                # If someone stuffed extra text around the URL, keep as-is; policy allows URLs here.
                return obj
            # Redact URLs everywhere else
            return URL_RE.sub("[URL_REDACTED]", obj)
        return obj

    result = _walk(result, path="")

    # Ensure ioc_extraction.urls contains all collected URLs (de-duped), since URLs elsewhere were redacted.
    if collected:
        ioc = result.get("ioc_extraction")
        if isinstance(ioc, dict):
            urls_list = ioc.get("urls")
            if not isinstance(urls_list, list):
                urls_list = []
            # Keep existing entries, append new URLs, then de-dupe while preserving order
            merged: List[str] = []
            seen: Set[str] = set()
            for item in urls_list:
                if isinstance(item, str) and item and item not in seen:
                    merged.append(item)
                    seen.add(item)
            for u in collected:
                if u and u not in seen:
                    merged.append(u)
                    seen.add(u)
            ioc["urls"] = merged
    return result, collected


def _coerce_ioc_extraction(value: Any) -> Dict[str, Any]:
    """Coerce IOC payload into stable markdown-rendering shape."""
    base: Dict[str, Any] = {
        "ip_addresses": [],
        "domains": [],
        "user_accounts": [],
        "hostnames": [],
        "process_names": [],
        "file_paths": [],
        "file_hashes": [],
        "event_ids": [],
        "urls": [],
    }
    if isinstance(value, dict):
        for k in list(base.keys()):
            v = value.get(k, [])
            if v is None:
                continue
            if isinstance(v, list):
                base[k] = [str(x) for x in v if str(x)]
            elif isinstance(v, str):
                base[k] = [v]
            else:
                base[k] = [str(v)]
        return base
    if isinstance(value, list):
        for item in value:
            s = str(item).strip()
            if not s:
                continue
            if s.startswith("http://") or s.startswith("https://"):
                base["urls"].append(s)
            elif re.match(r"^\d{1,3}(\.\d{1,3}){3}$", s):
                base["ip_addresses"].append(s)
            elif "\\" in s or "@" in s:
                base["user_accounts"].append(s)
            elif "/" in s or s.startswith("\\"):
                base["file_paths"].append(s)
            elif "." in s and " " not in s:
                base["domains"].append(s)
            else:
                base["hostnames"].append(s)
        return base
    return base


def _coerce_evidence_vs_inference(value: Any) -> Dict[str, Any]:
    """Coerce evidence/inference payload into a stable dict contract."""
    base: Dict[str, Any] = {"evidence": [], "inferences": []}
    if isinstance(value, dict):
        ev = value.get("evidence", [])
        inf = value.get("inferences", [])
        base["evidence"] = [
            str(x) for x in (ev if isinstance(ev, list) else [ev]) if str(x)
        ]
        base["inferences"] = [
            str(x) for x in (inf if isinstance(inf, list) else [inf]) if str(x)
        ]
        return base
    if isinstance(value, list):
        base["evidence"] = [str(x) for x in value if str(x)]
        return base
    if isinstance(value, str):
        base["evidence"] = [value]
        return base
    return base


_TTP_ID_RE = re.compile(r"\b(T\d{4}(?:\.\d{3})?)\b")


def _coerce_ttp_id(value: Any) -> Optional[str]:
    """Extract a MITRE technique ID (T#### or T####.###) from common shapes."""
    if value is None:
        return None
    if isinstance(value, str):
        m = _TTP_ID_RE.search(value.strip())
        return m.group(1) if m else None
    return _coerce_ttp_id(str(value))


def _coerce_ttp_analysis(value: Any) -> List[Dict[str, Any]]:
    """Coerce ttp_analysis into a list of objects with at least a ttp_id field."""
    if value is None:
        return []

    items: List[Any]
    if isinstance(value, list):
        items = value
    else:
        items = [value]

    out: List[Dict[str, Any]] = []
    for item in items:
        if isinstance(item, str):
            ttp_id = _coerce_ttp_id(item)
            if ttp_id:
                out.append(
                    {
                        "ttp_id": ttp_id,
                        "ttp_name": "",
                        "confidence_score": 0.5,
                        "explanation": "Extracted from model output (non-schema). Uncertainty: output format drift.",
                        "evidence_fields": [],
                    }
                )
            continue
        if isinstance(item, dict):
            raw_id = (
                item.get("ttp_id")
                or item.get("technique_id")
                or item.get("mitre_technique_id")
                or item.get("technique")
                or item.get("id")
            )
            ttp_id = _coerce_ttp_id(raw_id)
            if not ttp_id:
                ttp_id = (
                    _coerce_ttp_id(item.get("ttp_name"))
                    or _coerce_ttp_id(item.get("explanation"))
                    or _coerce_ttp_id(item.get("rationale"))
                )
            out.append(
                {
                    **item,
                    "ttp_id": ttp_id,
                    "ttp_name": item.get(
                        "ttp_name", item.get("technique_name", item.get("name", ""))
                    ),
                    "confidence_score": item.get(
                        "confidence_score",
                        item.get("score", item.get("confidence", 0.5)),
                    ),
                    "explanation": item.get("explanation", item.get("rationale", "")),
                    "evidence_fields": item.get(
                        "evidence_fields", item.get("evidence", [])
                    ),
                }
            )
    return out


def _normalize_and_fill_defaults(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """Make parsed object robust to minor schema drift from local models."""
    if not isinstance(parsed, dict):
        return {}
    out = dict(parsed)
    ar = out.get("alert_reconciliation", {})
    if not isinstance(ar, dict):
        ar = {}
    out["alert_reconciliation"] = {
        "verdict": str(ar.get("verdict", "")) if ar.get("verdict") is not None else "",
        "confidence": str(ar.get("confidence", ""))
        if ar.get("confidence") is not None
        else "",
        "one_sentence_summary": str(ar.get("one_sentence_summary", ""))
        if ar.get("one_sentence_summary") is not None
        else "",
        "decision_drivers": [
            str(x)
            for x in (
                ar.get("decision_drivers", [])
                if isinstance(ar.get("decision_drivers", []), list)
                else [ar.get("decision_drivers", "")]
            )
            if str(x)
        ],
        "recommended_actions": [
            str(x)
            for x in (
                ar.get("recommended_actions", [])
                if isinstance(ar.get("recommended_actions", []), list)
                else [ar.get("recommended_actions", "")]
            )
            if str(x)
        ],
    }
    ch = out.get("competing_hypotheses", [])
    if isinstance(ch, dict):
        ch = [ch]
    out["competing_hypotheses"] = [x for x in ch if isinstance(x, dict)] if isinstance(ch, list) else []
    out["evidence_vs_inference"] = _coerce_evidence_vs_inference(
        out.get("evidence_vs_inference", {})
    )
    out["ioc_extraction"] = _coerce_ioc_extraction(out.get("ioc_extraction", {}))
    out["ttp_analysis"] = _coerce_ttp_analysis(out.get("ttp_analysis", []))
    return out


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def extract_scored_ttps(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract a normalized scored TTP list from parsed model output."""
    scored: List[Dict[str, Any]] = []
    ttp_list = result.get("ttp_analysis", [])
    if not isinstance(ttp_list, list):
        return scored
    for i, item in enumerate(ttp_list):
        if not isinstance(item, dict):
            logger.warning(f"Skipping invalid TTP item at index {i}: not a dict")
            continue
        ttp_id = item.get("ttp_id")
        if not ttp_id:
            logger.warning(f"Skipping invalid TTP item at index {i}: missing ttp_id")
            continue
        scored.append(
            {
                "ttp_id": ttp_id,
                "ttp_name": item.get("ttp_name", ""),
                "score": _safe_float(
                    item.get(
                        "confidence_score",
                        item.get("score", item.get("confidence", 0.0)),
                    )
                ),
                "explanation": item.get("explanation", ""),
                "evidence_fields": item.get("evidence_fields", []),
            }
        )
    return scored


def build_poc_fallback_llm_payload(
    *,
    primary_text: str,
    repair_text: Optional[str],
    reason: str,
    model_name: str,
    attempt: int,
    elapsed_primary: float,
    elapsed_repair: Optional[float],
) -> Dict[str, Any]:
    """Build fallback payload that preserves raw model text for PoC review."""
    primary_text = (primary_text or "").strip()
    repair_text = (repair_text or "").strip()
    combined = primary_text
    if repair_text:
        combined += (
            "\n\n---\n\n### Secondary call (schema repair attempt) - raw output\n\n"
            + repair_text
        )
    if not combined:
        combined = "(empty model response)"
    return {
        "poc_unstructured_output": True,
        "poc_fallback_reason": reason,
        "raw_response": combined,
        "alert_reconciliation": {
            "verdict": "poc_raw_output_only",
            "confidence": "n/a",
            "one_sentence_summary": (
                "Structured output was not applied; the model raw text is preserved "
                "in the PoC section for human review."
            ),
            "decision_drivers": [reason[:800]],
            "recommended_actions": [
                "Review the PoC raw output section in this report.",
            ],
        },
        "competing_hypotheses": [],
        "evidence_vs_inference": {"evidence": [], "inferences": []},
        "ioc_extraction": {},
        "ttp_analysis": [],
        "metadata": {
            "model": model_name,
            "poc_fallback": True,
            "attempt": attempt,
            "inference_time_seconds": (
                (elapsed_repair or 0.0) + elapsed_primary
                if repair_text
                else elapsed_primary
            ),
        },
    }


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
        # Bedrock calls can be long-running; set explicit client timeouts so we don't
        # hang until an outer runtime limit (e.g., Lambda timeout) kills the task.
        default_read_timeout_s = 300
        default_connect_timeout_s = 10
        try:
            read_timeout_s = int(os.environ.get("BEDROCK_READ_TIMEOUT_SECONDS", str(default_read_timeout_s)))
        except ValueError:
            read_timeout_s = default_read_timeout_s
        try:
            connect_timeout_s = int(os.environ.get("BEDROCK_CONNECT_TIMEOUT_SECONDS", str(default_connect_timeout_s)))
        except ValueError:
            connect_timeout_s = default_connect_timeout_s
        # Clamp to sane bounds
        read_timeout_s = max(30, min(read_timeout_s, 900))
        connect_timeout_s = max(1, min(connect_timeout_s, 60))

        self.bedrock_client = boto3.client(
            "bedrock-runtime",
            config=Config(
                read_timeout=read_timeout_s,
                connect_timeout=connect_timeout_s,
            ),
        )
        self.model_id = model_id
        
        # Initialize validator
        ids_file = Path(__file__).parent / "enterprise_attack_v17.1_ids.json"
        self.validator = TTPValidator(ids_file)
        
        # Store last response for markdown generation
        self.last_llm_response = None
        # Store raw content for retry/debugging
        self.last_raw_content = None

    def _build_prompt(self, alert_text: str, alert_time: Optional[str], *, use_tool: bool) -> str:
        """Assemble the full prompt from modular sections.
        
        Args:
            alert_text: Formatted alert text to analyze.
            alert_time: Optional ISO timestamp of the alert.
            use_tool: Whether to use tool-calling mode (affects output schema instructions).
            
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

{PROCEDURE}

Use MITRE ATT&CK v17 technique IDs (format: T#### or T####.###). If unsure, omit; invalid IDs will be discarded.

SECURITY ALERT INPUT:
{alert_text}

---

{output_schema}

---

{RULES}
"""
    
    @staticmethod
    def _is_tooluse_model_error(err: ClientError) -> bool:
        """Detect Bedrock tool-use sequencing ModelErrorException responses.

        Args:
            err: Boto3 ClientError raised by Bedrock converse call.

        Returns:
            True when the error matches known tool-use invalid-sequence shape.
        """
        try:
            code = (err.response or {}).get("Error", {}).get("Code", "")
            msg = (err.response or {}).get("Error", {}).get("Message", "") or str(err)
        except Exception:
            return False
        return code == "ModelErrorException" and "ToolUse" in msg and "invalid sequence" in msg.lower()

    def _converse(self, prompt: str, *, use_tool: bool) -> Dict[str, Any]:
        """Call Bedrock Converse with optional tool configuration.

        Args:
            prompt: Fully rendered prompt text.
            use_tool: Whether to enforce tool-call mode.

        Returns:
            Raw Bedrock Converse response payload.
        """
        # Default to the highest allowed cap; can be overridden via MAX_OUTPUT_TOKENS
        default_max_tokens = 8192
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
    
    def format_alert_input(
        self,
        alert_payload: Any,
        raw_content: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> str:
        """Format alert input with a format-agnostic contract.

        Args:
            alert_payload: Parsed JSON payload or raw text.
            raw_content: Original alert content, used to preserve JSON as submitted.
            content_type: Optional source type hint ('json' or 'text').

        Returns:
            Raw JSON for JSON alerts, or raw text for text alerts.
        """
        if isinstance(alert_payload, str):
            return alert_payload

        if content_type == 'json' and (raw_content or '').strip():
            return raw_content.strip()

        try:
            return json.dumps(alert_payload, ensure_ascii=True, separators=(',', ':'))
        except TypeError:
            return str(alert_payload)
    
    def analyze_ttp(self, alert_text: str, alert_time: Optional[str] = None) -> List[Dict[str, Any]]:
        """Analyze one alert and return validated scored TTP entries."""
        logger.info("Starting TTP analysis")
        start_time = time.time()
        total_ttps = self.validator.get_ttp_count()
        logger.info(f"Loaded {total_ttps} valid TTPs for post-response validation")

        prompt_tool = self._build_prompt(alert_text, alert_time, use_tool=True)
        prompt_raw = self._build_prompt(alert_text, alert_time, use_tool=False)

        if not alert_text or not alert_text.strip():
            logger.error("Alert text is empty or whitespace only")
            self.last_llm_response = {"error": "Empty alert text", "ttp_analysis": []}
            return []

        def _validate_and_postprocess(parsed: Dict[str, Any]) -> Tuple[bool, Optional[str], Dict[str, Any]]:
            parsed = _normalize_llm_result_shape(parsed)
            if not isinstance(parsed, dict):
                return False, f"Expected dict after normalization, got {type(parsed).__name__}", {}
            parsed = _normalize_and_fill_defaults(parsed)

            is_valid, validation_error = validate_response_schema(parsed)
            if not is_valid:
                return False, f"Schema validation: {validation_error}", {}

            ch_ok, ch_err = validate_competing_hypotheses_balance(parsed, strict=False)
            if not ch_ok:
                return False, f"Competing hypotheses validation: {ch_err}", {}

            policy_ok, policy_err = validate_content_policies(parsed)
            if not policy_ok:
                return False, f"Content policy validation: {policy_err}", {}

            parsed["ttp_analysis_raw"] = parsed.get("ttp_analysis", [])
            extracted = extract_scored_ttps(parsed)
            parsed["ttp_analysis"] = self.validator.filter_valid_ttps(extracted)
            return True, None, parsed

        try:
            max_retries = 3
            retry_delay = 5
            response: Optional[Dict[str, Any]] = None
            used_tool = True
            response_attempt = 1
            primary_elapsed = 0.0

            # Phase 1: tool mode
            for attempt in range(max_retries):
                try:
                    logger.info(f"API call attempt {attempt + 1}/{max_retries} (tool_use=True)")
                    t0 = time.time()
                    response = self._converse(prompt_tool, use_tool=True)
                    primary_elapsed = time.time() - t0
                    response_attempt = attempt + 1
                    break
                except ClientError as api_error:
                    if self._is_tooluse_model_error(api_error):
                        logger.warning("Tool-use mode failed with ModelErrorException; falling back to raw JSON mode.")
                        used_tool = False
                        response = None
                        break
                    logger.warning(f"API call attempt {attempt + 1} failed: {str(api_error)}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        retry_delay *= 2
                    else:
                        raise

            # Phase 2: raw JSON mode
            if response is None and not used_tool:
                retry_delay = 5
                for attempt in range(max_retries):
                    try:
                        logger.info(f"API call attempt {attempt + 1}/{max_retries} (tool_use=False)")
                        t0 = time.time()
                        response = self._converse(prompt_raw, use_tool=False)
                        primary_elapsed = time.time() - t0
                        response_attempt = attempt + 1
                        break
                    except ClientError as api_error:
                        logger.warning(f"Raw JSON API call attempt {attempt + 1} failed: {str(api_error)}")
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            retry_delay *= 2
                        else:
                            raise

            if response is None:
                raise RuntimeError("Bedrock converse did not return a response")

            result, error_msg, raw_content = self._parse_bedrock_response(
                response,
                allow_text_fallback=(used_tool is False),
            )
            primary_raw = raw_content or ""
            if primary_raw:
                self.last_raw_content = primary_raw

            ok = False
            final_obj: Dict[str, Any] = {}
            if result is not None:
                logger.info(
                    f"Parsed result keys: {list(result.keys()) if isinstance(result, dict) else type(result).__name__}"
                )
                logger.info(f"Required top-level keys: {REQUIRED_RESPONSE_KEYS_LIST}")
                ok, error_msg, final_obj = _validate_and_postprocess(result)

            repair_raw: Optional[str] = None
            repair_elapsed: Optional[float] = None
            used_prompt_len = len(prompt_tool if used_tool else prompt_raw)
            repair_attempted = False

            if not ok and error_msg:
                repair_attempted = True
                logger.warning(f"Initial parse/validation failed: {error_msg}. Attempting one repair call.")
                prior_output = (primary_raw or str(result) or "")[:4000]
                repair_template = REPAIR_PROMPT_TEMPLATE if used_tool else REPAIR_PROMPT_TEMPLATE_RAW_JSON
                repair_prompt = repair_template.format(error=error_msg, prior_output=prior_output)
                t0 = time.time()
                retry_response = self._converse(repair_prompt, use_tool=used_tool)
                repair_elapsed = time.time() - t0
                used_prompt_len = len(repair_prompt)
                retry_result, retry_error, retry_raw = self._parse_bedrock_response(
                    retry_response,
                    allow_text_fallback=(used_tool is False),
                )
                repair_raw = retry_raw or ""
                if repair_raw:
                    self.last_raw_content = repair_raw
                if retry_result is not None:
                    ok, error_msg, final_obj = _validate_and_postprocess(retry_result)
                else:
                    ok = False
                    error_msg = retry_error or error_msg

            if not ok:
                fallback = build_poc_fallback_llm_payload(
                    primary_text=primary_raw,
                    repair_text=repair_raw,
                    reason=error_msg or "Response parsing/validation failed",
                    model_name=self.model_id,
                    attempt=response_attempt,
                    elapsed_primary=primary_elapsed,
                    elapsed_repair=repair_elapsed,
                )
                self.last_llm_response = fallback
                return []

            final_obj["metadata"] = {
                "model": self.model_id,
                "inference_time_seconds": (
                    (repair_elapsed or 0.0) + primary_elapsed
                    if repair_attempted and repair_elapsed is not None
                    else primary_elapsed
                ),
                "prompt_length": used_prompt_len,
                "attempt": response_attempt,
                "repair_attempted": repair_attempted,
            }
            final_obj["raw_response"] = repair_raw if repair_attempted and repair_raw else primary_raw
            self.last_llm_response = final_obj

            valid_ttps = final_obj.get("ttp_analysis", [])
            logger.info(f"Final valid TTPs: {len(valid_ttps)}")
            total_time = time.time() - start_time
            logger.info(f"Total TTP analysis completed in {total_time:.2f} seconds")
            return valid_ttps

        except Exception as e:
            logger.error(f"Unexpected error calling LLM: {str(e)}")
            logger.error(f"Exception type: {type(e).__name__}")
            self.last_llm_response = {"error": f"LLM API error: {e}", "ttp_analysis": []}
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

