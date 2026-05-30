"""SPL query-generation contract and normalization helpers."""

from __future__ import annotations

import json
import re
from typing import Any

SPL_QUERY_STRATEGIES = {"resolve_unknown", "check_contradiction"}
SPL_QUERY_FIELDS = (
    "query_strategy",
    "primary_spl_query",
    "why_this_query",
    "supports_if",
    "weakens_if",
)
SPL_QUERY_GROUNDING_FIELDS = ("primary_spl_query_grounding_refs",)

_INDEX_RE = re.compile(r"\bindex\s*=\s*([A-Za-z0-9_\-*]+)", re.IGNORECASE)
_SOURCETYPE_RE = re.compile(r"\bsourcetype\s*=\s*([A-Za-z0-9_\-.:*]+)", re.IGNORECASE)
_MACRO_RE = re.compile(r"`([^`]+)`")
_DATAMODEL_RE = re.compile(r"\bdatamodel\s*=\s*([A-Za-z0-9_\-.:]+)", re.IGNORECASE)
_GROUNDING_LINE_RE = re.compile(
    r"^\[\d+\]\s+\[(?P<source>.*?)\s+::\s+(?P<section>.*?)\]\s+(?P<excerpt>.*)$"
)

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
- Do not invent environment-specific tokens unless they appear in SECURITY ALERT INPUT, SPL_QUERY_GROUNDING_CONTEXT, or the configured allowlist.
""".strip()

SPL_QUERY_CONTEXT_RULES = """
SPL QUERY CONTEXT RULES:
- Treat SOC_OPERATIONAL_CONTEXT as advisory context only.
- Treat SPL_QUERY_GROUNDING_CONTEXT as advisory Splunk-environment context only.
- Never treat either context block as direct alert evidence.
- Do not use indexes, sourcetypes, macros, or CIM data models unless they appear in SECURITY ALERT INPUT, SPL_QUERY_GROUNDING_CONTEXT, or the configured allowlist.
- Keep each query bounded and decision-oriented.
""".strip()

SPL_QUERY_OUTPUT_SCHEMA = """
Return ONLY a single JSON object with this shape:
{
  "competing_hypotheses": [
    {
      "query_strategy": "resolve_unknown|check_contradiction",
      "primary_spl_query": "string",
      "why_this_query": "string",
      "supports_if": "string",
      "weakens_if": "string"
    }
  ]
}

Requirements:
- Output exactly 6 items in competing_hypotheses.
- Keep the same order as INPUT_COMPETING_HYPOTHESES.
- Include only the query fields above per hypothesis item.
- Do not include markdown fences or extra prose.
""".strip()


def build_spl_query_generation_prompt(
    *,
    alert_text: str,
    hypotheses: list[dict[str, Any]],
    soc_operational_context: str = "",
    spl_query_grounding_context: str = "",
    alert_time: str | None = None,
) -> str:
    """Build a bounded second-call prompt for SPL query generation only."""

    alert_time_str = f"\n**ALERT_TIME:** {alert_time}\n" if alert_time else ""
    soc_context_block = (soc_operational_context or "").strip() or "SOC_OPERATIONAL_CONTEXT\n(none)\n"
    spl_grounding_block = (
        (spl_query_grounding_context or "").strip()
        or "SPL_QUERY_GROUNDING_CONTEXT\n(none)\n"
    )
    hypotheses_block = json.dumps(hypotheses, indent=2, ensure_ascii=True)
    return f"""You are a cybersecurity investigation assistant generating Splunk queries for predefined hypotheses.
{alert_time_str}
---

SECURITY ALERT INPUT:
{alert_text}

---

INPUT_COMPETING_HYPOTHESES (ordered):
{hypotheses_block}

---

{soc_context_block}

---

{spl_grounding_block}

{SPL_QUERY_CONTEXT_RULES}

---

{SPL_QUERY_GENERATION_RULES}

---

