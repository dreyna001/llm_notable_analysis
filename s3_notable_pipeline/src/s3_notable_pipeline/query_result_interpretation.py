"""Bounded LLM interpretation of deterministic query results."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

ASSESSMENT_VALUES = {"supports", "weakens", "inconclusive", "unknown"}
CONFIDENCE_DELTA_VALUES = {"increase", "decrease", "unchanged", "unknown"}

_MAX_RATIONALE_CHARS = 900
_MAX_LIST_ITEMS = 6
_MAX_LIST_ITEM_CHARS = 240
_MAX_QUERY_CHARS = 900
_MAX_ALERT_CHARS_DEFAULT = 1200
_MIN_CONTEXT_BUDGET_CHARS = 800


def _truncate(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _clean_string_list(value: Any, *, max_items: int, max_chars: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = _truncate(item, max_chars)
        if text:
            out.append(text)
        if len(out) >= max_items:
            break
    return out


def _available_query_refs(query_result_section: dict[str, Any]) -> set[str]:
    queries = query_result_section.get("queries", [])
    if not isinstance(queries, list):
        return set()
    refs: set[str] = set()
    for item in queries:
        if not isinstance(item, dict):
            continue
        ref = str(item.get("search_reference", "")).strip()
        if ref:
            refs.add(ref)
    return refs


def _bounded_sample_rows(rows: Any, *, max_rows: int) -> list[dict[str, str]]:
    if max_rows <= 0 or not isinstance(rows, list):
        return []
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        clean_row: dict[str, str] = {}
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


def _bounded_alert_reconciliation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "verdict": _truncate(value.get("verdict"), 80),
        "confidence": _truncate(value.get("confidence"), 40),
        "one_sentence_summary": _truncate(value.get("one_sentence_summary"), 300),
        "decision_drivers": _clean_string_list(
            value.get("decision_drivers", []),
            max_items=_MAX_LIST_ITEMS,
            max_chars=_MAX_LIST_ITEM_CHARS,
        ),
        "recommended_actions": _clean_string_list(
            value.get("recommended_actions", []),
            max_items=_MAX_LIST_ITEMS,
            max_chars=_MAX_LIST_ITEM_CHARS,
        ),
    }


def _bounded_query_summary(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        value = {}
    return {
        "attempted": _safe_int(value.get("attempted")),
        "executed": _safe_int(value.get("executed")),
        "denied": _safe_int(value.get("denied")),
        "failed": _safe_int(value.get("failed")),
        "skipped": _safe_int(value.get("skipped")),
    }


def _serialized_context_len(context: dict[str, Any]) -> int:
    return len(json.dumps(context, ensure_ascii=True, separators=(",", ":")))


def _prune_context_to_budget(
    context: dict[str, Any],
    *,
    context_budget_chars: int,
) -> dict[str, Any]:
    if context_budget_chars < _MIN_CONTEXT_BUDGET_CHARS:
        context_budget_chars = _MIN_CONTEXT_BUDGET_CHARS
    if _serialized_context_len(context) <= context_budget_chars:
        return context

    context["alert_text"] = _truncate(context.get("alert_text"), 500)
    queries = context.get("query_result_section", {}).get("queries", [])
    if isinstance(queries, list):
        for item in queries:
            if not isinstance(item, dict):
                continue
            item.pop("sample_rows", None)
            item["query"] = _truncate(item.get("query"), 500)
            item["message"] = _truncate(item.get("message"), 180)
    if _serialized_context_len(context) <= context_budget_chars:
        return context

    hypotheses = context.get("hypotheses", [])
    if isinstance(hypotheses, list):
        for item in hypotheses:
            if not isinstance(item, dict):
                continue
            item["hypothesis"] = _truncate(item.get("hypothesis"), 240)
            item["supports_if"] = _truncate(item.get("supports_if"), 180)
            item["weakens_if"] = _truncate(item.get("weakens_if"), 180)
            item["query_result_summary"] = _truncate(item.get("query_result_summary"), 160)
    if _serialized_context_len(context) <= context_budget_chars:
        return context

    context["alert_reconciliation"] = {
        "verdict": _truncate(context.get("alert_reconciliation", {}).get("verdict", "unknown"), 80),
        "confidence": _truncate(
            context.get("alert_reconciliation", {}).get("confidence", "unknown"),
            40,
        ),
    }
    context["alert_text"] = _truncate(context.get("alert_text"), 240)
    if isinstance(queries, list):
        for item in queries:
            if not isinstance(item, dict):
                continue
            item["query"] = _truncate(item.get("query"), 220)
            item["message"] = _truncate(item.get("message"), 80)
            item["sample_columns"] = _clean_string_list(
                item.get("sample_columns", []),
                max_items=8,
                max_chars=40,
            )
    return context


def build_query_result_interpretation_context(
    alert_text: str,
    analysis_result: dict[str, Any],
    *,
    context_budget_chars: int,
    max_sample_rows: int,
) -> dict[str, Any]:
    """Build a bounded, deterministic input object for result interpretation."""

    query_result_section = analysis_result.get("query_result_section", {})
    if not isinstance(query_result_section, dict):
        query_result_section = {}

    hypotheses: list[dict[str, Any]] = []
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
                    "query_result_summary": _truncate(item.get("query_result_summary"), 300),
                    "query_result_reference": _truncate(item.get("query_result_reference"), 160),
                }
            )

    queries: list[dict[str, Any]] = []
    raw_queries = query_result_section.get("queries", [])
    if isinstance(raw_queries, list):
        for item in raw_queries:
            if not isinstance(item, dict):
                continue
            entry: dict[str, Any] = {
                "hypothesis_index": item.get("hypothesis_index"),
                "query_strategy": _truncate(item.get("query_strategy"), 80),
                "query": _truncate(item.get("query"), _MAX_QUERY_CHARS),
                "status": _truncate(item.get("status"), 40),
                "result_count": _safe_int(item.get("result_count")),
                "sample_columns": _clean_string_list(
                    item.get("sample_columns", []),
                    max_items=30,
                    max_chars=80,
                ),
                "search_reference": _truncate(item.get("search_reference"), 160),
                "message": _truncate(item.get("message"), 300),
            }
            sample_rows = _bounded_sample_rows(item.get("sample_rows", []), max_rows=max_sample_rows)
            if sample_rows:
                entry["sample_rows"] = sample_rows
            queries.append(entry)

    context = {
        "alert_text": _truncate(alert_text, _MAX_ALERT_CHARS_DEFAULT),
        "alert_reconciliation": _bounded_alert_reconciliation(
            analysis_result.get("alert_reconciliation", {})
        ),
        "hypotheses": hypotheses,
        "query_result_section": {
            "summary": _bounded_query_summary(query_result_section.get("summary", {})),
            "queries": queries,
        },
    }

    if context_budget_chars > 0:
        context = _prune_context_to_budget(context, context_budget_chars=context_budget_chars)
    return context


def build_query_result_interpretation_prompt(
    alert_text: str,
    analysis_result: dict[str, Any],
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
    return f"""You are interpreting deterministic query execution results for a SOC notable.

