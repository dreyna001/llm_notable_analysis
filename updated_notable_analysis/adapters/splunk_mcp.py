"""Splunk MCP read-only query execution adapter."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from updated_notable_analysis.core.models import QueryExecutionRequest, QueryResultEvidence
from updated_notable_analysis.core.validators import (
    normalize_mapping,
    normalize_optional_non_negative_int,
    normalize_optional_string,
    require_non_empty_string,
)
from updated_notable_analysis.core.vocabulary import EvidenceType, QueryDialect


class SplunkMcpSearchClient(Protocol):
    """Minimal MCP-facing client contract for read-only Splunk searches."""

    def run_search(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Execute one bounded read-only Splunk search through MCP."""


@dataclass(slots=True)
class SplunkMcpReadOnlyExecutor:
    """Read-only Splunk MCP executor that returns normalized query evidence."""

    client: SplunkMcpSearchClient
    mcp_tool_name: str = "splunk_search"
    raw_result_ref_prefix: str = "splunk-mcp://search"

    def __post_init__(self) -> None:
        """Validate adapter configuration."""
        if not hasattr(self.client, "run_search"):
            raise ValueError("Field 'client' must provide run_search(payload).")
        self.mcp_tool_name = require_non_empty_string(self.mcp_tool_name, "mcp_tool_name")
        self.raw_result_ref_prefix = require_non_empty_string(
            self.raw_result_ref_prefix, "raw_result_ref_prefix"
        ).rstrip("/")

    def execute(self, request: QueryExecutionRequest) -> QueryResultEvidence:
        """Execute an approved SPL query through the injected Splunk MCP client."""
        _validate_request(request)

        payload = _build_search_payload(request, self.mcp_tool_name)
        started_at = time.perf_counter()
        response = self.client.run_search(payload)
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        if not isinstance(response, Mapping):
            raise ValueError("Splunk MCP search client must return a mapping.")

        return _normalize_search_response(
            response=response,
            request=request,
            elapsed_ms=elapsed_ms,
            adapter_name=self.mcp_tool_name,
            raw_result_ref_prefix=self.raw_result_ref_prefix,
        )


def _validate_request(request: QueryExecutionRequest) -> None:
    """Validate adapter-specific request assumptions."""
    if not isinstance(request, QueryExecutionRequest):
        raise ValueError("Field 'request' must be QueryExecutionRequest.")
    if request.source_system.lower() != "splunk":
        raise ValueError("Splunk MCP executor only supports source_system='splunk'.")
    if request.query_plan.query_dialect is not QueryDialect.SPL:
        raise ValueError("Splunk MCP executor only supports SPL query plans.")
    if request.query_plan.time_range is None:
        raise ValueError("Splunk MCP executor requires query_plan.time_range.")
    if request.query_plan.max_rows is None or request.query_plan.max_rows <= 0:
        raise ValueError("Splunk MCP executor requires a positive query_plan.max_rows.")
    if (
        request.query_plan.execution_timeout_seconds is None
        or request.query_plan.execution_timeout_seconds <= 0
    ):
        raise ValueError(
            "Splunk MCP executor requires a positive query_plan.execution_timeout_seconds."
        )


def _build_search_payload(
    request: QueryExecutionRequest, mcp_tool_name: str
) -> dict[str, Any]:
    """Build the MCP client payload from the approved query request."""
    return {
        "tool_name": mcp_tool_name,
        "query": request.query_plan.query_text,
        "query_dialect": request.query_plan.query_dialect.value,
        "time_range": request.query_plan.time_range,
        "max_rows": request.query_plan.max_rows,
        "timeout_seconds": request.query_plan.execution_timeout_seconds,
        "policy_bundle_name": request.policy_bundle_name,
        "source_system": request.source_system,
    }


