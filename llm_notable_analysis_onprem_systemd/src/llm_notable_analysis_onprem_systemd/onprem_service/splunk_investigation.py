"""Read-only Splunk investigation query execution helpers.

This module validates generated SPL queries against deterministic policy rules
and executes eligible queries through Splunk REST or an injected MCP client.
"""

from __future__ import annotations

import logging
import re
import concurrent.futures
from typing import Any, Dict, List, Mapping, Optional, Protocol, Tuple

import requests

from .config import Config

logger = logging.getLogger(__name__)

_DEFAULT_ALLOWED_INDEXES = "main,notable,risk"
_DEFAULT_ALLOWED_COMMANDS = "search,stats,table,fields,where,head"
_DEFAULT_DENIED_COMMANDS = "delete,collect,outputlookup,sendemail,map,rest,script,dbxquery"
_DEFAULT_MAX_TIME_RANGE = "24h"
_DEFAULT_MAX_ROWS = 100
_DEFAULT_TIMEOUT_SECONDS = 20
_DEFAULT_MAX_QUERIES_PER_ALERT = 6
_DEFAULT_MAX_CONCURRENT_QUERIES = 3
_DEFAULT_SEARCH_ENDPOINT_PATH = "/services/search/jobs/oneshot"
_DEFAULT_MCP_TOOL_NAME = "splunk_search"
_INDEX_RE = re.compile(r"\bindex\s*=\s*([A-Za-z0-9_\-*]+)", re.IGNORECASE)
_DURATION_RE = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.IGNORECASE)