Rules:
- Use only QUERY_RESULT_INTERPRETATION_INPUT. Do not invent events, rows, users, hosts, IOCs, or source-system facts.
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
      "key_observations": ["bounded observations from query result facts"],
      "remaining_gaps": ["what is still unknown after these queries"],
      "source_query_refs": ["search references used for this interpretation"]
    }}
  ]
}}

QUERY_RESULT_INTERPRETATION_INPUT
{context_json}
"""


def build_query_result_interpretation_repair_prompt(
    *,
    original_prompt: str,
    validation_error: str,
    prior_output: str,
) -> str:
    """Build a repair prompt that preserves the original grounded context."""

    return f"""{original_prompt}

---

Your previous query-result interpretation response failed validation.

Validation error:
{_truncate(validation_error, 800)}

Previous output (truncated):
{_truncate(prior_output, 2000)}

Return ONLY one corrected JSON object matching the schema above. Use only
QUERY_RESULT_INTERPRETATION_INPUT and the allowed source_query_refs shown there.
Do not include markdown fences or any extra text.
"""


def validate_query_result_interpretation_payload(
    payload: dict[str, Any],
    analysis_result: dict[str, Any],
) -> tuple[bool, str | None, dict[str, Any]]:
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
    if not raw_items and allowed_refs:
        return False, "query_result_interpretation must not be empty", {}

    seen_indexes: set[int] = set()
    normalized: list[dict[str, Any]] = []
    for pos, item in enumerate(raw_items):
        if not isinstance(item, dict):
            return False, f"query_result_interpretation[{pos}] must be an object", {}
        idx = item.get("hypothesis_index")
        if not isinstance(idx, int):
            return False, f"query_result_interpretation[{pos}].hypothesis_index must be an integer", {}
        if idx < 0 or idx >= hypothesis_count:
            return False, f"query_result_interpretation[{pos}].hypothesis_index is out of range", {}
        if idx in seen_indexes:
            return False, f"query_result_interpretation[{pos}].hypothesis_index is duplicated", {}
        seen_indexes.add(idx)

        assessment = str(item.get("assessment", "")).strip().lower()
        if assessment not in ASSESSMENT_VALUES:
            return False, f"query_result_interpretation[{pos}].assessment is unsupported", {}
        confidence_delta = str(item.get("confidence_delta", "")).strip().lower()
        if confidence_delta not in CONFIDENCE_DELTA_VALUES:
            return False, f"query_result_interpretation[{pos}].confidence_delta is unsupported", {}

        refs = _clean_string_list(
            item.get("source_query_refs", []),
            max_items=_MAX_LIST_ITEMS,
            max_chars=160,
        )
        for ref in refs:
            if ref not in allowed_refs:
                return False, (
                    f"query_result_interpretation[{pos}].source_query_refs contains unknown ref"
                ), {}
        rationale = _truncate(item.get("rationale"), _MAX_RATIONALE_CHARS)
        if assessment in {"supports", "weakens"} and (not refs or not rationale):
            return False, (
                f"query_result_interpretation[{pos}] requires rationale and source refs for {assessment}"
            ), {}

        normalized.append(
            {
                "hypothesis_index": idx,
                "assessment": assessment,
                "confidence_delta": confidence_delta,
                "rationale": rationale,
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
    analysis_result: dict[str, Any],
    interpretation_payload: dict[str, Any],
) -> dict[str, Any]:
    """Attach validated interpretation without mutating deterministic fields."""

    out = deepcopy(analysis_result)
    out["query_result_interpretation"] = list(
        interpretation_payload.get("query_result_interpretation", [])
    )
    return out
