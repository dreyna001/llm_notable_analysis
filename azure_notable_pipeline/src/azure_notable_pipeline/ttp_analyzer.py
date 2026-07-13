"""Claude Sonnet TTP analysis with deterministic validation and policy gates."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from . import azure_anthropic_gateway
from .verdicts import ALLOWED_VERDICTS, normalize_verdict

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


# Native Anthropic Messages tool schema; this is the durable analysis contract.
ANALYZE_NOTABLE_INPUT_SCHEMA = {
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
                    "enum": list(ALLOWED_VERDICTS),
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

ANALYZE_NOTABLE_TOOL = {
    "name": "analyze_notable",
    "description": "Analyze a security alert and return structured TTP analysis",
    "input_schema": ANALYZE_NOTABLE_INPUT_SCHEMA,
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

# Repair prompt template for the one bounded structured-output repair call
REPAIR_PROMPT_TEMPLATE = """Your previous response could not be parsed or validated.

Error: {error}

Previous output (truncated):
{prior_output}

Repair only formatting, JSON validity, schema shape, enum values, and missing required containers. Do not improve, expand, reinterpret, or add new analysis.

Do not add facts, IOCs, hosts, users, timestamps, verdict reasons, TTPs, queries, or result interpretations that were not present in the previous output or original prompt context.

If a required field cannot be supported, use "unknown" for scalar fields and [] for list fields where the schema allows it.

Preserve valid fields from the previous output whenever they already satisfy the contract. Only change fields needed to pass validation.

OUTPUT CONTRACT:
{contract}

Please use the analyze_notable tool to return your analysis. Return ONLY the tool call. No markdown fences, comments, prose, or explanation."""

# Repair prompt for raw-JSON mode (no tool use)
REPAIR_PROMPT_TEMPLATE_RAW_JSON = """Your previous response could not be parsed or validated.

Error: {error}

Previous output (truncated):
{prior_output}

Repair only formatting, JSON validity, schema shape, enum values, and missing required containers. Do not improve, expand, reinterpret, or add new analysis.

Do not add facts, IOCs, hosts, users, timestamps, verdict reasons, TTPs, queries, or result interpretations that were not present in the previous output or original prompt context.

If a required field cannot be supported, use "unknown" for scalar fields and [] for list fields where the schema allows it.

Preserve valid fields from the previous output whenever they already satisfy the contract. Only change fields needed to pass validation.

OUTPUT CONTRACT:
{contract}

Return only one valid JSON object. No markdown fences, comments, prose, or explanation."""

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

OUTPUT_CONTRACT_CONSTRAINTS = """
Additional constraints:
- This contract is mandatory; omit unsupported facts rather than inventing values.
- Direct alert evidence must come only from SECURITY ALERT INPUT.
- SOC_OPERATIONAL_CONTEXT may inform analyst pivots and recommended validation steps, but it must not create findings, verdicts, IOCs, or TTP evidence by itself.
- Keep direct evidence, inference, and recommended next steps separate.
- explanation: must end with "Uncertainty: [brief statement]".
- URLs are only allowed in ioc_extraction.urls[]; no URLs elsewhere.
- Leave arrays empty [] when no items apply.
- alert_reconciliation: object with verdict, confidence, one_sentence_summary, decision_drivers (list), recommended_actions (list).
- alert_reconciliation.verdict MUST be exactly one of: "likely_benign", "likely_malicious", "unknown".
- Use "likely_malicious" when direct alert evidence supports adversary activity or a true-positive security concern.
- Use "likely_benign" when direct alert evidence supports benign, administrative, expected, or false-positive activity.
- Use "unknown" when the evidence is insufficient, conflicting, missing critical context, or only supports competing benign/adversary hypotheses.
- ATT&CK techniques are behavior labels, not verdicts; do not mark a verdict true-positive solely because a technique can be mapped.
- alert_reconciliation.confidence is confidence in the selected verdict, not an independent probability that the alert is malicious.
"""

OUTPUT_SCHEMA = f"""
Use the analyze_notable tool to return your analysis. Follow the tool's JSON schema exactly.

{OUTPUT_CONTRACT_CONSTRAINTS}
Top-level keys (required): alert_reconciliation, competing_hypotheses, evidence_vs_inference, ioc_extraction, ttp_analysis.
- Return ONLY the tool call; no extra text.
"""

OUTPUT_SCHEMA_RAW_JSON = f"""
Return ONLY a single JSON object matching the schema. Do not include markdown fences or any extra text.

