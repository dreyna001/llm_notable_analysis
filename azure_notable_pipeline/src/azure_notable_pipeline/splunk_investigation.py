"""Read-only Splunk investigation query execution helpers."""

from __future__ import annotations

import concurrent.futures
import re
from typing import Any, Mapping, Protocol

import requests

from .config import Config
from .runtime_security import validate_https_url

_DEFAULT_ALLOWED_INDEXES = "main,notable,risk"
_DEFAULT_ALLOWED_COMMANDS = "search,stats,table,fields,where,head"
_DEFAULT_DENIED_COMMANDS = "delete,collect,outputlookup,sendemail,map,rest,script,dbxquery"
_DEFAULT_MAX_TIME_RANGE = "24h"
_DEFAULT_MAX_ROWS = 100
_DEFAULT_TIMEOUT_SECONDS = 30
_DEFAULT_MAX_QUERIES_PER_ALERT = 6
_DEFAULT_MAX_CONCURRENT_QUERIES = 6
_DEFAULT_SEARCH_ENDPOINT_PATH = "/services/search/jobs/oneshot"
_MAX_RESULT_SAMPLE_ROWS = 5
_MAX_SAMPLE_ROW_COLUMNS = 12
_MAX_SAMPLE_VALUE_CHARS = 160
_INDEX_RE = re.compile(r"\bindex\s*=\s*([A-Za-z0-9_\-*]+)", re.IGNORECASE)
_DURATION_RE = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.IGNORECASE)


