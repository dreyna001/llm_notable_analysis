"""Local LLM client for vLLM/OpenAI-compatible inference (no onprem-llm-sdk).

Same behavior as local_llm_client.LocalLLMClient but uses requests via
openai_transport_nonsdk instead of onprem_llm_sdk.VLLMClient.
"""

import json
import logging
import re
import time
import ast
from threading import BoundedSemaphore
from typing import List, Dict, Any, Optional, Tuple
import requests

from .openai_transport_nonsdk import (
    ClientRequestError,
    RateLimitError,
    RequestTimeoutError,
    ResponseFormatError,
    ServerError,
    TransportError,
    openai_chat_complete,
)

from .config import Config
from .ttp_validator import TTPValidator

logger = logging.getLogger(__name__)

# Qwen3 chat templates may emit a "thinking" trace before the visible answer.
# When present, the final user-facing segment usually follows this marker.
_QWEN_THINK_END = "</think>"


def strip_llm_thinking_preamble(text: str) -> str:
    """Drop Qwen-style thinking trace; return the tail after the last think closer.

    If no marker is present, returns ``text`` unchanged (aside from outer strip).

    Args:
        text: Raw model output text.

    Returns:
        Cleaned response text suitable for downstream JSON parsing.
    """
    if not text or _QWEN_THINK_END not in text:
        return text.strip() if text else text
    tail = text.split(_QWEN_THINK_END)[-1].strip()
    return tail if tail else text.strip()


def _model_name_suggests_qwen(model_name: str) -> bool:
    """Return whether model name likely refers to a Qwen-family model.

    Args:
        model_name: Configured model name.

    Returns:
        True when the model name includes `qwen` (case-insensitive).
    """
    return "qwen" in (model_name or "").lower()


class _RequestsPostSession:
    """Session adapter preserving existing test hooks on requests.post.

    Tests in this repo patch `local_llm_client_nonsdk.requests.post`; this adapter
    keeps that patch point intact for HTTP calls.
    """

    def post(self, *args, **kwargs):
        """Call `requests.post` while normalizing mock/test response attributes.

        Args:
            *args: Positional arguments forwarded to `requests.post`.
            **kwargs: Keyword arguments forwarded to `requests.post`.

        Returns:
            Response-like object with normalized `status_code` and `text` fields.
        """
        response = requests.post(*args, **kwargs)

        # Some unit tests use MagicMock responses without status_code; default to
        # success when raise_for_status() doesn't raise.
        status_code = getattr(response, "status_code", None)
        if not isinstance(status_code, int):
            try:
                response.raise_for_status()
                response.status_code = 200
            except requests.exceptions.HTTPError as exc:
                err_resp = getattr(exc, "response", None)
                response.status_code = getattr(err_resp, "status_code", 500)

        if not isinstance(getattr(response, "text", ""), str):
            response.text = str(getattr(response, "text", ""))

        return response


# =============================================================================
# s3_testing-compatible prompt + output contract + validation helpers
# =============================================================================

# Some models / intermediaries occasionally wrap the JSON payload in an extra
# top-level container key (e.g., {"analysis": {...}}). This helper unwraps
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

    Args:
        result: Parsed model output object.

    Returns:
        Unwrapped dict when known wrapper keys are detected; otherwise returns
        `result` unchanged.
    """
    if not isinstance(result, dict):
        return result

    for k in _COMMON_RESULT_WRAPPER_KEYS:
        v = result.get(k)
        if isinstance(v, dict):
            logger.warning(f"Unwrapping LLM result from container key: {k!r}")
            return v

    if len(result) == 1:
        ((only_key, only_val),) = result.items()
        if isinstance(only_val, dict):
            logger.warning(
                f"Unwrapping singleton LLM result container key: {only_key!r}"
            )
            return only_val

    return result


# Required keys and their expected types for schema validation (matches s3_testing)
REQUIRED_RESPONSE_KEYS: Dict[str, type] = {
    "alert_reconciliation": dict,
    "competing_hypotheses": list,
    "evidence_vs_inference": dict,
    "ioc_extraction": dict,
    "ttp_analysis": list,
}

_SPL_QUERY_STRATEGIES = {"resolve_unknown", "check_contradiction"}
_SPL_QUERY_FIELDS = (
    "query_strategy",
    "primary_spl_query",
    "why_this_query",
    "supports_if",
    "weakens_if",
)


ANALYST_DOCTRINE = """
ANALYST DOCTRINE (apply to every case)
- MITRE ATT&CK is many-to-many: a single technique may support several tactics. Always state (a) the tactic you're assigning in this alert AND (b) other plausible tactics this technique commonly serves (tactic-span note). Base on MITRE ATT&CK v17.
- FACT vs. INFERENCE: List literal, direct alert evidence first (field=value from the alert), then inferences and assumptions separately (with uncertainty).
- IOC labeling hygiene: Do not list core OS/generic binaries as IOCs without explicit malicious context. Instead, list as "system_components_observed" if present in the alert.
- STATELESS ANALYSIS: Reasoning must rely only on observable fields in this notable. If a required fact is not present, state "unknown" and list what would disambiguate.
""".strip()


EVIDENCE_GATE = """
EVIDENCE-GATE: Only include a technique (TTP) if:
A. There is a direct data-component match in the alert (quote it).
B. Your explanation cites the matching field/value.
C. No inference or external context is necessary.
D. If evidence correctness depends on context not in the log (e.g., domain internal/external, IP a DC), drop to the parent technique or reduce confidence by >=0.20 and state the missing context in your explanation.
""".strip()


SCORING_RUBRIC = """
Scoring Rubric:
- high >= 0.80 = direct, unambiguous
- med 0.50-0.79 = strongly suggestive; one element missing
- low < 0.30 = plausible but needs corroboration
""".strip()


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
""".strip()