{OUTPUT_CONTRACT_CONSTRAINTS}
Top-level keys (required):
- alert_reconciliation
- competing_hypotheses
- evidence_vs_inference
- ioc_extraction
- ttp_analysis
"""

SOC_CONTEXT_RULES = """
SOC CONTEXT RULES:
- The SOC_OPERATIONAL_CONTEXT block is operational guidance only.
- Never treat SOC_OPERATIONAL_CONTEXT as direct alert evidence.
- Never copy SOC context into evidence_vs_inference.evidence, ttp_analysis[*].evidence_fields, or ioc_extraction unless present in SECURITY ALERT INPUT.
- If SOC context is weak, missing, or conflicting, keep guidance broad and explicitly use "unknown" where needed.
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

    verdict = result["alert_reconciliation"].get("verdict")
    if verdict not in ALLOWED_VERDICTS:
        return (
            False,
            "alert_reconciliation.verdict must be one of: "
            + ", ".join(ALLOWED_VERDICTS),
        )

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
        "verdict": normalize_verdict(ar.get("verdict")),
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


class AnthropicAnalyzer:
    """Coordinate bounded Sonnet analysis and deterministic post-processing."""

    def __init__(
        self,
        deployment: str = "claude-sonnet-4-6",
        *,
        base_url: str | None = None,
        gateway: Any | None = None,
        max_output_tokens: int | None = None,
        propagate_retryable: bool = False,
    ) -> None:
        deployment = deployment.strip()
        if not deployment:
            raise ValueError("deployment cannot be blank")
        self.deployment = deployment
        self.base_url = (
            base_url
            if base_url is not None
            else os.getenv("AZURE_AI_FOUNDRY_ANTHROPIC_BASE_URL", "")
        )
        self.gateway = gateway
        self.max_output_tokens = self._resolve_max_output_tokens(max_output_tokens)
        self.propagate_retryable = bool(propagate_retryable)

        ids_file = Path(__file__).parent / "enterprise_attack_v17.1_ids.json"
        self.validator = TTPValidator(ids_file)
        self.last_llm_response: Optional[Dict[str, Any]] = None
        self.last_raw_content: Optional[str] = None

    @staticmethod
    def _resolve_max_output_tokens(value: int | None) -> int:
        if value is None:
            raw_value = os.getenv("MAX_OUTPUT_TOKENS", "8192")
            try:
                value = int(raw_value)
            except ValueError:
                value = 8192
        return max(256, min(value, 8192))

    def _build_prompt(
        self,
        alert_text: str,
        alert_time: Optional[str],
        *,
        use_tool: bool = True,
        advisory_context: Optional[str] = None,
    ) -> str:
        """Assemble the unchanged contract-first analyzer prompt."""

        alert_time_str = f"\n**ALERT_TIME:** {alert_time}\n" if alert_time else ""
        output_schema = OUTPUT_SCHEMA if use_tool else OUTPUT_SCHEMA_RAW_JSON
        if advisory_context and advisory_context.strip():
            soc_context_block = (
                "SOC_OPERATIONAL_CONTEXT\n" f"{advisory_context.strip()}\n"
            )
        else:
            soc_context_block = "SOC_OPERATIONAL_CONTEXT\n(none)\n"

        return f"""You are a cybersecurity expert producing a structured SOC analysis from a single alert.

TASK:
Analyze one alert only. Produce a verdict, separate direct evidence from inference,
extract supported IOCs, map MITRE ATT&CK only when direct evidence supports it,
and generate competing benign/adversary hypotheses for analyst validation.

OUTPUT CONTRACT:
{output_schema}

---
{alert_time_str}
{ANALYST_DOCTRINE}

{EVIDENCE_GATE}

{SCORING_RUBRIC}

{CAUSAL_HUMILITY}

{PROCEDURE}

Use MITRE ATT&CK v17 technique IDs (format: T#### or T####.###). If unsure, omit; invalid IDs will be discarded.

SECURITY ALERT INPUT:
{alert_text}

---

{soc_context_block}

{SOC_CONTEXT_RULES}

---

{RULES}
"""

    def _request_analysis(self, prompt: str) -> azure_anthropic_gateway.AnthropicAnalysis:
        return azure_anthropic_gateway.analyze_notable(
            messages=[{"role": "user", "content": prompt}],
            deployment=self.deployment,
            tool=ANALYZE_NOTABLE_TOOL,
            base_url=self.base_url,
            max_tokens=self.max_output_tokens,
            temperature=0.1,
            gateway=self.gateway,
        )

    def _validate_and_postprocess(
        self, parsed: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        parsed = _normalize_llm_result_shape(parsed)
        if not isinstance(parsed, dict):
            return (
                False,
                f"Expected dict after normalization, got {type(parsed).__name__}",
                {},
            )
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
        parsed["ttp_analysis"] = self.validator.filter_valid_ttps(
            extract_scored_ttps(parsed)
        )
        return True, None, parsed

    def format_alert_input(
        self,
        alert_payload: Any,
        raw_content: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> str:
        """Format JSON or text without inventing a cloud event envelope."""

        if isinstance(alert_payload, str):
            return alert_payload
        if content_type == "json" and (raw_content or "").strip():
            return str(raw_content).strip()
        try:
            return json.dumps(alert_payload, ensure_ascii=True, separators=(",", ":"))
        except TypeError:
            return str(alert_payload)

    def analyze_ttp(
        self,
        alert_text: str,
        alert_time: Optional[str] = None,
        advisory_context: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Analyze one alert with one primary call and at most one repair call."""

        logger.info("Starting TTP analysis")
        start_time = time.time()
        if not alert_text or not alert_text.strip():
            self.last_llm_response = {
                "error": "Empty alert text",
                "ttp_analysis": [],
            }
            return []

        prompt = self._build_prompt(
            alert_text,
            alert_time,
            use_tool=True,
            advisory_context=advisory_context,
        )
        primary_elapsed = 0.0
        primary_raw = ""
        primary_usage: dict[str, int] = {}
        result: Optional[Dict[str, Any]] = None
        error_msg: Optional[str] = None

        try:
            call_started = time.time()
            try:
                response = self._request_analysis(prompt)
                primary_elapsed = time.time() - call_started
                primary_raw = response.raw_output
                result = response.payload
                if response.input_tokens is not None:
                    primary_usage["input_tokens"] = response.input_tokens
                if response.output_tokens is not None:
                    primary_usage["output_tokens"] = response.output_tokens
            except azure_anthropic_gateway.AnthropicGatewayResponseError as exc:
                primary_elapsed = time.time() - call_started
                primary_raw = exc.raw_output
                error_msg = str(exc)

            self.last_raw_content = primary_raw or None
            ok = False
            final_obj: Dict[str, Any] = {}
            if result is not None:
                ok, error_msg, final_obj = self._validate_and_postprocess(result)

            repair_raw: Optional[str] = None
            repair_elapsed: Optional[float] = None
            repair_attempted = False
            used_prompt_len = len(prompt)

            if not ok and error_msg:
                repair_attempted = True
                prior_output = (primary_raw or str(result) or "")[:4000]
                repair_prompt = REPAIR_PROMPT_TEMPLATE.format(
                    error=error_msg,
                    prior_output=prior_output,
                    contract=OUTPUT_SCHEMA,
                )
                call_started = time.time()
                try:
                    repair_response = self._request_analysis(repair_prompt)
                    repair_elapsed = time.time() - call_started
                    repair_raw = repair_response.raw_output
                    ok, error_msg, final_obj = self._validate_and_postprocess(
                        repair_response.payload
                    )
                except azure_anthropic_gateway.AnthropicGatewayResponseError as exc:
                    repair_elapsed = time.time() - call_started
                    repair_raw = exc.raw_output
                    error_msg = str(exc)
                    ok = False
                used_prompt_len = len(repair_prompt)
                self.last_raw_content = repair_raw or self.last_raw_content

            if not ok:
                self.last_llm_response = build_poc_fallback_llm_payload(
                    primary_text=primary_raw,
                    repair_text=repair_raw,
                    reason=error_msg or "Response parsing/validation failed",
                    model_name=self.deployment,
                    attempt=1,
                    elapsed_primary=primary_elapsed,
                    elapsed_repair=repair_elapsed,
                )
                return []

            final_obj["metadata"] = {
                "model": self.deployment,
                "inference_time_seconds": (
                    primary_elapsed + (repair_elapsed or 0.0)
                ),
                "prompt_length": used_prompt_len,
                "attempt": 1,
                "repair_attempted": repair_attempted,
                **primary_usage,
            }
            final_obj["raw_response"] = (
                repair_raw if repair_attempted and repair_raw else primary_raw
            )
            self.last_llm_response = final_obj
            return final_obj.get("ttp_analysis", [])
        except azure_anthropic_gateway.AnthropicGatewayError as exc:
            if self.propagate_retryable and isinstance(
                exc,
                (
                    azure_anthropic_gateway.AnthropicGatewayTimeoutError,
                    azure_anthropic_gateway.AnthropicGatewayRateLimitError,
                    azure_anthropic_gateway.AnthropicGatewayServiceError,
                ),
            ):
                raise
            logger.warning("Anthropic Foundry analysis failed: %s", type(exc).__name__)
            self.last_llm_response = {
                "error": f"LLM API error: {exc}",
                "ttp_analysis": [],
            }
            return []
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.exception("Unexpected error calling Anthropic Foundry")
            self.last_llm_response = {
                "error": f"LLM API error: {exc}",
                "ttp_analysis": [],
            }
            return []
        finally:
            logger.info(
                "TTP analysis completed in %.2f seconds", time.time() - start_time
            )


def extract_score(ttp: Dict[str, Any]) -> float:
    """Extract score from a normalized TTP dictionary."""

    for key in ("score", "confidence_score", "confidence"):
        if key in ttp:
            return ttp[key]
    return 0.0
