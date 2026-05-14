"""Bounded LLM interpretation of deterministic Splunk query results.

This module keeps query execution facts separate from model-generated
interpretation. The LLM may explain how results affect hypotheses, but it must
not rewrite deterministic query status, counts, references, or existing scores.
"""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Dict, List, Optional, Set, Tuple

ASSESSMENT_VALUES = {"supports", "weakens", "inconclusive", "unknown"}
CONFIDENCE_DELTA_VALUES = {"increase", "decrease", "unchanged", "unknown"}

_MAX_RATIONALE_CHARS = 900
_MAX_LIST_ITEMS = 6
_MAX_LIST_ITEM_CHARS = 240
_MAX_QUERY_CHARS = 900
_MAX_ALERT_CHARS_DEFAULT = 1200


def _truncate(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _clean_string_list(value: Any, *, max_items: int, max_chars: int) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        text = _truncate(item, max_chars)
        if text:
            out.append(text)
        if len(out) >= max_items:
            break
    return out


def _available_query_refs(query_result_section: Dict[str, Any]) -> Set[str]:
    queries = query_result_section.get("queries", [])
    if not isinstance(queries, list):
        return set()
    refs: Set[str] = set()
    for item in queries:
        if not isinstance(item, dict):
            continue
        ref = str(item.get("search_reference", "")).strip()
        if ref:
            refs.add(ref)
    return refs


def _bounded_sample_rows(rows: Any, *, max_rows: int) -> List[Dict[str, str]]:
    if max_rows <= 0 or not isinstance(rows, list):
        return []
    out: List[Dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        clean_row: Dict[str, str] = {}
        for key in sorted(row.keys())[:12]:
            clean_key = _truncate(key, 80)
            clean_value = _truncate(row.get(key), 160)
            if clean_key:
                clean_row[clean_key] = clean_value
        if clean_row:
            out.append(clean_row)
        if len(out) >= max_rows:
            break
    return out


def build_query_result_interpretation_context(
    alert_text: str,
    analysis_result: Dict[str, Any],
    *,
    context_budget_chars: int,
    max_sample_rows: int,
) -> Dict[str, Any]:
    """Build a bounded, deterministic input object for result interpretation."""
    query_result_section = analysis_result.get("query_result_section", {})
    if not isinstance(query_result_section, dict):
        query_result_section = {}

    hypotheses: List[Dict[str, Any]] = []
    raw_hypotheses = analysis_result.get("competing_hypotheses", [])
    if isinstance(raw_hypotheses, list):
        for idx, item in enumerate(raw_hypotheses):
            if not isinstance(item, dict):
                continue
            hypotheses.append(
                {
                    "hypothesis_index": idx,
                    "hypothesis_type": _truncate(item.get("hypothesis_type"), 80),
                    "hypothesis": _truncate(item.get("hypothesis"), 500),
                    "supports_if": _truncate(item.get("supports_if"), 400),
                    "weakens_if": _truncate(item.get("weakens_if"), 400),
                    "query_result_summary": _truncate(
                        item.get("query_result_summary"), 300
                    ),
                    "query_result_reference": _truncate(
                        item.get("query_result_reference"), 160
                    ),
                }
            )

    queries: List[Dict[str, Any]] = []
    raw_queries = query_result_section.get("queries", [])
    if isinstance(raw_queries, list):
        for item in raw_queries:
            if not isinstance(item, dict):
                continue
            entry: Dict[str, Any] = {
                "hypothesis_index": item.get("hypothesis_index"),
                "query_strategy": _truncate(item.get("query_strategy"), 80),
                "query": _truncate(item.get("query"), _MAX_QUERY_CHARS),
                "status": _truncate(item.get("status"), 40),
                "result_count": int(item.get("result_count", 0) or 0),
                "sample_columns": _clean_string_list(
                    item.get("sample_columns", []),
                    max_items=30,
                    max_chars=80,
                ),
                "search_reference": _truncate(item.get("search_reference"), 160),
                "message": _truncate(item.get("message"), 300),
            }
            sample_rows = _bounded_sample_rows(
                item.get("sample_rows", []), max_rows=max_sample_rows
            )
            if sample_rows:
                entry["sample_rows"] = sample_rows
            queries.append(entry)

    context = {
        "alert_text": _truncate(alert_text, _MAX_ALERT_CHARS_DEFAULT),
        "alert_reconciliation": analysis_result.get("alert_reconciliation", {}),
        "hypotheses": hypotheses,
        "query_result_section": {
            "summary": query_result_section.get("summary", {}),
            "queries": queries,
        },
    }

    if context_budget_chars > 0:
        rendered = json.dumps(context, ensure_ascii=True, separators=(",", ":"))
        if len(rendered) > context_budget_chars:
            context["alert_text"] = _truncate(alert_text, 500)
            for item in queries:
                item.pop("sample_rows", None)
                item["query"] = _truncate(item.get("query"), 500)
                item["message"] = _truncate(item.get("message"), 180)
    return context


def build_query_result_interpretation_prompt(
    alert_text: str,
    analysis_result: Dict[str, Any],
    *,
    context_budget_chars: int,
    max_sample_rows: int,
) -> str:
    """Build the third-call prompt for query-result interpretation."""
    context = build_query_result_interpretation_context(
        alert_text,
        analysis_result,
        context_budget_chars=context_budget_chars,
        max_sample_rows=max_sample_rows,
    )
    context_json = json.dumps(context, ensure_ascii=True, indent=2, sort_keys=True)
    return f"""You are interpreting deterministic Splunk query execution results for a SOC notable.

Rules:
- Use only QUERY_RESULT_INTERPRETATION_INPUT. Do not invent events, rows, users, hosts, IOCs, or Splunk facts.
- Treat query results as direct evidence and your explanation as inference.
- Do not modify or restate new values for alert_reconciliation.confidence, TTP scores, hypothesis ordering, query status, result counts, or search references.
- confidence_delta is an interpretation-only label, not a numeric score update.
- For denied, failed, skipped, or ambiguous results, prefer assessment="unknown" or "inconclusive" and confidence_delta="unknown" or "unchanged".
- source_query_refs may include only search_reference values present in QUERY_RESULT_INTERPRETATION_INPUT.
- Return a single JSON object only. No markdown fences.

Schema:
{{
  "query_result_interpretation": [
    {{
      "hypothesis_index": 0,
      "assessment": "supports | weakens | inconclusive | unknown",
      "confidence_delta": "increase | decrease | unchanged | unknown",
      "rationale": "short interpretation grounded in query results",
      "key_observations": ["bounded observations from the query result facts"],
      "remaining_gaps": ["what is still unknown after these queries"],
      "source_query_refs": ["search references used for this interpretation"]
    }}
  ]
}}

QUERY_RESULT_INTERPRETATION_INPUT
{context_json}
"""


def validate_query_result_interpretation_payload(
    payload: Dict[str, Any],
    analysis_result: Dict[str, Any],
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """Validate and normalize query-result interpretation LLM output."""
    if not isinstance(payload, dict):
        return False, "interpretation payload must be an object", {}

    raw_items = payload.get("query_result_interpretation")
    if not isinstance(raw_items, list):
        return False, "query_result_interpretation must be a list", {}

    hypotheses = analysis_result.get("competing_hypotheses", [])
    hypothesis_count = len(hypotheses) if isinstance(hypotheses, list) else 0
    query_section = analysis_result.get("query_result_section", {})
    if not isinstance(query_section, dict):
        return False, "analysis result missing query_result_section", {}
    allowed_refs = _available_query_refs(query_section)
    seen_indexes: Set[int] = set()
    normalized: List[Dict[str, Any]] = []

    for pos, item in enumerate(raw_items):
        if not isinstance(item, dict):
            return False, f"query_result_interpretation[{pos}] must be an object", {}
        idx = item.get("hypothesis_index")
        if not isinstance(idx, int):
            return (
                False,
                f"query_result_interpretation[{pos}].hypothesis_index must be an integer",
                {},
            )
        if idx < 0 or idx >= hypothesis_count:
            return (
                False,
                f"query_result_interpretation[{pos}].hypothesis_index is out of range",
                {},
            )
        if idx in seen_indexes:
            return (
                False,
                f"query_result_interpretation[{pos}].hypothesis_index is duplicated",
                {},
            )
        seen_indexes.add(idx)

        assessment = str(item.get("assessment", "")).strip().lower()
        if assessment not in ASSESSMENT_VALUES:
            return (
                False,
                f"query_result_interpretation[{pos}].assessment is unsupported",
                {},
            )
        confidence_delta = str(item.get("confidence_delta", "")).strip().lower()
        if confidence_delta not in CONFIDENCE_DELTA_VALUES:
            return (
                False,
                f"query_result_interpretation[{pos}].confidence_delta is unsupported",
                {},
            )

        refs = _clean_string_list(
            item.get("source_query_refs", []),
            max_items=_MAX_LIST_ITEMS,
            max_chars=160,
        )
        for ref in refs:
            if ref not in allowed_refs:
                return (
                    False,
                    f"query_result_interpretation[{pos}].source_query_refs contains unknown ref",
                    {},
                )

        normalized.append(
            {
                "hypothesis_index": idx,
                "assessment": assessment,
                "confidence_delta": confidence_delta,
                "rationale": _truncate(item.get("rationale"), _MAX_RATIONALE_CHARS),
                "key_observations": _clean_string_list(
                    item.get("key_observations", []),
                    max_items=_MAX_LIST_ITEMS,
                    max_chars=_MAX_LIST_ITEM_CHARS,
                ),
                "remaining_gaps": _clean_string_list(
                    item.get("remaining_gaps", []),
                    max_items=_MAX_LIST_ITEMS,
                    max_chars=_MAX_LIST_ITEM_CHARS,
                ),
                "source_query_refs": refs,
            }
        )

    return True, None, {"query_result_interpretation": normalized}


def merge_query_result_interpretation(
    analysis_result: Dict[str, Any],
    interpretation_payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Attach validated interpretation without mutating deterministic fields."""
    out = deepcopy(analysis_result)
    out["query_result_interpretation"] = list(
        interpretation_payload.get("query_result_interpretation", [])
    )
    return out