class SplunkMcpClient(Protocol):
    """Minimal MCP client contract for Splunk search execution."""

    def run_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute a bounded Splunk search and return a mapping response."""


class HttpSplunkMcpClient:
    """MCP-over-HTTPS bridge client with a narrow search payload contract."""

    def __init__(
        self,
        *,
        endpoint: str,
        bearer_token: str = "",
        timeout_seconds: int = 35,
        allow_private: bool = False,
    ):
        self.endpoint = validate_https_url(
            endpoint,
            setting_name="SPLUNK_MCP_ENDPOINT",
            allow_private=allow_private,
        )
        self.bearer_token = bearer_token
        self.timeout_seconds = timeout_seconds

    def run_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        response = requests.post(
            self.endpoint,
            json=payload,
            headers=headers,
            timeout=self.timeout_seconds,
            verify=True,
        )
        response.raise_for_status()
        response_obj = response.json()
        if not isinstance(response_obj, dict):
            raise ValueError("MCP response must be an object")
        return response_obj


def _csv_to_list(value: str) -> list[str]:
    return [part.strip().lower() for part in (value or "").split(",") if part.strip()]


def _duration_to_seconds(value: str) -> int | None:
    match = _DURATION_RE.match(str(value or ""))
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    factor = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    return amount * factor


def _duration_to_earliest_time(value: str) -> str:
    clean = str(value or "").strip()
    return clean if clean.startswith("-") else f"-{clean}"


def _extract_commands(query: str) -> list[str]:
    commands: list[str] = []
    for segment in [s.strip() for s in query.split("|")]:
        if not segment:
            continue
        first_token = segment.split()[0].lower()
        if first_token:
            commands.append(first_token)
    return commands


def _unsupported_commands(commands: list[str], allowed_commands: list[str]) -> list[str]:
    unsupported: list[str] = []
    for pos, command in enumerate(commands):
        if pos == 0 and "=" in command:
            continue
        if command not in allowed_commands:
            unsupported.append(command)
    return unsupported


def _allowed_fields(config: Config) -> set[str]:
    return {part.strip().casefold() for part in str(getattr(config, "SPLUNK_SEARCH_ALLOWED_FIELDS", "")).split(",") if part.strip()}


def _bounded_sample_rows(rows: Any, *, allowed_fields: set[str] | None = None) -> list[dict[str, str]]:
    if not isinstance(rows, list):
        return []
    allowed = allowed_fields or set()
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        clean_row: dict[str, str] = {}
        for key in sorted(row.keys())[:_MAX_SAMPLE_ROW_COLUMNS]:
            clean_key = str(key).strip()[:80]
            if clean_key == "_raw":
                continue
            if allowed and clean_key.casefold() not in allowed:
                continue
            clean_value = str(row.get(key, "")).strip()
            if len(clean_value) > _MAX_SAMPLE_VALUE_CHARS:
                clean_value = clean_value[: _MAX_SAMPLE_VALUE_CHARS - 3].rstrip() + "..."
            if clean_key:
                clean_row[clean_key] = clean_value
        if clean_row:
            out.append(clean_row)
        if len(out) >= _MAX_RESULT_SAMPLE_ROWS:
            break
    return out


def validate_splunk_query_policy(
    query: str,
    *,
    config: Config,
    time_range: str,
    max_rows: int,
    timeout_seconds: int,
) -> tuple[bool, str | None]:
    """Validate generated SPL query against read-only policy and bounds."""

    query_clean = str(query or "").strip()
    if not query_clean:
        return False, "query is empty"
    if "[" in query_clean or "]" in query_clean or "`" in query_clean:
        return False, "query contains subsearch or macro syntax that is denied by policy"

    allowed_indexes = _csv_to_list(
        str(getattr(config, "SPLUNK_SEARCH_ALLOWED_INDEXES", _DEFAULT_ALLOWED_INDEXES))
    )
    query_indexes = [m.group(1).strip().lower() for m in _INDEX_RE.finditer(query_clean)]
    if not query_indexes:
        return False, "query must include explicit index=..."
    if allowed_indexes and any(idx not in allowed_indexes for idx in query_indexes):
        return False, "query index is not in allowed index policy"

    denied_commands = _csv_to_list(
        str(getattr(config, "SPLUNK_SEARCH_DENIED_COMMANDS", _DEFAULT_DENIED_COMMANDS))
    )
    for denied in denied_commands:
        if re.search(rf"\b{re.escape(denied)}\b", query_clean, re.IGNORECASE):
            return False, f"query contains denied command: {denied}"

    commands_present = _extract_commands(query_clean)
    allowed_commands = _csv_to_list(
        str(getattr(config, "SPLUNK_SEARCH_ALLOWED_COMMANDS", _DEFAULT_ALLOWED_COMMANDS))
    )
    if allowed_commands and not any(cmd in allowed_commands for cmd in commands_present):
        return False, "query does not contain an allowed command"
    unsupported = _unsupported_commands(commands_present, allowed_commands)
    if allowed_commands and unsupported:
        return False, f"query contains non-allowlisted command: {unsupported[0]}"

    requested_range_seconds = _duration_to_seconds(time_range)
    max_range_seconds = _duration_to_seconds(
        str(getattr(config, "SPLUNK_SEARCH_MAX_TIME_RANGE", _DEFAULT_MAX_TIME_RANGE))
    )
    if requested_range_seconds is None or max_range_seconds is None:
        return False, "invalid time range format"
    if requested_range_seconds > max_range_seconds:
        return False, "time range exceeds configured max"

    configured_max_rows = int(getattr(config, "SPLUNK_SEARCH_MAX_ROWS", _DEFAULT_MAX_ROWS))
    if max_rows <= 0 or max_rows > configured_max_rows:
        return False, "max rows exceeds configured max"

    configured_timeout = int(
        getattr(config, "SPLUNK_SEARCH_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS)
    )
    if timeout_seconds <= 0 or timeout_seconds > configured_timeout:
        return False, "timeout exceeds configured max"

    return True, None


def extract_hypothesis_queries(
    analysis_result: dict[str, Any],
    *,
    max_queries: int,
) -> list[dict[str, Any]]:
    """Extract per-hypothesis SPL candidates from model analysis output."""

    hypotheses = analysis_result.get("competing_hypotheses", [])
    if not isinstance(hypotheses, list):
        return []

    out: list[dict[str, Any]] = []
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


def _normalize_rest_result(query: str, response_json: Mapping[str, Any], *, config: Config) -> dict[str, Any]:
    rows = response_json.get("results")
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        rows = []

    allowed = _allowed_fields(config)
    sample_rows = _bounded_sample_rows(rows, allowed_fields=allowed)
    sample_columns = sorted(str(k) for k in sample_rows[0].keys()) if sample_rows else []

    search_ref = response_json.get("sid") or response_json.get("search_id") or response_json.get("job_id")
    return {
        "status": "success",
        "executor": "rest",
        "query": query,
        "result_count": len(rows),
        "sample_columns": sample_columns,
        "sample_rows": sample_rows,
        "search_id": search_ref,
    }


def execute_splunk_rest_query(
    query: str,
    *,
    config: Config,
    api_token: str,
    time_range: str,
    max_rows: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Execute one read-only Splunk search via REST oneshot endpoint."""

    allowed, reason = validate_splunk_query_policy(
        query,
        config=config,
        time_range=time_range,
        max_rows=max_rows,
        timeout_seconds=timeout_seconds,
    )
    if not allowed:
        return {"status": "denied", "executor": "rest", "query": query, "message": reason}

    if not config.SPLUNK_BASE_URL or not api_token:
        return {
            "status": "error",
            "executor": "rest",
            "query": query,
            "message": "Splunk REST credentials are not configured",
        }

    endpoint_path = str(getattr(config, "SPLUNK_SEARCH_ENDPOINT_PATH", _DEFAULT_SEARCH_ENDPOINT_PATH))
    if not endpoint_path.startswith("/"):
        endpoint_path = f"/{endpoint_path}"
    base_url = validate_https_url(
        config.SPLUNK_BASE_URL,
        setting_name="SPLUNK_BASE_URL",
        allow_private=bool(getattr(config, "ALLOW_PRIVATE_OUTBOUND_ENDPOINTS", False)),
    )
    rest_url = f"{base_url.rstrip('/')}{endpoint_path}"
    headers = {
        "Authorization": f"Bearer {api_token}",
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

    try:
        response = requests.post(
            rest_url,
            data=data,
            headers=headers,
            timeout=timeout_seconds,
            verify=True,
        )
        response.raise_for_status()
        response_json = response.json()
        if not isinstance(response_json, Mapping):
            return {
                "status": "error",
                "executor": "rest",
                "query": query,
                "message": "Splunk REST response must be an object",
            }
        return _normalize_rest_result(query, response_json, config=config)
    except (requests.RequestException, ValueError) as exc:
        return {"status": "error", "executor": "rest", "query": query, "message": str(exc)}


def _normalize_mcp_result(query: str, response_obj: Mapping[str, Any], *, config: Config) -> dict[str, Any]:
    ref_key: str | None = None
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
    allowed = _allowed_fields(config)
    sample_rows = _bounded_sample_rows(rows, allowed_fields=allowed)
    sample_columns = sorted(str(k) for k in sample_rows[0].keys()) if sample_rows else []
    result_count = response_obj.get("result_count")
    if not isinstance(result_count, int):
        result_count = len(rows)

    return {
        "status": "success",
        "executor": "mcp",
        "query": query,
        "result_count": result_count,
        "sample_columns": sample_columns,
        "sample_rows": sample_rows,
        ref_key: response_obj.get(ref_key),
    }


def execute_splunk_mcp_query(
    query: str,
    *,
    config: Config,
    mcp_client: SplunkMcpClient | None,
    time_range: str,
    max_rows: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Execute one read-only Splunk search through an MCP bridge client."""

    allowed, reason = validate_splunk_query_policy(
        query,
        config=config,
        time_range=time_range,
        max_rows=max_rows,
        timeout_seconds=timeout_seconds,
    )
    if not allowed:
        return {"status": "denied", "executor": "mcp", "query": query, "message": reason}
    if mcp_client is None:
        return {
            "status": "error",
            "executor": "mcp",
            "query": query,
            "message": "MCP client is not configured",
        }

    payload = {
        "tool_name": str(getattr(config, "SPLUNK_MCP_TOOL_NAME", "splunk_search")),
        "query": query,
        "query_dialect": "spl",
        "time_range": time_range,
        "max_rows": max_rows,
        "timeout_seconds": timeout_seconds,
    }

    try:
        response_obj = mcp_client.run_search(payload)
    except (RuntimeError, ValueError, TypeError, AttributeError, requests.RequestException) as exc:
        return {"status": "error", "executor": "mcp", "query": query, "message": str(exc)}
    if not isinstance(response_obj, Mapping):
        return {
            "status": "error",
            "executor": "mcp",
            "query": query,
            "message": "MCP response must be an object",
        }
    return _normalize_mcp_result(query, response_obj, config=config)


def execute_hypothesis_queries(
    analysis_result: dict[str, Any],
    *,
    config: Config,
    api_token: str = "",
    mcp_client: SplunkMcpClient | None = None,
) -> list[dict[str, Any]]:
    """Execute bounded hypothesis queries via the selected Splunk executor."""

    if not bool(getattr(config, "INVESTIGATION_QUERY_EXECUTION_ENABLED", False)):
        return []
    if str(getattr(config, "INVESTIGATION_QUERY_BACKEND", "splunk")).strip().lower() != "splunk":
        return []

    max_queries = int(
        getattr(config, "INVESTIGATION_MAX_QUERIES_PER_ALERT", _DEFAULT_MAX_QUERIES_PER_ALERT)
    )
    max_concurrent = int(
        getattr(config, "INVESTIGATION_MAX_CONCURRENT_QUERIES", _DEFAULT_MAX_CONCURRENT_QUERIES)
    )
    executor_name = str(getattr(config, "INVESTIGATION_QUERY_EXECUTOR", "rest")).strip().lower()
    time_range = str(getattr(config, "SPLUNK_SEARCH_MAX_TIME_RANGE", _DEFAULT_MAX_TIME_RANGE))
    max_rows = int(getattr(config, "SPLUNK_SEARCH_MAX_ROWS", _DEFAULT_MAX_ROWS))
    timeout_seconds = int(
        getattr(config, "SPLUNK_SEARCH_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS)
    )

    candidates = extract_hypothesis_queries(analysis_result, max_queries=max_queries)
    if not candidates:
        return []

    max_workers = min(max_concurrent, len(candidates))
    indexed_results: list[tuple[int, dict[str, Any]]] = []

    def _run_one(pos: int, item: dict[str, Any]) -> tuple[int, dict[str, Any]]:
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
                api_token=api_token,
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
