"""SPL query-generation contract and normalization helpers.

This module keeps SPL-specific prompt doctrine and response-contract logic
separate from broader LLM transport, parsing, and report processing.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

SPL_QUERY_STRATEGIES = {"resolve_unknown", "check_contradiction"}
SPL_QUERY_FIELDS = (
    "query_strategy",
    "primary_spl_query",
    "why_this_query",
    "supports_if",
    "weakens_if",
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
- Do not invent environment-specific tokens (indexes/sourcetypes/macros/CIM data model names) unless explicitly present in SECURITY ALERT INPUT.
""".strip()


def _validate_strict_hypothesis_balance(
    hypotheses: List[Any],
) -> Tuple[bool, Optional[str]]:
    """Validate EXACTLY 3 benign and 3 adversary hypotheses."""
    if len(hypotheses) != 6:
        return (
            False,
            f"competing_hypotheses must contain exactly 6 items, got {len(hypotheses)}",
        )

    benign = 0
    adversary = 0
    for i, item in enumerate(hypotheses):
        if not isinstance(item, dict):
            return False, f"competing_hypotheses[{i}] must be an object"
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


def validate_spl_query_contract(result: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
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
            return (
                False,
                f"competing_hypotheses[{i}].query_strategy must be one of {SPL_QUERY_STRATEGIES}",
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


def normalize_competing_hypotheses(
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
            for field in SPL_QUERY_FIELDS:
                hyp.pop(field, None)
        normalized.append(hyp)
    return normalized
