"""Deterministic query-result enrichment for analysis payloads."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def _normalize_query_status(raw_status: str) -> str:
    status = str(raw_status or "").strip().lower()
    if status == "success":
        return "executed"
    if status in {"denied", "skipped"}:
        return status
    return "failed"


def _extract_query_reference(item: dict[str, Any]) -> str:
    for key in ("raw_result_ref", "search_id", "job_id", "sid"):
        value = item.get(key)
        if value:
            return str(value)
    return ""


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _clean_sample_rows(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, str]] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        clean_row = {
            str(key).strip(): str(row.get(key, "")).strip()
            for key in row
            if str(key).strip()
        }
        if clean_row:
            out.append(clean_row)
    return out


def _build_query_entries(query_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in query_results:
        if not isinstance(item, dict):
            continue
        normalized_status = _normalize_query_status(str(item.get("status", "")))
        entry = {
            "hypothesis_index": item.get("hypothesis_index"),
            "query_strategy": str(item.get("query_strategy", "")).strip().lower(),
            "query": str(item.get("query", "")).strip(),
            "status": normalized_status,
            "result_count": _safe_int(item.get("result_count")),
            "sample_columns": _clean_string_list(item.get("sample_columns", [])),
            "search_reference": _extract_query_reference(item),
            "message": str(item.get("message", "")).strip(),
        }
        sample_rows = _clean_sample_rows(item.get("sample_rows", []))
        if sample_rows:
            entry["sample_rows"] = sample_rows
        entries.append(entry)
    return entries


def _summarize_query_entries(entries: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"attempted": len(entries), "executed": 0, "denied": 0, "failed": 0, "skipped": 0}
    for entry in entries:
        status = str(entry.get("status", "")).strip().lower()
        if status in summary:
            summary[status] += 1
        else:
            summary["failed"] += 1
    return summary


def _annotate_hypotheses_with_query_results(
    hypotheses: list[dict[str, Any]],
    entries: list[dict[str, Any]],
) -> None:
    for entry in entries:
        idx = entry.get("hypothesis_index")
        if not isinstance(idx, int) or idx < 0 or idx >= len(hypotheses):
            continue
        hypothesis = hypotheses[idx]
        if not isinstance(hypothesis, dict):
            continue

        status = str(entry.get("status", "")).strip().lower()
        hypothesis["query_result_status"] = status
        if status == "executed":
            count = int(entry.get("result_count", 0) or 0)
            hypothesis["query_result_summary"] = f"Query executed with {count} result(s)."
        elif status == "denied":
            hypothesis["query_result_summary"] = "Query was denied by policy."
        elif status == "skipped":
            hypothesis["query_result_summary"] = "Query was skipped."
        else:
            message = str(entry.get("message", "")).strip()
            hypothesis["query_result_summary"] = (
                "Query execution failed."
                if not message
                else f"Query execution failed: {message}"
            )

        ref = str(entry.get("search_reference", "")).strip()
        if ref:
            hypothesis["query_result_reference"] = ref


def enrich_analysis_with_query_results(
    llm_response: dict[str, Any],
    query_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Enrich analysis output with deterministic query-result summaries."""

    if not isinstance(llm_response, dict):
        return {}
    out: dict[str, Any] = deepcopy(llm_response)

    if not isinstance(query_results, list) or not query_results:
        return out

    entries = _build_query_entries(query_results)
    if not entries:
        return out

    out["query_result_section"] = {
        "summary": _summarize_query_entries(entries),
        "queries": entries,
    }

    hypotheses = out.get("competing_hypotheses")
    if isinstance(hypotheses, list):
        _annotate_hypotheses_with_query_results(hypotheses, entries)

    return out