SPL_QUERY_GENERATION_RULES = """
SPL QUERY GENERATION (Enabled):
- For each of the EXACTLY 6 hypotheses, include exactly one primary Splunk query.
- Each hypothesis must include:
  - query_strategy: "resolve_unknown" or "check_contradiction"
  - primary_spl_query: a real SPL query string
  - why_this_query: short rationale
  - supports_if: result pattern that strengthens the hypothesis
  - weakens_if: result pattern that weakens the hypothesis
- Focus each query on a decision-changing unknown or strongest contradiction.
- Do not use placeholders such as <INDEX>, <SOURCETYPE>, or similar tokens.
- Do not output pseudo-queries such as "search ...".
- Do not invent environment-specific tokens (indexes/sourcetypes/macros/CIM data model names) unless explicitly present in SECURITY ALERT INPUT.
""".strip()


PROCEDURE = """
PROCEDURE:
1. Decode/deobfuscate common encodings (Base64, hex, URL-encoded, gzip) if found.
2. Use sub-techniques when specific variant is confirmed (e.g., T1059.001 for PowerShell); default to parent techniques otherwise.
""".strip()


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
""".strip()


RULES = """
RULES:
- NO EMOJIS OR UNICODE SYMBOLS; use only plain ASCII text.
- Never output example.com or PLACEHOLDER anywhere.
""".strip()

SOC_CONTEXT_RULES = """
SOC CONTEXT RULES:
- The SOC_OPERATIONAL_CONTEXT block is operational guidance only.
- Never treat SOC_OPERATIONAL_CONTEXT as direct alert evidence.
- Never copy SOC context into evidence_vs_inference.evidence, ttp_analysis[*].evidence_fields, or ioc_extraction unless present in SECURITY ALERT INPUT.
- If SOC context is weak, missing, or conflicting, keep guidance broad and explicitly use "unknown" where needed.
""".strip()


REPAIR_PROMPT_TEMPLATE_RAW_JSON = """Your previous response could not be parsed or validated.

Error: {error}

Previous output (truncated):
{prior_output}

Return ONLY a single valid JSON object matching the schema and constraints. Do not include markdown fences or any extra text.
"""


def validate_response_schema(result: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Validate required top-level keys and value container types.

    Args:
        result: Parsed LLM response object.

    Returns:
        Tuple of `(is_valid, error_message)`. `error_message` is `None` when
        validation succeeds.
    """
    if not isinstance(result, dict):
        return False, f"Expected dict, got {type(result).__name__}"

    for key, expected_type in REQUIRED_RESPONSE_KEYS.items():
        if key not in result:
            return False, f"Missing required key: {key}"
        if not isinstance(result[key], expected_type):
            return (
                False,
                f"Key '{key}' must be {expected_type.__name__}, got {type(result[key]).__name__}",
            )

    return True, None