class SplunkMcpClient(Protocol):
    """Minimal MCP client contract for Splunk search execution."""

    def run_search(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a bounded Splunk search and return a mapping response."""


def _csv_to_list(value: str) -> List[str]:
    return [part.strip().lower() for part in (value or "").split(",") if part.strip()]


def _duration_to_seconds(value: str) -> Optional[int]:
    match = _DURATION_RE.match(str(value or ""))
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    factor = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    return amount * factor


def _duration_to_earliest_time(value: str) -> str:
    clean = str(value or "").strip()
    if clean.startswith("-"):
        return clean
    return f"-{clean}"


def _extract_commands(query: str) -> List[str]:
    commands: List[str] = []
    for segment in [s.strip() for s in query.split("|")]:
        if not segment:
            continue
        first_token = segment.split()[0].lower()
        if first_token:
            commands.append(first_token)
    return commands


def validate_splunk_query_policy(
    query: str,
    *,
    config: Config,
    time_range: str,
    max_rows: int,
    timeout_seconds: int,
) -> Tuple[bool, Optional[str]]:
    """Validate generated SPL query against read-only policy and bounds.

    Args:
        query: SPL query string.
        config: Service configuration.
        time_range: Query lookback window (e.g., ``24h``).
        max_rows: Max rows requested from Splunk.
        timeout_seconds: Request timeout for the query.

    Returns:
        Tuple of ``(is_allowed, reason)`` where ``reason`` is populated when
        denied.
    """
    query_clean = str(query or "").strip()
    if not query_clean:
        return False, "query is empty"

    allowed_indexes = _csv_to_list(
        str(
            getattr(
                config,
                "SPLUNK_SEARCH_ALLOWED_INDEXES",
                _DEFAULT_ALLOWED_INDEXES,
            )
        )
    )
    query_indexes = [m.group(1).strip().lower() for m in _INDEX_RE.finditer(query_clean)]
    if not query_indexes:
        return False, "query must include explicit index=..."
    if allowed_indexes and any(idx not in allowed_indexes for idx in query_indexes):
        return False, "query index is not in allowed index policy"

    denied_commands = _csv_to_list(
        str(
            getattr(
                config,
                "SPLUNK_SEARCH_DENIED_COMMANDS",
                _DEFAULT_DENIED_COMMANDS,
            )
        )
    )
    for denied in denied_commands:
        if re.search(rf"\b{re.escape(denied)}\b", query_clean, re.IGNORECASE):
            return False, f"query contains denied command: {denied}"

    commands_present = _extract_commands(query_clean)
    allowed_commands = _csv_to_list(
        str(
            getattr(
                config,
                "SPLUNK_SEARCH_ALLOWED_COMMANDS",
                _DEFAULT_ALLOWED_COMMANDS,
            )
        )
    )
    if allowed_commands and not any(cmd in allowed_commands for cmd in commands_present):
        return False, "query does not contain an allowed command"

    requested_range_seconds = _duration_to_seconds(time_range)
    max_range_seconds = _duration_to_seconds(
        str(
            getattr(
                config,
                "SPLUNK_SEARCH_MAX_TIME_RANGE",
                _DEFAULT_MAX_TIME_RANGE,
            )
        )
    )
    if requested_range_seconds is None or max_range_seconds is None:
        return False, "invalid time range format"
    if requested_range_seconds > max_range_seconds:
        return False, "time range exceeds configured max"

    configured_max_rows = int(
        getattr(config, "SPLUNK_SEARCH_MAX_ROWS", _DEFAULT_MAX_ROWS)
    )
    if max_rows <= 0 or max_rows > configured_max_rows:
        return False, "max rows exceeds configured max"

    configured_timeout = int(
        getattr(config, "SPLUNK_SEARCH_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS)
    )
    if timeout_seconds <= 0 or timeout_seconds > configured_timeout:
        return False, "timeout exceeds configured max"

    return True, None


def extract_hypothesis_queries(
    analysis_result: Dict[str, Any],
    *,
    max_queries: int,
) -> List[Dict[str, Any]]:
    """Extract per-hypothesis query candidates from model analysis output.

    Args:
        analysis_result: Structured LLM analysis output.
        max_queries: Max number of queries to return.

    Returns:
        List of query candidate records preserving hypothesis order.
    """
    hypotheses = analysis_result.get("competing_hypotheses", [])
    if not isinstance(hypotheses, list):
        return []

    out: List[Dict[str, Any]] = []
    for idx, item in enumerate(hypotheses):
        if not isinstance(item, dict):
            continue
        query = str(item.get("primary_spl_query", "")).strip()
        if not query:
            continue
        out.append(
            {
                "hypothesis_index": idx,
                "query_strategy": str(item.get("query_strategy", "")).strip().lower(),
                "query": query,
                "supports_if": str(item.get("supports_if", "")).strip(),
                "weakens_if": str(item.get("weakens_if", "")).strip(),
            }
        )
        if len(out) >= max_queries:
            break
    return out


def _normalize_rest_result(
    query: str,
    response_json: Mapping[str, Any],
) -> Dict[str, Any]:
    rows = response_json.get("results")
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        rows = []

    sample_columns: List[str] = []
    if rows and isinstance(rows[0], dict):
        sample_columns = sorted(str(k) for k in rows[0].keys())

    search_ref = (
        response_json.get("sid")
        or response_json.get("search_id")
        or response_json.get("job_id")
    )
    return {
        "status": "success",
        "executor": "rest",
        "query": query,
        "result_count": len(rows),
        "sample_columns": sample_columns,
        "search_id": search_ref,
    }


def execute_splunk_rest_query(
    query: str,
    *,
    config: Config,
    time_range: str,
    max_rows: int,
    timeout_seconds: int,
) -> Dict[str, Any]:
    """Execute one read-only Splunk search via REST oneshot endpoint."""
    allowed, reason = validate_splunk_query_policy(
        query,
        config=config,
        time_range=time_range,
        max_rows=max_rows,
        timeout_seconds=timeout_seconds,
    )
    if not allowed:
        return {
            "status": "denied",
            "executor": "rest",
            "query": query,
            "message": reason,
        }

    if not config.SPLUNK_BASE_URL or not config.SPLUNK_API_TOKEN:
        return {
            "status": "error",
            "executor": "rest",
            "query": query,
            "message": "Splunk REST credentials are not configured",
        }

    endpoint_path = str(
        getattr(config, "SPLUNK_SEARCH_ENDPOINT_PATH", _DEFAULT_SEARCH_ENDPOINT_PATH)
    )
    if not endpoint_path.startswith("/"):
        endpoint_path = f"/{endpoint_path}"
    rest_url = f"{config.SPLUNK_BASE_URL.rstrip('/')}{endpoint_path}"
    headers = {
        "Authorization": f"Bearer {config.SPLUNK_API_TOKEN}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    search_query = query if query.lstrip().lower().startswith("search") else f"search {query}"
    data = {
        "search": search_query,
        "earliest_time": _duration_to_earliest_time(time_range),
        "latest_time": "now",
        "output_mode": "json",
        "count": str(max_rows),
    }
    verify_tls = config.SPLUNK_CA_BUNDLE if config.SPLUNK_CA_BUNDLE else True

    try:
        response = requests.post(
            rest_url,
            data=data,
            headers=headers,
            timeout=timeout_seconds,
            verify=verify_tls,
        )
        response.raise_for_status()
        try:
            response_json = response.json()
        except ValueError:
            return {
                "status": "error",
                "executor": "rest",
                "query": query,
                "message": "Splunk REST response was not valid JSON",
            }
        if not isinstance(response_json, Mapping):
            return {
                "status": "error",
                "executor": "rest",
                "query": query,
                "message": "Splunk REST response must be an object",
            }
        return _normalize_rest_result(query, response_json)
    except requests.RequestException as exc:
        return {
            "status": "error",
            "executor": "rest",
            "query": query,
            "message": str(exc),
        }


def _normalize_mcp_result(
    query: str,
    response_obj: Mapping[str, Any],
) -> Dict[str, Any]:
    ref_key: Optional[str] = None
    for key in ("raw_result_ref", "search_id", "job_id", "sid"):
        if response_obj.get(key):
            ref_key = key
            break
    if not ref_key:
        return {
            "status": "error",
            "executor": "mcp",
            "query": query,
            "message": "MCP response missing expected search reference field",
        }

    rows = response_obj.get("rows")
    if not isinstance(rows, list):
        rows = []
    sample_columns: List[str] = []
    if rows and isinstance(rows[0], dict):
        sample_columns = sorted(str(k) for k in rows[0].keys())
    result_count = response_obj.get("result_count")
    if not isinstance(result_count, int):
        result_count = len(rows)

    return {
        "status": "success",
        "executor": "mcp",
        "query": query,
        "result_count": result_count,
        "sample_columns": sample_columns,
        ref_key: response_obj.get(ref_key),
    }


def execute_splunk_mcp_query(
    query: str,
    *,
    config: Config,
    mcp_client: Optional[SplunkMcpClient],
    time_range: str,
    max_rows: int,
    timeout_seconds: int,
) -> Dict[str, Any]:
    """Execute one read-only Splunk search through an injected MCP client."""
    allowed, reason = validate_splunk_query_policy(
        query,
        config=config,
        time_range=time_range,
        max_rows=max_rows,
        timeout_seconds=timeout_seconds,
    )
    if not allowed:
        return {
            "status": "denied",
            "executor": "mcp",
            "query": query,
            "message": reason,
        }
    if mcp_client is None:
        return {
            "status": "error",
            "executor": "mcp",
            "query": query,
            "message": "MCP client is not configured",
        }

    payload = {
        "tool_name": str(
            getattr(config, "SPLUNK_MCP_TOOL_NAME", _DEFAULT_MCP_TOOL_NAME)
        ),
        "query": query,
        "query_dialect": "spl",
        "time_range": time_range,
        "max_rows": max_rows,
        "timeout_seconds": timeout_seconds,
    }

    try:
        response_obj = mcp_client.run_search(payload)
    except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
        return {
            "status": "error",
            "executor": "mcp",
            "query": query,
            "message": str(exc),
        }
    if not isinstance(response_obj, Mapping):
        return {
            "status": "error",
            "executor": "mcp",
            "query": query,
            "message": "MCP response must be an object",
        }
    return _normalize_mcp_result(query, response_obj)


def execute_hypothesis_queries(
    analysis_result: Dict[str, Any],
    *,
    config: Config,
    mcp_client: Optional[SplunkMcpClient] = None,
) -> List[Dict[str, Any]]:
    """Execute bounded hypothesis queries via selected executor.

    Args:
        analysis_result: Structured model output containing competing hypotheses.
        config: Service configuration.
        mcp_client: Optional injected MCP client for ``mcp`` executor mode.

    Returns:
        List of normalized query execution records.
    """
    if not bool(getattr(config, "INVESTIGATION_QUERY_EXECUTION_ENABLED", False)):
        return []

    max_queries = int(
        getattr(
            config,
            "INVESTIGATION_MAX_QUERIES_PER_ALERT",
            _DEFAULT_MAX_QUERIES_PER_ALERT,
        )
    )
    max_concurrent = int(
        getattr(
            config,
            "INVESTIGATION_MAX_CONCURRENT_QUERIES",
            _DEFAULT_MAX_CONCURRENT_QUERIES,
        )
    )
    executor_name = str(
        getattr(config, "INVESTIGATION_QUERY_EXECUTOR", "rest")
    ).strip().lower()
    time_range = str(
        getattr(config, "SPLUNK_SEARCH_MAX_TIME_RANGE", _DEFAULT_MAX_TIME_RANGE)
    )
    max_rows = int(getattr(config, "SPLUNK_SEARCH_MAX_ROWS", _DEFAULT_MAX_ROWS))
    timeout_seconds = int(
        getattr(config, "SPLUNK_SEARCH_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS)
    )

    candidates = extract_hypothesis_queries(analysis_result, max_queries=max_queries)
    if not candidates:
        return []

    max_workers = min(max_concurrent, len(candidates))
    indexed_results: List[Tuple[int, Dict[str, Any]]] = []

    def _run_one(pos: int, item: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        query = str(item.get("query", "")).strip()
        if executor_name == "mcp":
            result = execute_splunk_mcp_query(
                query,
                config=config,
                mcp_client=mcp_client,
                time_range=time_range,
                max_rows=max_rows,
                timeout_seconds=timeout_seconds,
            )
        elif executor_name == "rest":
            result = execute_splunk_rest_query(
                query,
                config=config,
                time_range=time_range,
                max_rows=max_rows,
                timeout_seconds=timeout_seconds,
            )
        else:
            result = {
                "status": "error",
                "executor": executor_name,
                "query": query,
                "message": "Unsupported investigation query executor",
            }
        result["hypothesis_index"] = item.get("hypothesis_index")
        result["query_strategy"] = item.get("query_strategy", "")
        result["supports_if"] = item.get("supports_if", "")
        result["weakens_if"] = item.get("weakens_if", "")
        return pos, result

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_run_one, idx, item) for idx, item in enumerate(candidates)]
        for future in concurrent.futures.as_completed(futures):
            indexed_results.append(future.result())

    indexed_results.sort(key=lambda pair: pair[0])
    return [item for _, item in indexed_results]
