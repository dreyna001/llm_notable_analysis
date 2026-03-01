"""Local LLM client for vLLM/OpenAI-compatible inference.

Replaces BedrockAnalyzer from the cloud pipeline with local HTTP calls
to vLLM server running gpt-oss-20b.
"""

import json
import logging
import re
import time
import ast
from typing import List, Dict, Any, Optional, Tuple
import requests

from .config import Config
from .ttp_validator import TTPValidator

logger = logging.getLogger(__name__)


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
    """Normalize common wrapper shapes around the expected top-level schema."""
    if not isinstance(result, dict):
        return result

    for k in _COMMON_RESULT_WRAPPER_KEYS:
        v = result.get(k)
        if isinstance(v, dict):
            logger.warning(f"Unwrapping LLM result from container key: {k!r}")
            return v

    if len(result) == 1:
        (only_key, only_val), = result.items()
        if isinstance(only_val, dict):
            logger.warning(f"Unwrapping singleton LLM result container key: {only_key!r}")
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


REPAIR_PROMPT_TEMPLATE_RAW_JSON = """Your previous response could not be parsed or validated.

Error: {error}

Previous output (truncated):
{prior_output}

Return ONLY a single valid JSON object matching the schema and constraints. Do not include markdown fences or any extra text.
"""


def validate_response_schema(result: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    if not isinstance(result, dict):
        return False, f"Expected dict, got {type(result).__name__}"

    for key, expected_type in REQUIRED_RESPONSE_KEYS.items():
        if key not in result:
            return False, f"Missing required key: {key}"
        if not isinstance(result[key], expected_type):
            return False, f"Key '{key}' must be {expected_type.__name__}, got {type(result[key]).__name__}"

    return True, None


def validate_competing_hypotheses_balance(result: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Validate competing_hypotheses shape.

    Historically this enforced EXACTLY 3 benign + 3 adversary hypotheses (6 total).
    In practice, some local models intermittently violate this constraint even when
    asked. For resilience, we only enforce "list of objects" here and treat count/
    balance as best-effort (the markdown generator can handle an empty list).
    """
    ch = result.get("competing_hypotheses")
    if ch is None:
        return True, None
    if not isinstance(ch, list):
        return False, "competing_hypotheses must be a list"
    for i, item in enumerate(ch):
        if not isinstance(item, dict):
            return False, f"competing_hypotheses[{i}] must be an object"
    return True, None


def _coerce_ioc_extraction(value: Any) -> Dict[str, Any]:
    """Coerce ioc_extraction into the dict shape expected by markdown rendering."""
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
    base: Dict[str, Any] = {"evidence": [], "inferences": []}
    if isinstance(value, dict):
        ev = value.get("evidence", [])
        inf = value.get("inferences", [])
        base["evidence"] = [str(x) for x in (ev if isinstance(ev, list) else [ev]) if str(x)]
        base["inferences"] = [str(x) for x in (inf if isinstance(inf, list) else [inf]) if str(x)]
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
                ttp_id = _coerce_ttp_id(item.get("ttp_name")) or _coerce_ttp_id(item.get("explanation")) or _coerce_ttp_id(item.get("rationale"))

            out.append(
                {
                    **item,
                    "ttp_id": ttp_id,
                    "ttp_name": item.get("ttp_name", item.get("technique_name", item.get("name", ""))),
                    "confidence_score": item.get("confidence_score", item.get("score", item.get("confidence", 0.5))),
                    "explanation": item.get("explanation", item.get("rationale", "")),
                    "evidence_fields": item.get("evidence_fields", item.get("evidence", [])),
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


def _normalize_and_fill_defaults(parsed: Dict[str, Any]) -> Dict[str, Any]:
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
        "confidence": str(ar.get("confidence", "")) if ar.get("confidence") is not None else "",
        "one_sentence_summary": str(ar.get("one_sentence_summary", "")) if ar.get("one_sentence_summary") is not None else "",
        "decision_drivers": [str(x) for x in (ar.get("decision_drivers", []) if isinstance(ar.get("decision_drivers", []), list) else [ar.get("decision_drivers", "")]) if str(x)],
        "recommended_actions": [str(x) for x in (ar.get("recommended_actions", []) if isinstance(ar.get("recommended_actions", []), list) else [ar.get("recommended_actions", "")]) if str(x)],
    }
    ch = out.get("competing_hypotheses", [])
    if isinstance(ch, dict):
        ch = [ch]
    if not isinstance(ch, list):
        ch = []
    out["competing_hypotheses"] = ch
    out["evidence_vs_inference"] = _coerce_evidence_vs_inference(out.get("evidence_vs_inference", {}))
    out["ioc_extraction"] = _coerce_ioc_extraction(out.get("ioc_extraction", {}))
    out["ttp_analysis"] = _coerce_ttp_analysis(out.get("ttp_analysis", []))
    return out


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
    """Validate policy constraints not fully expressible via JSON schema."""
    for p, s in _iter_strings(result):
        s_lower = s.lower()
        if "example.com" in s_lower:
            return False, f"Disallowed placeholder domain in {p}"
        if "placeholder" in s_lower:
            return False, f"Disallowed PLACEHOLDER token in {p}"
        if ("http://" in s_lower or "https://" in s_lower):
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
                "score": _safe_float(item.get("confidence_score", item.get("score", item.get("confidence", 0.0)))),
                "explanation": item.get("explanation", ""),
                "evidence_fields": item.get("evidence_fields", []),
            }
        )

    return scored


def _extract_brace_balanced_object(text: str) -> Optional[str]:
    """Extract the first complete brace-balanced JSON object from text."""
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
    """Extract a JSON object from text that may contain fences, preamble, or trailing content."""
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
    
    def _build_prompt(self, alert_text: str, alert_time: Optional[str] = None) -> str:
        """Build the analysis prompt.
        
        Ported from s3_notable_pipeline/ttp_analyzer.py format_alert_input().
        
        Args:
            alert_text: The alert content to analyze.
            alert_time: Optional timestamp for time window references.
            
        Returns:
            Formatted prompt string.
        """
        alert_time_str = f"\n**ALERT_TIME:** {alert_time}\n" if alert_time else ""

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
            json.JSONDecodeError: If response is not valid JSON.
        """
        candidate, note = extract_json_object(response_text)
        if note:
            logger.info(f"LLM JSON extraction: {note}")

        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            # Some models return Python-like dicts (single quotes). Try a safe parse.
            parsed = ast.literal_eval(candidate)
        parsed = _normalize_llm_result_shape(parsed)
        if not isinstance(parsed, dict):
            raise ValueError(f"Expected top-level JSON object, got {type(parsed).__name__}")
        return parsed
    
    def analyze_alert(
        self,
        alert_text: str,
        alert_time: Optional[str] = None
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
        
        prompt = self._build_prompt(alert_text, alert_time)

        headers = {"Content-Type": "application/json"}
        if self.config.LLM_API_TOKEN:
            headers["Authorization"] = f"Bearer {self.config.LLM_API_TOKEN}"

        def _extract_choice_text(response_json: Dict[str, Any]) -> str:
            if "choices" in response_json and len(response_json["choices"]) > 0:
                choice0 = response_json["choices"][0]
                if "text" in choice0:
                    return choice0["text"]
                if "message" in choice0 and isinstance(choice0["message"], dict):
                    return choice0["message"].get("content", "")
                raise ValueError("Unexpected response format from LLM choices[0]")
            raise ValueError("No choices in LLM response")

        def _call_llm(prompt_text: str) -> Tuple[str, float]:
            request_body = {
                "model": self.config.LLM_MODEL_NAME,
                "prompt": prompt_text,
                "max_tokens": self.config.LLM_MAX_TOKENS,
                "temperature": 0.0,
            }
            start_time = time.time()
            response = requests.post(
                self.config.LLM_API_URL,
                json=request_body,
                headers=headers,
                timeout=self.config.LLM_TIMEOUT,
            )
            response.raise_for_status()
            elapsed = time.time() - start_time
            response_json = response.json()
            return _extract_choice_text(response_json), elapsed

        def _validate_and_postprocess(parsed: Dict[str, Any], *, raw_text: str) -> Tuple[bool, Optional[str], Dict[str, Any]]:
            parsed = _normalize_llm_result_shape(parsed)
            if not isinstance(parsed, dict):
                return False, f"Expected dict after normalization, got {type(parsed).__name__}", {}

            # Make schema a bit more resilient for local inference (best-effort coercion).
            parsed = _normalize_and_fill_defaults(parsed)

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

            ch_ok, ch_err = validate_competing_hypotheses_balance(parsed)
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

        # Retry logic (transport)
        max_retries = 3
        retry_delay = 5
        last_error: Optional[str] = None

        for attempt in range(max_retries):
            try:
                logger.info(f"LLM API call attempt {attempt + 1}/{max_retries}")
                llm_text, elapsed = _call_llm(prompt)

                parsed = self._parse_llm_response(llm_text)
                ok, err, final_obj = _validate_and_postprocess(parsed, raw_text=llm_text)
                if ok:
                    final_obj["metadata"] = {
                        "model": self.config.LLM_MODEL_NAME,
                        "inference_time_seconds": elapsed,
                        "prompt_length": len(prompt),
                        "attempt": attempt + 1,
                        "repair_attempted": False,
                    }
                    final_obj["raw_response"] = llm_text
                    return final_obj

                last_error = err or "Unknown validation error"
                logger.warning(f"LLM output invalid, attempting single repair: {last_error}")

                prior = (llm_text or "")[:4000]
                repair_prompt = REPAIR_PROMPT_TEMPLATE_RAW_JSON.format(error=last_error, prior_output=prior)
                llm_text2, elapsed2 = _call_llm(repair_prompt)

                parsed2 = self._parse_llm_response(llm_text2)
                ok2, err2, final_obj2 = _validate_and_postprocess(parsed2, raw_text=llm_text2)
                if ok2:
                    final_obj2["metadata"] = {
                        "model": self.config.LLM_MODEL_NAME,
                        "inference_time_seconds": elapsed2,
                        "prompt_length": len(repair_prompt),
                        "attempt": attempt + 1,
                        "repair_attempted": True,
                        "repair_reason": last_error,
                    }
                    final_obj2["raw_response"] = llm_text2
                    return final_obj2

                last_error = err2 or "Unknown validation error after repair"
                logger.error(f"Repair attempt failed: {last_error}")
                return {"error": f"Response validation error: {last_error}", "ttp_analysis": []}

            except requests.exceptions.Timeout:
                logger.warning(f"LLM API timeout on attempt {attempt + 1}")
                last_error = "LLM API timeout"
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    return {"error": "LLM API timeout after retries", "ttp_analysis": []}

            except requests.exceptions.RequestException as e:
                logger.error(f"LLM API request error: {e}")
                last_error = f"LLM API error: {e}"
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    return {"error": f"LLM API error: {e}", "ttp_analysis": []}

            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"LLM response parsing error: {e}")
                return {"error": f"Response parsing error: {e}", "ttp_analysis": []}

        return {"error": f"Max retries exceeded ({last_error or 'unknown'})", "ttp_analysis": []}