def validate_competing_hypotheses_balance(
    result: Dict[str, Any], *, strict: bool = False
) -> Tuple[bool, Optional[str]]:
    """Validate competing_hypotheses shape.

    In non-strict mode, this enforces only "list of objects" for resilience with
    local models. In strict mode, it enforces EXACTLY 3 benign + 3 adversary
    hypotheses (6 total).

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
            f"competing_hypotheses must contain exactly 6 items, got {len(ch)}",
        )
    benign = 0
    adversary = 0
    for i, item in enumerate(ch):
        htype = str(item.get("hypothesis_type", "")).strip().lower()
        if htype == "benign":
            benign += 1
        elif htype == "adversary":
            adversary += 1
        else:
            return (
                False,
                f"competing_hypotheses[{i}].hypothesis_type must be benign or adversary",
            )
    if benign != 3 or adversary != 3:
        return (
            False,
            f"competing_hypotheses must include exactly 3 benign and 3 adversary; got benign={benign}, adversary={adversary}",
        )
    return True, None


def _validate_spl_query_contract(result: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Validate strict SPL query contract for per-hypothesis query generation."""
    ch = result.get("competing_hypotheses")
    if not isinstance(ch, list):
        return False, "competing_hypotheses must be a list"

    ch_ok, ch_err = validate_competing_hypotheses_balance(result, strict=True)
    if not ch_ok:
        return False, ch_err

    for i, item in enumerate(ch):
        if not isinstance(item, dict):
            return False, f"competing_hypotheses[{i}] must be an object"

        strategy = str(item.get("query_strategy", "")).strip().lower()
        if strategy not in _SPL_QUERY_STRATEGIES:
            return (
                False,
                f"competing_hypotheses[{i}].query_strategy must be one of {_SPL_QUERY_STRATEGIES}",
            )

        primary_query = str(item.get("primary_spl_query", "")).strip()
        if not primary_query:
            return (
                False,
                f"competing_hypotheses[{i}].primary_spl_query must be non-empty",
            )
        if re.search(r"<[^>]+>", primary_query):
            return (
                False,
                f"competing_hypotheses[{i}].primary_spl_query contains placeholder token",
            )
        if "..." in primary_query:
            return (
                False,
                f"competing_hypotheses[{i}].primary_spl_query contains pseudo-query ellipsis",
            )
        if re.search(r"\bindex\s*=", primary_query, re.IGNORECASE):
            return (
                False,
                f"competing_hypotheses[{i}].primary_spl_query must not assume index names",
            )
        if re.search(r"\bsourcetype\s*=", primary_query, re.IGNORECASE):
            return (
                False,
                f"competing_hypotheses[{i}].primary_spl_query must not assume sourcetypes",
            )
        if re.search(r"`[^`]+`", primary_query):
            return (
                False,
                f"competing_hypotheses[{i}].primary_spl_query must not assume macros",
            )
        if re.search(r"\bdatamodel\s*=", primary_query, re.IGNORECASE):
            return (
                False,
                f"competing_hypotheses[{i}].primary_spl_query must not assume CIM data models",
            )

        for field in ("why_this_query", "supports_if", "weakens_if"):
            value = str(item.get(field, "")).strip()
            if not value:
                return (
                    False,
                    f"competing_hypotheses[{i}].{field} must be non-empty",
                )

    return True, None


def _normalize_competing_hypotheses(
    value: Any, *, spl_query_enabled: bool
) -> List[Dict[str, Any]]:
    """Normalize competing hypotheses and optionally strip SPL query fields."""
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        hyp = dict(item)
        if spl_query_enabled:
            strategy = str(hyp.get("query_strategy", "")).strip().lower()
            hyp["query_strategy"] = strategy
            for field in ("primary_spl_query", "why_this_query", "supports_if", "weakens_if"):
                val = hyp.get(field, "")
                hyp[field] = str(val).strip() if val is not None else ""
        else:
            for field in _SPL_QUERY_FIELDS:
                hyp.pop(field, None)
        normalized.append(hyp)
    return normalized


def _coerce_ioc_extraction(value: Any) -> Dict[str, Any]:
    """Coerce IOC payload into stable markdown-rendering shape.

    Args:
        value: Arbitrary model-provided IOC structure.

    Returns:
        Dict with known IOC keys mapped to lists of strings.
    """
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
        # Keep known keys; coerce leaf values into lists of strings.
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

    # If the model returned a list of strings, do light heuristic bucketing.
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

    # Anything else: return empty base.
    return base


def _coerce_evidence_vs_inference(value: Any) -> Dict[str, Any]:
    """Coerce evidence/inference payload into a stable dict contract.

    Args:
        value: Arbitrary model-provided evidence/inference shape.

    Returns:
        Dict with `evidence` and `inferences` lists of strings.
    """
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
            continue

    return out


