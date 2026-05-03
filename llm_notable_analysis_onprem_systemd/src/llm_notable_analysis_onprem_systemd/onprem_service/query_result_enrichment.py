"""Deterministic query-result enrichment for analysis payloads.

This module adds normalized query execution summaries to the analysis response
without modifying evidence-vs-inference facts.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List


def _normalize_query_status(raw_status: str) -> str:
    status = str(raw_status or "").strip().lower()
    if status == "success":
        return "executed"
    if status in {"denied", "skipped"}:
        return status
    return "failed"


def _extract_query_reference(item: Dict[str, Any]) -> str:
    for key in ("raw_result_ref", "search_id", "job_id", "sid"):
        value = item.get(key)
        if value:
            return str(value)
    return ""


def _build_query_entries(query_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for item in query_results:
        if not isinstance(item, dict):
            continue
        normalized_status = _normalize_query_status(str(item.get("status", "")))
        entry = {
            "hypothesis_index": item.get("hypothesis_index"),
            "query_strategy": str(item.get("query_strategy", "")).strip().lower(),
            "query": str(item.get("query", "")).strip(),
            "status": normalized_status,
            "result_count": int(item.get("result_count", 0) or 0),
            "sample_columns": list(item.get("sample_columns", []) or []),
            "search_reference": _extract_query_reference(item),
            "message": str(item.get("message", "")).strip(),
        }
        entries.append(entry)
    return entries


def _summarize_query_entries(entries: List[Dict[str, Any]]) -> Dict[str, int]:
    summary = {"attempted": len(entries), "executed": 0, "denied": 0, "failed": 0, "skipped": 0}
    for entry in entries:
        status = str(entry.get("status", "")).strip().lower()
        if status in summary:
            summary[status] += 1
        else:
            summary["failed"] += 1
    return summary


def _annotate_hypotheses_with_query_results(
    hypotheses: List[Dict[str, Any]],
    entries: List[Dict[str, Any]],
) -> None:
    for entry in entries:
        idx = entry.get("hypothesis_index")
        if not isinstance(idx, int):
            continue
        if idx < 0 or idx >= len(hypotheses):
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
    llm_response: Dict[str, Any],
    query_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Enrich analysis output with deterministic query-result summaries.

    Args:
        llm_response: Base structured analysis response from local LLM.
        query_results: Normalized per-query execution records.

    Returns:
        New analysis dictionary with ``query_result_section`` added when query
        results are present and hypothesis-level query summary annotations.
    """
    if not isinstance(llm_response, dict):
        return {}
    out: Dict[str, Any] = deepcopy(llm_response)

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