{SPL_QUERY_OUTPUT_SCHEMA}
"""


def merge_spl_query_fields_by_position(
    *,
    base_hypotheses: list[dict[str, Any]],
    generated_payload: dict[str, Any],
    spl_query_grounding_context: str = "",
) -> list[dict[str, Any]]:
    """Merge generated SPL query fields onto baseline hypotheses by list order."""

    base = normalize_competing_hypotheses(base_hypotheses, spl_query_enabled=False)
    generated = generated_payload.get("competing_hypotheses", [])
    if not isinstance(generated, list):
        generated = []

    merged: list[dict[str, Any]] = []
    for idx, item in enumerate(base):
        merged_item = dict(item)
        generated_item = generated[idx] if idx < len(generated) else {}
        if isinstance(generated_item, dict):
            for field in SPL_QUERY_FIELDS:
                if field in generated_item:
                    merged_item[field] = generated_item.get(field)
            refs = build_spl_query_grounding_refs(
                str(merged_item.get("primary_spl_query", "")),
                spl_query_grounding_context,
            )
            if refs:
                merged_item["primary_spl_query_grounding_refs"] = refs
        merged.append(merged_item)

    return normalize_competing_hypotheses(merged, spl_query_enabled=True)


def _query_environment_tokens(query: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    for match in _INDEX_RE.finditer(query or ""):
        tokens.append(("index", match.group(1).strip()))
    for match in _SOURCETYPE_RE.finditer(query or ""):
        tokens.append(("sourcetype", match.group(1).strip()))
    for match in _MACRO_RE.finditer(query or ""):
        tokens.append(("macro", match.group(1).strip()))
    for match in _DATAMODEL_RE.finditer(query or ""):
        tokens.append(("datamodel", match.group(1).strip()))
    return [(kind, value) for kind, value in tokens if value]


def _token_present(token: str, text: str) -> bool:
    clean = (token or "").strip().casefold()
    return bool(clean and clean in (text or "").casefold())


def build_spl_query_grounding_refs(
    query: str,
    spl_query_grounding_context: str,
) -> list[dict[str, str]]:
    """Return source refs from SPL grounding snippets used by the query."""

    tokens = [value for _kind, value in _query_environment_tokens(query)]
    if not tokens or not spl_query_grounding_context:
        return []

    refs: list[dict[str, str]] = []
    seen = set()
    for raw_line in spl_query_grounding_context.splitlines():
        match = _GROUNDING_LINE_RE.match(raw_line.strip())
        if not match or not any(_token_present(token, raw_line) for token in tokens):
            continue
        ref = {
            "source_file": (match.group("source") or "unknown_source").strip(),
            "section_path": (match.group("section") or "root").strip(),
        }
        key = (ref["source_file"], ref["section_path"])
        if key not in seen:
            refs.append(ref)
            seen.add(key)
    return refs


def _environment_token_is_allowed(
    *,
    token_kind: str,
    token: str,
    alert_text: str,
    spl_query_grounding_context: str,
    allowed_indexes: str = "",
) -> bool:
    if _token_present(token, alert_text) or _token_present(token, spl_query_grounding_context):
        return True
    if token_kind == "index":
        allowed = {part.strip().casefold() for part in allowed_indexes.split(",") if part.strip()}
        return token.casefold() in allowed
    return False


def _validate_strict_hypothesis_balance(hypotheses: list[Any]) -> tuple[bool, str | None]:
    if len(hypotheses) != 6:
        return False, f"competing_hypotheses must contain exactly 6 items, got {len(hypotheses)}"

    for i, item in enumerate(hypotheses):
        if not isinstance(item, dict):
            return False, f"competing_hypotheses[{i}] must be an object"
    return True, None


def validate_spl_query_contract(
    result: dict[str, Any],
    *,
    alert_text: str = "",
    spl_query_grounding_context: str = "",
    require_spl_grounding: bool = False,
    allowed_indexes: str = "",
) -> tuple[bool, str | None]:
    """Validate strict SPL query contract for per-hypothesis query generation."""

    ch = result.get("competing_hypotheses")
    if not isinstance(ch, list):
        return False, "competing_hypotheses must be a list"

    ch_ok, ch_err = _validate_strict_hypothesis_balance(ch)
    if not ch_ok:
        return False, ch_err

    for i, item in enumerate(ch):
        strategy = str(item.get("query_strategy", "")).strip().lower()
        if strategy not in SPL_QUERY_STRATEGIES:
            return False, f"competing_hypotheses[{i}].query_strategy must be one of {SPL_QUERY_STRATEGIES}"

        primary_query = str(item.get("primary_spl_query", "")).strip()
        if not primary_query:
            return False, f"competing_hypotheses[{i}].primary_spl_query must be non-empty"
        if re.search(r"<[^>]+>", primary_query):
            return False, f"competing_hypotheses[{i}].primary_spl_query contains placeholder token"
        if "..." in primary_query:
            return False, f"competing_hypotheses[{i}].primary_spl_query contains pseudo-query ellipsis"
        for token_kind, token_value in _query_environment_tokens(primary_query):
            if _environment_token_is_allowed(
                token_kind=token_kind,
                token=token_value,
                alert_text=alert_text,
                spl_query_grounding_context=spl_query_grounding_context,
                allowed_indexes=allowed_indexes,
            ):
                continue
            if require_spl_grounding:
                return False, (
                    f"competing_hypotheses[{i}].primary_spl_query uses "
                    f"ungrounded {token_kind}: {token_value}"
                )
            return False, (
                f"competing_hypotheses[{i}].primary_spl_query must not assume "
                f"{token_kind} names"
            )

        for field in ("why_this_query", "supports_if", "weakens_if"):
            value = str(item.get(field, "")).strip()
            if not value:
                return False, f"competing_hypotheses[{i}].{field} must be non-empty"

    return True, None


def normalize_competing_hypotheses(
    value: Any,
    *,
    spl_query_enabled: bool,
) -> list[dict[str, Any]]:
    """Normalize competing hypotheses and optionally strip SPL query fields."""

    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, Any]] = []
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
            for field in (*SPL_QUERY_FIELDS, *SPL_QUERY_GROUNDING_FIELDS):
                hyp.pop(field, None)
        normalized.append(hyp)
    return normalized