def _extract_ttp_ids_from_text(text: str) -> List[str]:
    """Extract unique technique IDs from arbitrary text (including preamble)."""
    if not text:
        return []
    ids = _TTP_ID_RE.findall(text)
    seen = set()
    out: List[str] = []
    for t in ids:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _normalize_and_fill_defaults(
    parsed: Dict[str, Any], *, spl_query_enabled: bool = False
) -> Dict[str, Any]:
    """Make the parsed object robust to minor schema drift from local models."""
    if not isinstance(parsed, dict):
        return {}

    out = dict(parsed)
    # Ensure required top-level keys exist with reasonable defaults, in stable order.
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
    out["competing_hypotheses"] = _normalize_competing_hypotheses(
        out.get("competing_hypotheses", []),
        spl_query_enabled=spl_query_enabled,
    )
    out["evidence_vs_inference"] = _coerce_evidence_vs_inference(
        out.get("evidence_vs_inference", {})
    )
    out["ioc_extraction"] = _coerce_ioc_extraction(out.get("ioc_extraction", {}))
    out["ttp_analysis"] = _coerce_ttp_analysis(out.get("ttp_analysis", []))
    return out


def _iter_strings(obj: Any, *, path: str = "") -> List[Tuple[str, str]]:
    """Collect all string leaf nodes from nested dict/list structures.

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
    """Validate policy constraints not fully expressible via JSON schema.

    Args:
        result: Parsed structured model output.

    Returns:
        Tuple of `(is_valid, error_message)`.
    """
    for p, s in _iter_strings(result):
        s_lower = s.lower()
        if "example.com" in s_lower:
            return False, f"Disallowed placeholder domain in {p}"
        if "placeholder" in s_lower:
            return False, f"Disallowed PLACEHOLDER token in {p}"
        if "http://" in s_lower or "https://" in s_lower:
            if not p.startswith("ioc_extraction.urls["):
                return False, f"Disallowed URL outside ioc_extraction.urls: {p}"
    return True, None


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def extract_scored_ttps(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract a normalized scored TTP list from a parsed LLM result.

    Mirrors the post-processing used in `s3_testing/ttp_analyzer.py`:
    - emits a stable shape used by markdown rendering
    - normalizes score from confidence_score/score/confidence

    Args:
        result: Parsed structured model output.

    Returns:
        List of normalized scored TTP dictionaries.
    """
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


def _extract_brace_balanced_object(text: str) -> Optional[str]:
    """Extract the first complete brace-balanced JSON object from text.

    Args:
        text: Candidate text beginning with `{`.

    Returns:
        Extracted JSON object string, or None when no balanced object exists.
    """
    if not text or not text.startswith("{"):
        return None

    depth = 0
    in_string = False
    escape_next = False

    for i, char in enumerate(text):
        if escape_next:
            escape_next = False
            continue

        if char == "\\" and in_string:
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[: i + 1]

    return None