def _normalize_search_response(
    *,
    response: Mapping[str, Any],
    request: QueryExecutionRequest,
    elapsed_ms: int,
    adapter_name: str,
    raw_result_ref_prefix: str,
) -> QueryResultEvidence:
    """Normalize a Splunk MCP response into query-result evidence."""
    response_dict = dict(response)
    rows_returned = _extract_rows_returned(response_dict)
    if rows_returned is not None and rows_returned > request.query_plan.max_rows:
        raise ValueError("Splunk MCP response exceeds the approved max_rows limit.")

    execution_time_ms = _extract_execution_time_ms(response_dict, elapsed_ms)
    if execution_time_ms > request.query_plan.execution_timeout_seconds * 1000:
        raise ValueError("Splunk MCP response exceeds the approved execution timeout.")

    raw_result_ref = _extract_raw_result_ref(
        response_dict=response_dict,
        policy_bundle_name=request.policy_bundle_name,
        raw_result_ref_prefix=raw_result_ref_prefix,
    )
    result_summary = _extract_result_summary(response_dict, rows_returned)
    metadata = _extract_metadata(response_dict, adapter_name)

    return QueryResultEvidence(
        evidence_type=EvidenceType.QUERY_RESULT,
        query_dialect=request.query_plan.query_dialect,
        query_text=request.query_plan.query_text,
        result_summary=result_summary,
        raw_result_ref=raw_result_ref,
        rows_returned=rows_returned,
        execution_time_ms=execution_time_ms,
        metadata=metadata,
    )


def _extract_rows_returned(response: Mapping[str, Any]) -> int | None:
    """Extract row count without retaining raw row bodies in evidence metadata."""
    for field_name in ("rows_returned", "row_count", "result_count"):
        if field_name in response:
            return normalize_optional_non_negative_int(response[field_name], field_name)

    rows = response.get("rows", response.get("results"))
    if rows is None:
        return None
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ValueError("Splunk MCP response rows/results must be a sequence when present.")
    return len(rows)


def _extract_execution_time_ms(response: Mapping[str, Any], elapsed_ms: int) -> int:
    """Extract execution time, defaulting to local adapter elapsed time."""
    explicit_ms = response.get("execution_time_ms")
    if explicit_ms is not None:
        return normalize_optional_non_negative_int(explicit_ms, "execution_time_ms") or 0

    explicit_seconds = response.get("execution_time_seconds")
    if explicit_seconds is not None:
        if isinstance(explicit_seconds, bool) or not isinstance(explicit_seconds, (int, float)):
            raise ValueError("Field 'execution_time_seconds' must be numeric when present.")
        if explicit_seconds < 0:
            raise ValueError("Field 'execution_time_seconds' must be non-negative.")
        return int(explicit_seconds * 1000)

    return max(elapsed_ms, 0)


def _extract_raw_result_ref(
    *,
    response_dict: Mapping[str, Any],
    policy_bundle_name: str,
    raw_result_ref_prefix: str,
) -> str:
    """Extract or derive a durable raw result reference for citation."""
    explicit_ref = normalize_optional_string(response_dict.get("raw_result_ref"), "raw_result_ref")
    if explicit_ref is not None:
        return explicit_ref

    for id_field in ("search_id", "job_id", "sid"):
        identifier = normalize_optional_string(response_dict.get(id_field), id_field)
        if identifier is not None:
            return f"{raw_result_ref_prefix}/{policy_bundle_name}/{identifier}"

    raise ValueError("Splunk MCP response must include raw_result_ref, search_id, job_id, or sid.")


def _extract_result_summary(response: Mapping[str, Any], rows_returned: int | None) -> str:
    """Extract or derive a compact result summary."""
    summary = normalize_optional_string(response.get("result_summary"), "result_summary")
    if summary is not None:
        return summary

    count_phrase = "an unknown number of"
    if rows_returned is not None:
        count_phrase = str(rows_returned)
    return f"Splunk MCP query returned {count_phrase} row(s)."


def _extract_metadata(response: Mapping[str, Any], adapter_name: str) -> dict[str, Any]:
    """Extract safe execution metadata while avoiding raw row payloads."""
    metadata = normalize_mapping(response.get("metadata"), "metadata")
    metadata["adapter"] = "splunk_mcp"
    metadata["mcp_tool_name"] = adapter_name

    for field_name in ("search_id", "job_id", "sid", "dispatch_state"):
        value = normalize_optional_string(response.get(field_name), field_name)
        if value is not None:
            metadata[field_name] = value

    field_names = response.get("field_names")
    if field_names is not None:
        if not isinstance(field_names, Sequence) or isinstance(field_names, (str, bytes)):
            raise ValueError("Splunk MCP response field_names must be a sequence when present.")
        metadata["field_names"] = tuple(str(field_name).strip() for field_name in field_names)

    return metadata
