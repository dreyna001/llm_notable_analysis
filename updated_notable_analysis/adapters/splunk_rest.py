"""Splunk REST API read-only query execution adapter."""

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


class SplunkRestSearchTransport(Protocol):
    """Minimal REST transport contract for read-only Splunk searches."""

    def post(
        self,
        *,
        path: str,
        data: Mapping[str, Any],
        timeout_seconds: int,
    ) -> Mapping[str, Any]:
        """POST one bounded search request to the configured Splunk REST endpoint."""


@dataclass(slots=True)
class SplunkRestReadOnlyExecutor:
    """Read-only Splunk REST executor that returns normalized query evidence."""

    transport: SplunkRestSearchTransport
    search_endpoint_path: str = "/services/search/jobs/oneshot"
    output_mode: str = "json"
    raw_result_ref_prefix: str = "splunk-rest://search"

    def __post_init__(self) -> None:
        """Validate adapter configuration."""
        if not hasattr(self.transport, "post"):
            raise ValueError("Field 'transport' must provide post(path, data, timeout_seconds).")
        self.search_endpoint_path = require_non_empty_string(
            self.search_endpoint_path, "search_endpoint_path"
        )
        if not self.search_endpoint_path.startswith("/"):
            raise ValueError("Field 'search_endpoint_path' must start with '/'.")
        self.output_mode = require_non_empty_string(self.output_mode, "output_mode")
        self.raw_result_ref_prefix = require_non_empty_string(
            self.raw_result_ref_prefix, "raw_result_ref_prefix"
        ).rstrip("/")

    def execute(self, request: QueryExecutionRequest) -> QueryResultEvidence:
        """Execute an approved SPL query through the injected Splunk REST transport."""
        _validate_request(request)

        payload = _build_search_payload(request, self.output_mode)
        started_at = time.perf_counter()
        response = self.transport.post(
            path=self.search_endpoint_path,
            data=payload,
            timeout_seconds=request.query_plan.execution_timeout_seconds,
        )
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        if not isinstance(response, Mapping):
            raise ValueError("Splunk REST transport must return a mapping.")

        return _normalize_search_response(
            response=response,
            request=request,
            elapsed_ms=elapsed_ms,
            endpoint_path=self.search_endpoint_path,
            raw_result_ref_prefix=self.raw_result_ref_prefix,
        )


def _validate_request(request: QueryExecutionRequest) -> None:
    """Validate adapter-specific request assumptions."""
    if not isinstance(request, QueryExecutionRequest):
        raise ValueError("Field 'request' must be QueryExecutionRequest.")
    if request.source_system.lower() != "splunk":
        raise ValueError("Splunk REST executor only supports source_system='splunk'.")
    if request.query_plan.query_dialect is not QueryDialect.SPL:
        raise ValueError("Splunk REST executor only supports SPL query plans.")
    if request.query_plan.time_range is None:
        raise ValueError("Splunk REST executor requires query_plan.time_range.")
    if request.query_plan.max_rows is None or request.query_plan.max_rows <= 0:
        raise ValueError("Splunk REST executor requires a positive query_plan.max_rows.")
    if (
        request.query_plan.execution_timeout_seconds is None
        or request.query_plan.execution_timeout_seconds <= 0
    ):
        raise ValueError(
            "Splunk REST executor requires a positive query_plan.execution_timeout_seconds."
        )


def _build_search_payload(
    request: QueryExecutionRequest, output_mode: str
) -> dict[str, Any]:
    """Build a bounded Splunk REST oneshot-search payload."""
    return {
        "search": request.query_plan.query_text,
        "output_mode": output_mode,
        "exec_mode": "oneshot",
        "earliest_time": f"-{request.query_plan.time_range}",
        "latest_time": "now",
        "count": request.query_plan.max_rows,
        "timeout": request.query_plan.execution_timeout_seconds,
    }


def _normalize_search_response(
    *,
    response: Mapping[str, Any],
    request: QueryExecutionRequest,
    elapsed_ms: int,
    endpoint_path: str,
    raw_result_ref_prefix: str,
) -> QueryResultEvidence:
    """Normalize a Splunk REST response into query-result evidence."""
    response_dict = dict(response)
    rows_returned = _extract_rows_returned(response_dict)
    if rows_returned is not None and rows_returned > request.query_plan.max_rows:
        raise ValueError("Splunk REST response exceeds the approved max_rows limit.")

    execution_time_ms = _extract_execution_time_ms(response_dict, elapsed_ms)
    if execution_time_ms > request.query_plan.execution_timeout_seconds * 1000:
        raise ValueError("Splunk REST response exceeds the approved execution timeout.")

    raw_result_ref = _extract_raw_result_ref(
        response_dict=response_dict,
        policy_bundle_name=request.policy_bundle_name,
        raw_result_ref_prefix=raw_result_ref_prefix,
    )
    result_summary = _extract_result_summary(response_dict, rows_returned)
    metadata = _extract_metadata(response_dict, endpoint_path)

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
        raise ValueError("Splunk REST response rows/results must be a sequence when present.")
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

    raise ValueError("Splunk REST response must include raw_result_ref, search_id, job_id, or sid.")


def _extract_result_summary(response: Mapping[str, Any], rows_returned: int | None) -> str:
    """Extract or derive a compact result summary."""
    summary = normalize_optional_string(response.get("result_summary"), "result_summary")
    if summary is not None:
        return summary

    count_phrase = "an unknown number of"
    if rows_returned is not None:
        count_phrase = str(rows_returned)
    return f"Splunk REST query returned {count_phrase} row(s)."


def _extract_metadata(response: Mapping[str, Any], endpoint_path: str) -> dict[str, Any]:
    """Extract safe execution metadata while avoiding raw row payloads."""
    metadata = normalize_mapping(response.get("metadata"), "metadata")
    metadata["adapter"] = "splunk_rest"
    metadata["endpoint_path"] = endpoint_path

    for field_name in ("search_id", "job_id", "sid", "dispatch_state"):
        value = normalize_optional_string(response.get(field_name), field_name)
        if value is not None:
            metadata[field_name] = value

    field_names = response.get("field_names")
    if field_names is not None:
        if not isinstance(field_names, Sequence) or isinstance(field_names, (str, bytes)):
            raise ValueError("Splunk REST response field_names must be a sequence when present.")
        metadata["field_names"] = tuple(str(field_name).strip() for field_name in field_names)

    return metadata