def extract_json_object(raw_text: str) -> Tuple[str, Optional[str]]:
    """Extract JSON object text from a model response.

    Args:
        raw_text: Raw model response text that may include preamble or fences.

    Returns:
        Tuple of `(json_candidate, extraction_note)`.
    """
    if not raw_text:
        return raw_text, None

    text = raw_text.strip()
    notes: List[str] = []

    if text.startswith("\ufeff"):
        text = text[1:]
        notes.append("stripped BOM")

    fence_pattern = r"^```(?:json)?\s*\n?(.*?)\n?```\s*$"
    fence_match = re.match(fence_pattern, text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1).strip()
        notes.append("stripped code fences")

    text_stripped = text.strip()
    if text_stripped.startswith("{"):
        extracted = _extract_brace_balanced_object(text_stripped)
        if extracted and extracted != text_stripped:
            notes.append("extracted brace-balanced object")
            text = extracted
        elif extracted:
            text = extracted
    else:
        first_brace = text.find("{")
        if first_brace != -1:
            notes.append(f"skipped {first_brace} chars of preamble")
            extracted = _extract_brace_balanced_object(text[first_brace:])
            if extracted:
                text = extracted
                notes.append("extracted brace-balanced object")
            else:
                text = text[first_brace:]

    return text, ("; ".join(notes) if notes else None)


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
    """Build fallback payload that preserves raw model text for PoC review.

    Args:
        primary_text: Raw text from the primary model call.
        repair_text: Raw text from schema-repair call, if attempted.
        reason: Short reason for fallback.
        model_name: Model identifier used for the calls.
        attempt: Attempt number that produced fallback.
        elapsed_primary: Primary call duration in seconds.
        elapsed_repair: Optional repair call duration in seconds.

    Returns:
        JSON-serializable fallback payload aligned to report rendering contract.
    """
    primary_text = (primary_text or "").strip()
    repair_text = (repair_text or "").strip()
    combined = primary_text
    if repair_text:
        combined += (
            "\n\n---\n\n### Secondary call (schema repair attempt) — raw output\n\n"
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
                "Structured output was not applied; the model's raw text is preserved "
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


class LocalLLMClient:
    """Client for local LLM inference via vLLM/OpenAI-compatible endpoint."""

    def __init__(self, config: Config, ttp_validator: TTPValidator):
        """Initialize the local LLM client.

        Args:
            config: Service configuration.
            ttp_validator: TTPValidator instance for filtering invalid TTPs.
        """
        self.config = config
        self.ttp_validator = ttp_validator
        self._session = _RequestsPostSession()
        self._semaphore = BoundedSemaphore(
            max(1, int(getattr(self.config, "MAX_WORKERS", 1)))
        )
        self._rag_provider = self._init_rag_provider()

    def _init_rag_provider(self):
        """Initialize optional RAG context provider (best-effort).

        Returns:
            RAG context provider instance when enabled/available, otherwise None.
        """
        if not bool(getattr(self.config, "RAG_ENABLED", False)):
            return None
        try:
            from onprem_rag_notable_analysis.future.rag_config import RAGConfig
            from onprem_rag_notable_analysis.future.retrieval import RAGContextProvider

            rag_cfg = RAGConfig(
                enabled=True,
                sqlite_path=self.config.RAG_SQLITE_PATH,
                faiss_path=self.config.RAG_FAISS_PATH,
                embedding_model_name=self.config.RAG_EMBEDDING_MODEL,
                max_snippets_120b=self.config.RAG_MAX_SNIPPETS_120B,
                max_snippets_20b=self.config.RAG_MAX_SNIPPETS_20B,
                context_budget_chars_120b=self.config.RAG_CONTEXT_BUDGET_CHARS_120B,
                context_budget_chars_20b=self.config.RAG_CONTEXT_BUDGET_CHARS_20B,
            )
            provider = RAGContextProvider.from_config(rag_cfg)
            if provider is None:
                logger.warning("RAG is enabled but provider initialization was skipped.")
            else:
                logger.info(
                    "RAG provider enabled with sqlite=%s faiss=%s",
                    rag_cfg.sqlite_path,
                    rag_cfg.faiss_path,
                )
            return provider
        except Exception as exc:
            logger.warning("Failed to initialize RAG provider; continuing without RAG: %s", exc)
            return None

    def _build_soc_operational_context(self, alert_text: str) -> str:
        """Build SOC operational context block from retrieval layer.

        Args:
            alert_text: Prompt-formatted alert text.

        Returns:
            Rendered `SOC_OPERATIONAL_CONTEXT` block or an empty string.
        """
        if self._rag_provider is None:
            return ""
        try:
            return self._rag_provider.build_context(
                alert_text=alert_text, llm_model_name=self.config.LLM_MODEL_NAME
            )
        except Exception as exc:
            logger.warning("RAG context build failed; continuing without context: %s", exc)
            return ""

    def _build_prompt(
        self,
        alert_text: str,
        alert_time: Optional[str] = None,
        soc_operational_context: str = "",
    ) -> str:
        """Build the analysis prompt.

        Ported from s3_notable_pipeline/ttp_analyzer.py format_alert_input().

        Args:
            alert_text: The alert content to analyze.
            alert_time: Optional timestamp for time window references.
            soc_operational_context: Optional retrieval-grounded SOC context block.

        Returns:
            Formatted prompt string.
        """
        alert_time_str = f"\n**ALERT_TIME:** {alert_time}\n" if alert_time else ""

        qwen_json_hint = ""
        if _model_name_suggests_qwen(self.config.LLM_MODEL_NAME):
            qwen_json_hint = (
                "Output policy: Respond with a single JSON object only—no markdown fences, "
                "no text before or after the object. /no_think\n\n"
            )

        soc_context_block = (soc_operational_context or "").strip()
        if not soc_context_block:
            soc_context_block = "SOC_OPERATIONAL_CONTEXT\n(none)\n"

        spl_query_block = ""
        if bool(getattr(self.config, "SPL_QUERY_GENERATION_ENABLED", False)):
            spl_query_block = f"\n{SPL_QUERY_GENERATION_RULES}\n"

        return f"""{qwen_json_hint}You are a cybersecurity expert mapping MITRE ATT&CK techniques from a single alert.
{alert_time_str}
---

{ANALYST_DOCTRINE}

{EVIDENCE_GATE}

{SCORING_RUBRIC}

{CAUSAL_HUMILITY}

{spl_query_block}

{PROCEDURE}

Use MITRE ATT&CK v17 technique IDs (format: T#### or T####.###). If unsure, omit; invalid IDs will be discarded.

SECURITY ALERT INPUT:
{alert_text}

---

{soc_context_block}

{SOC_CONTEXT_RULES}

---

{OUTPUT_SCHEMA_RAW_JSON}

---

{RULES}
"""

    def _parse_llm_response(self, response_text: str) -> Dict[str, Any]:
        """Parse LLM response text into structured JSON.

        Args:
            response_text: Raw text from LLM.

        Returns:
            Parsed JSON dict.

        Raises:
            ValueError: If response is empty or not parseable.
        """
        cleaned = strip_llm_thinking_preamble(response_text or "")
        if not cleaned.strip():
            raise ValueError("Empty LLM response after stripping thinking preamble")

        candidate, note = extract_json_object(cleaned)
        if note:
            logger.info(f"LLM JSON extraction: {note}")

        if not (candidate or "").strip():
            raise ValueError("No JSON object found in LLM response")

        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            # Some models return Python-like dicts (single quotes). Try a safe parse.
            # IMPORTANT: This fallback is only for repairing model output text, not
            # for parsing external/untrusted input payloads.
            try:
                parsed = ast.literal_eval(candidate)
            except (SyntaxError, ValueError) as exc:
                preview = (candidate or "")[:800]
                logger.error(
                    "LLM output not valid JSON or Python literal; preview=%r", preview
                )
                raise ValueError(
                    f"LLM response not parseable (len={len(candidate)}): {exc}"
                ) from exc
        parsed = _normalize_llm_result_shape(parsed)
        if not isinstance(parsed, dict):
            raise ValueError(
                f"Expected top-level JSON object, got {type(parsed).__name__}"
            )
        return parsed

    def analyze_alert(
        self, alert_text: str, alert_time: Optional[str] = None
    ) -> Dict[str, Any]:
        """Analyze an alert and return structured TTP analysis.

        Args:
            alert_text: The alert content to analyze.
            alert_time: Optional timestamp for time window references.

        Returns:
            Dict containing:
                - alert_reconciliation: Verdict, confidence, summary, and recommended actions
                - competing_hypotheses: Hypotheses & pivots
                - evidence_vs_inference: Evidence breakdown
                - ioc_extraction: Extracted IOCs
                - ttp_analysis: List of scored, validated TTPs (normalized shape)
                - raw_response: Original LLM response text
                - metadata: Processing metadata
        """
        if not alert_text or not alert_text.strip():
            logger.error("Alert text is empty or whitespace only")
            return {"error": "Empty alert text", "ttp_analysis": []}

        soc_context = self._build_soc_operational_context(alert_text)
        prompt = self._build_prompt(
            alert_text, alert_time, soc_operational_context=soc_context
        )

        def _call_llm(prompt_text: str) -> Tuple[str, float]:
            self._semaphore.acquire()
            try:
                return openai_chat_complete(
                    self._session,
                    self.config,
                    prompt=prompt_text,
                    max_tokens=self.config.LLM_MAX_TOKENS,
                    temperature=0.0,
                    connect_timeout_sec=float(self.config.LLM_TIMEOUT),
                    read_timeout_sec=float(self.config.LLM_TIMEOUT),
                )
            finally:
                self._semaphore.release()

        spl_query_generation_enabled = bool(
            getattr(self.config, "SPL_QUERY_GENERATION_ENABLED", False)
        )

        def _annotate_metadata(
            result_obj: Dict[str, Any],
            *,
            inference_time_seconds: float,
            prompt_length: int,
            attempt_num: int,
            repair_attempted: bool,
            repair_reason: Optional[str] = None,
            spl_unavailable_reason: Optional[str] = None,
        ) -> Dict[str, Any]:
            metadata: Dict[str, Any] = {
                "model": self.config.LLM_MODEL_NAME,
                "inference_time_seconds": inference_time_seconds,
                "prompt_length": prompt_length,
                "attempt": attempt_num,
                "repair_attempted": repair_attempted,
                "soc_context_included": bool(soc_context),
                "soc_context_chars": len(soc_context),
                "spl_query_generation_enabled": spl_query_generation_enabled,
                "spl_query_generation_unavailable": bool(spl_unavailable_reason),
            }
            if repair_reason:
                metadata["repair_reason"] = repair_reason
            if spl_unavailable_reason:
                metadata["spl_query_generation_unavailable_reason"] = (
                    str(spl_unavailable_reason)[:600]
                )
            result_obj["metadata"] = metadata
            return result_obj

        def _suppress_spl_queries_for_alert(
            result_obj: Dict[str, Any], *, reason: str
        ) -> Dict[str, Any]:
            suppressed = _normalize_and_fill_defaults(
                result_obj,
                spl_query_enabled=False,
            )
            suppressed["spl_query_generation_unavailable"] = True
            suppressed["spl_query_generation_unavailable_reason"] = str(reason)[:600]
            return suppressed

        def _validate_base_and_postprocess(
            parsed: Dict[str, Any], *, raw_text: str
        ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
            parsed = _normalize_llm_result_shape(parsed)
            if not isinstance(parsed, dict):
                return (
                    False,
                    f"Expected dict after normalization, got {type(parsed).__name__}",
                    {},
                )

            # Make schema a bit more resilient for local inference (best-effort coercion).
            parsed = _normalize_and_fill_defaults(
                parsed,
                spl_query_enabled=spl_query_generation_enabled,
            )

            # If the model ignored the schema but mentioned technique IDs in the preamble,
            # salvage them into ttp_analysis as a last resort.
            if not parsed.get("ttp_analysis"):
                extracted_ids = _extract_ttp_ids_from_text(raw_text)
                if extracted_ids:
                    parsed["ttp_analysis"] = [
                        {
                            "ttp_id": t,
                            "ttp_name": "",
                            "confidence_score": 0.5,
                            "explanation": "Extracted from model preamble (non-schema). Uncertainty: output format drift.",
                            "evidence_fields": [],
                        }
                        for t in extracted_ids
                    ]

            schema_ok, schema_err = validate_response_schema(parsed)
            if not schema_ok:
                return False, f"Schema validation: {schema_err}", {}

            ch_ok, ch_err = validate_competing_hypotheses_balance(
                parsed, strict=False
            )
            if not ch_ok:
                return False, f"Competing hypotheses validation: {ch_err}", {}

            policy_ok, policy_err = validate_content_policies(parsed)
            if not policy_ok:
                return False, f"Content policy validation: {policy_err}", {}

            try:
                parsed["ttp_analysis_raw"] = parsed.get("ttp_analysis", [])
                extracted = extract_scored_ttps(parsed)
                parsed["ttp_analysis"] = self.ttp_validator.filter_valid_ttps(extracted)
            except Exception as e:
                return False, f"TTP filtering failed: {e}", {}

            return True, None, parsed

        def _check_spl_query_contract(
            result_obj: Dict[str, Any]
        ) -> Tuple[bool, Optional[str]]:
            if not spl_query_generation_enabled:
                return True, None
            return _validate_spl_query_contract(result_obj)

        # Retry logic (transport)
        max_retries = 3
        retry_delay = 5
        last_error: Optional[str] = None

        for attempt in range(max_retries):
            llm_text2: Optional[str] = None
            elapsed2: Optional[float] = None
            try:
                logger.info(f"LLM API call attempt {attempt + 1}/{max_retries}")
                llm_text, elapsed = _call_llm(prompt)

                parsed = self._parse_llm_response(llm_text)
                base_ok, base_err, final_obj = _validate_base_and_postprocess(
                    parsed, raw_text=llm_text
                )
                primary_spl_ok = False
                primary_spl_err: Optional[str] = None
                if base_ok:
                    primary_spl_ok, primary_spl_err = _check_spl_query_contract(final_obj)
                if base_ok and primary_spl_ok:
                    final_obj = _annotate_metadata(
                        final_obj,
                        inference_time_seconds=elapsed,
                        prompt_length=len(prompt),
                        attempt_num=attempt + 1,
                        repair_attempted=False,
                    )
                    final_obj["raw_response"] = llm_text
                    return final_obj

                if base_ok and not primary_spl_ok:
                    last_error = (
                        f"SPL query contract validation: {primary_spl_err or 'unknown'}"
                    )
                else:
                    last_error = base_err or "Unknown validation error"
                logger.warning(
                    f"LLM output invalid, attempting single repair: {last_error}"
                )

                prior = (llm_text or "")[:4000]
                repair_prompt = REPAIR_PROMPT_TEMPLATE_RAW_JSON.format(
                    error=last_error, prior_output=prior
                )
                llm_text2, elapsed2 = _call_llm(repair_prompt)

                parsed2 = self._parse_llm_response(llm_text2)
                base_ok2, base_err2, final_obj2 = _validate_base_and_postprocess(
                    parsed2, raw_text=llm_text2
                )
                repair_spl_ok = False
                repair_spl_err: Optional[str] = None
                if base_ok2:
                    repair_spl_ok, repair_spl_err = _check_spl_query_contract(final_obj2)
                if base_ok2 and repair_spl_ok:
                    final_obj2 = _annotate_metadata(
                        final_obj2,
                        inference_time_seconds=elapsed2 or 0.0,
                        prompt_length=len(repair_prompt),
                        attempt_num=attempt + 1,
                        repair_attempted=True,
                        repair_reason=last_error,
                    )
                    final_obj2["raw_response"] = llm_text2
                    return final_obj2

                if spl_query_generation_enabled and base_ok:
                    spl_reason = primary_spl_err or "unknown SPL query contract error"
                    if base_ok2 and not repair_spl_ok:
                        spl_reason = (
                            f"{spl_reason}; repair SPL validation: {repair_spl_err or 'unknown'}"
                        )
                    elif not base_ok2:
                        spl_reason = (
                            f"{spl_reason}; repair validation: {base_err2 or 'unknown'}"
                        )
                    logger.warning(
                        "SPL query generation unavailable after repair; suppressing SPL output for this alert: %s",
                        spl_reason,
                    )
                    suppressed_obj = _suppress_spl_queries_for_alert(
                        final_obj,
                        reason=spl_reason,
                    )
                    suppressed_obj = _annotate_metadata(
                        suppressed_obj,
                        inference_time_seconds=elapsed,
                        prompt_length=len(prompt),
                        attempt_num=attempt + 1,
                        repair_attempted=True,
                        repair_reason=last_error,
                        spl_unavailable_reason=spl_reason,
                    )
                    suppressed_obj["raw_response"] = llm_text
                    return suppressed_obj

                if spl_query_generation_enabled and base_ok2 and not repair_spl_ok:
                    spl_reason = repair_spl_err or "unknown SPL query contract error"
                    logger.warning(
                        "SPL query generation unavailable after repair; suppressing SPL output for this alert: %s",
                        spl_reason,
                    )
                    suppressed_obj = _suppress_spl_queries_for_alert(
                        final_obj2,
                        reason=spl_reason,
                    )
                    suppressed_obj = _annotate_metadata(
                        suppressed_obj,
                        inference_time_seconds=elapsed2 or 0.0,
                        prompt_length=len(repair_prompt),
                        attempt_num=attempt + 1,
                        repair_attempted=True,
                        repair_reason=last_error,
                        spl_unavailable_reason=spl_reason,
                    )
                    suppressed_obj["raw_response"] = llm_text2
                    return suppressed_obj

                last_error = base_err2 or "Unknown validation error after repair"
                logger.error(f"Repair attempt failed: {last_error}")
                logger.warning(
                    "PoC fallback: returning raw model output (schema/repair failed)"
                )
                return build_poc_fallback_llm_payload(
                    primary_text=llm_text,
                    repair_text=llm_text2,
                    reason=f"Response validation error: {last_error}",
                    model_name=self.config.LLM_MODEL_NAME,
                    attempt=attempt + 1,
                    elapsed_primary=elapsed,
                    elapsed_repair=elapsed2,
                )

            except RequestTimeoutError:
                logger.warning(f"LLM API timeout on attempt {attempt + 1}")
                last_error = "LLM API timeout"
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    return {
                        "error": "LLM API timeout after retries",
                        "ttp_analysis": [],
                    }

            except (
                TransportError,
                RateLimitError,
                ServerError,
                ClientRequestError,
            ) as e:
                logger.error(f"LLM API request error: {e}")
                last_error = f"LLM API error: {e}"
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    return {"error": f"LLM API error: {e}", "ttp_analysis": []}

            except (
                json.JSONDecodeError,
                ValueError,
                SyntaxError,
                ResponseFormatError,
            ) as e:
                logger.error(f"LLM response parsing error: {e}")
                logger.warning(
                    "PoC fallback: returning raw model output (JSON parse failed)"
                )
                return build_poc_fallback_llm_payload(
                    primary_text=llm_text,
                    repair_text=llm_text2,
                    reason=f"Response parsing error: {e}",
                    model_name=self.config.LLM_MODEL_NAME,
                    attempt=attempt + 1,
                    elapsed_primary=elapsed,
                    elapsed_repair=elapsed2,
                )

        return {
            "error": f"Max retries exceeded ({last_error or 'unknown'})",
            "ttp_analysis": [],
        }
