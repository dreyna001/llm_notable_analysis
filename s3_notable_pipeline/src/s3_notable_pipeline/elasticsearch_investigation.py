"""Read-only Elasticsearch investigation query execution helpers."""

from __future__ import annotations

import concurrent.futures
from copy import deepcopy
import fnmatch
import json
from typing import Any, Mapping
from urllib.parse import quote

import requests

from .config import Config
from .elastic_query_generation import duration_to_seconds, validate_elastic_query_contract

_DEFAULT_MAX_TIME_RANGE = "24h"
_DEFAULT_MAX_ROWS = 100
_DEFAULT_TIMEOUT_SECONDS = 30
_DEFAULT_MAX_QUERIES_PER_ALERT = 6
_DEFAULT_MAX_CONCURRENT_QUERIES = 6
_MAX_RESULT_SAMPLE_ROWS = 5
_MAX_SAMPLE_ROW_COLUMNS = 12
_MAX_SAMPLE_VALUE_CHARS = 160
_INDEX_FORBIDDEN_CHARS = {",", "/", "\\", "?", "#"}


def _csv_to_list(value: str) -> list[str]:
    return [part.strip().lower() for part in (value or "").split(",") if part.strip()]


def _query_to_compact_text(primary_query: Mapping[str, Any]) -> str:
    return json.dumps(primary_query, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _allowed_fields(config: Config) -> list[str]:
    return _csv_to_list(str(getattr(config, "ELASTICSEARCH_ALLOWED_FIELDS", "")))


def _index_allowed(index_pattern: str, *, allowed_patterns: list[str], allow_wildcards: bool) -> bool:
    clean = index_pattern.strip().lower()
    if not clean or any(char in clean for char in _INDEX_FORBIDDEN_CHARS):
        return False
    if "*" in clean and not allow_wildcards:
        return False
    return any(fnmatch.fnmatch(clean, allowed) for allowed in allowed_patterns)


def _bounded_sample_rows(rows: Any, *, allowed_fields: list[str]) -> list[dict[str, str]]:
    if not isinstance(rows, list):
        return []
    allowed = {field.casefold() for field in allowed_fields}
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        source = row.get("_source", row)
        if not isinstance(source, Mapping):
            continue
        clean_row: dict[str, str] = {}
        for key in sorted(source.keys())[:_MAX_SAMPLE_ROW_COLUMNS]:
            clean_key = str(key).strip()[:80]
            if allowed and clean_key.casefold() not in allowed:
                continue
            clean_value = str(source.get(key, "")).strip()
            if len(clean_value) > _MAX_SAMPLE_VALUE_CHARS:
                clean_value = clean_value[: _MAX_SAMPLE_VALUE_CHARS - 3].rstrip() + "..."
            if clean_key:
                clean_row[clean_key] = clean_value
        if clean_row:
            out.append(clean_row)
        if len(out) >= _MAX_RESULT_SAMPLE_ROWS:
            break
    return out


def _hypothesis_for_policy(primary_query: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "query_strategy": "resolve_unknown",
        "primary_elastic_query": dict(primary_query),
        "why_this_query": "policy validation",
        "supports_if": "results present",
        "weakens_if": "results absent",
    }


def validate_elasticsearch_query_policy(
    primary_query: Mapping[str, Any],
    *,
    config: Config,
    time_range: str,
    max_rows: int,
    timeout_seconds: int,
) -> tuple[bool, str | None]:
    """Validate generated Query DSL request against read-only policy and bounds."""

    if not isinstance(primary_query, Mapping):
        return False, "query must be an object"
    index_pattern = str(primary_query.get("index_pattern", "")).strip()
    body = primary_query.get("body")
    allowed_patterns = _csv_to_list(str(getattr(config, "ELASTICSEARCH_INDEX_ALLOWLIST", "")))
    if not allowed_patterns:
        return False, "ELASTICSEARCH_INDEX_ALLOWLIST must contain at least one index pattern"
    if not _index_allowed(
        index_pattern,
        allowed_patterns=allowed_patterns,
        allow_wildcards=bool(getattr(config, "ELASTICSEARCH_ALLOW_WILDCARD_INDEXES", False)),
    ):
        return False, "query index_pattern is not in allowed index policy"
    if not _allowed_fields(config):
        return False, "ELASTICSEARCH_ALLOWED_FIELDS must contain at least one field"

    requested_range_seconds = duration_to_seconds(time_range)
    max_range_seconds = duration_to_seconds(
        str(getattr(config, "ELASTICSEARCH_MAX_TIME_RANGE", _DEFAULT_MAX_TIME_RANGE))
    )
    if requested_range_seconds is None or max_range_seconds is None:
        return False, "invalid time range format"
    if requested_range_seconds > max_range_seconds:
        return False, "time range exceeds configured max"

    configured_max_rows = int(getattr(config, "ELASTICSEARCH_MAX_ROWS", _DEFAULT_MAX_ROWS))
    if max_rows <= 0 or max_rows > configured_max_rows:
        return False, "max rows exceeds configured max"
    configured_timeout = int(getattr(config, "ELASTICSEARCH_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS))
    if timeout_seconds <= 0 or timeout_seconds > configured_timeout:
        return False, "timeout exceeds configured max"

    payload = {"competing_hypotheses": [_hypothesis_for_policy(primary_query)] * 6}
    ok, err = validate_elastic_query_contract(
        payload,
        allowed_fields=str(getattr(config, "ELASTICSEARCH_ALLOWED_FIELDS", "")),
        allowed_index_patterns=str(getattr(config, "ELASTICSEARCH_INDEX_ALLOWLIST", "")),
        allow_wildcard_indexes=bool(getattr(config, "ELASTICSEARCH_ALLOW_WILDCARD_INDEXES", False)),
        max_rows=max_rows,
        max_time_range=str(getattr(config, "ELASTICSEARCH_MAX_TIME_RANGE", _DEFAULT_MAX_TIME_RANGE)),
        timestamp_field=str(getattr(config, "ELASTICSEARCH_TIMESTAMP_FIELD", "@timestamp")),
        require_elastic_grounding=False,
    )
    if not ok:
        return False, str(err)
    if not isinstance(body, Mapping):
        return False, "query body must be an object"
    return True, None


def extract_hypothesis_elastic_queries(
    analysis_result: dict[str, Any],
    *,
    max_queries: int,
) -> list[dict[str, Any]]:
    """Extract per-hypothesis Elastic query candidates from model output."""

    hypotheses = analysis_result.get("competing_hypotheses", [])
    if not isinstance(hypotheses, list):
        return []
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(hypotheses):
        if not isinstance(item, dict):
            continue
        primary = item.get("primary_elastic_query")
        if not isinstance(primary, Mapping):
            continue
        if not str(primary.get("index_pattern", "")).strip():
            continue
        out.append(
            {
                "hypothesis_index": idx,
                "query_strategy": str(item.get("query_strategy", "")).strip().lower(),
                "primary_query": dict(primary),
                "query": _query_to_compact_text(primary),
                "supports_if": str(item.get("supports_if", "")).strip(),
                "weakens_if": str(item.get("weakens_if", "")).strip(),
            }
        )
        if len(out) >= max_queries:
            break
    return out


def _normalized_request_body(
    primary_query: Mapping[str, Any],
    *,
    config: Config,
    max_rows: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    body = primary_query.get("body", {})
    normalized = deepcopy(body) if isinstance(body, Mapping) else {}
    size = normalized.get("size", max_rows)
    if not isinstance(size, int) or size <= 0 or size > max_rows:
        size = max_rows
    normalized["size"] = size
    fields = sorted(_allowed_fields(config))
    if fields:
        normalized["_source"] = fields
    normalized["timeout"] = f"{timeout_seconds}s"
    normalized["terminate_after"] = max_rows
    return normalized


def _normalize_search_result(
    primary_query: Mapping[str, Any],
    response_json: Mapping[str, Any],
    *,
    allowed_fields: list[str],
) -> dict[str, Any]:
    hits_obj = response_json.get("hits")
    hits: list[Any] = []
    result_count = 0
    if isinstance(hits_obj, Mapping):
        raw_hits = hits_obj.get("hits", [])
        if isinstance(raw_hits, list):
            hits = raw_hits
        total = hits_obj.get("total")
        if isinstance(total, Mapping):
            try:
                result_count = int(total.get("value", len(hits)) or 0)
            except (TypeError, ValueError):
                result_count = len(hits)
        elif isinstance(total, int):
            result_count = total
        else:
            result_count = len(hits)
    sample_rows = _bounded_sample_rows(hits, allowed_fields=allowed_fields)
    sample_columns = sorted(str(k) for k in sample_rows[0].keys()) if sample_rows else []
    index_pattern = str(primary_query.get("index_pattern", "")).strip()
    return {
        "status": "success",
        "executor": "elasticsearch",
        "query": _query_to_compact_text(primary_query),
        "result_count": result_count,
        "sample_columns": sample_columns,
        "sample_rows": sample_rows,
        "raw_result_ref": f"elasticsearch:{index_pattern}",
    }


def execute_elasticsearch_query(
    primary_query: Mapping[str, Any],
    *,
    config: Config,
    api_key: str,
    time_range: str,
    max_rows: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Execute one read-only Elasticsearch `_search` request."""

    query_text = _query_to_compact_text(primary_query)
    allowed, reason = validate_elasticsearch_query_policy(
        primary_query,
        config=config,
        time_range=time_range,
        max_rows=max_rows,
        timeout_seconds=timeout_seconds,
    )
    if not allowed:
        return {"status": "denied", "executor": "elasticsearch", "query": query_text, "message": reason}
    if not config.ELASTICSEARCH_BASE_URL or not api_key:
        return {
            "status": "error",
            "executor": "elasticsearch",
            "query": query_text,
            "message": "Elasticsearch credentials are not configured",
        }

    index_pattern = str(primary_query.get("index_pattern", "")).strip()
    body = _normalized_request_body(
        primary_query,
        config=config,
        max_rows=max_rows,
        timeout_seconds=timeout_seconds,
    )
    encoded_index = quote(index_pattern, safe="*.-_")
    search_url = f"{config.ELASTICSEARCH_BASE_URL.rstrip('/')}/{encoded_index}/_search"
    headers = {"Authorization": f"ApiKey {api_key}", "Content-Type": "application/json"}
    try:
        response = requests.post(
            search_url,
            json=body,
            headers=headers,
            timeout=timeout_seconds,
            verify=True,
        )
        response.raise_for_status()
        response_json = response.json()
        if not isinstance(response_json, Mapping):
            return {
                "status": "error",
                "executor": "elasticsearch",
                "query": query_text,
                "message": "Elasticsearch response must be an object",
            }
        return _normalize_search_result(
            primary_query,
            response_json,
            allowed_fields=_allowed_fields(config),
        )
    except (requests.RequestException, ValueError) as exc:
        return {"status": "error", "executor": "elasticsearch", "query": query_text, "message": str(exc)}


def execute_hypothesis_elasticsearch_queries(
    analysis_result: dict[str, Any],
    *,
    config: Config,
    api_key: str,
) -> list[dict[str, Any]]:
    """Execute bounded hypothesis queries via Elasticsearch `_search`."""

    if not bool(getattr(config, "INVESTIGATION_QUERY_EXECUTION_ENABLED", False)):
        return []
    if str(getattr(config, "INVESTIGATION_QUERY_BACKEND", "")).strip().lower() != "elasticsearch":
        return []

    max_queries = max(1, int(getattr(config, "INVESTIGATION_MAX_QUERIES_PER_ALERT", _DEFAULT_MAX_QUERIES_PER_ALERT)))
    max_concurrent = max(1, int(getattr(config, "INVESTIGATION_MAX_CONCURRENT_QUERIES", _DEFAULT_MAX_CONCURRENT_QUERIES)))
    time_range = str(getattr(config, "ELASTICSEARCH_MAX_TIME_RANGE", _DEFAULT_MAX_TIME_RANGE))
    max_rows = int(getattr(config, "ELASTICSEARCH_MAX_ROWS", _DEFAULT_MAX_ROWS))
    timeout_seconds = int(getattr(config, "ELASTICSEARCH_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS))
    candidates = extract_hypothesis_elastic_queries(analysis_result, max_queries=max_queries)
    if not candidates:
        return []

    indexed_results: list[tuple[int, dict[str, Any]]] = []

    def _run_one(pos: int, item: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        result = execute_elasticsearch_query(
            item.get("primary_query", {}),
            config=config,
            api_key=api_key,
            time_range=time_range,
            max_rows=max_rows,
            timeout_seconds=timeout_seconds,
        )
        result["hypothesis_index"] = item.get("hypothesis_index")
        result["query_strategy"] = item.get("query_strategy", "")
        result["supports_if"] = item.get("supports_if", "")
        result["weakens_if"] = item.get("weakens_if", "")
        return pos, result

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_concurrent, len(candidates))) as pool:
        futures = [pool.submit(_run_one, idx, item) for idx, item in enumerate(candidates)]
        for future in concurrent.futures.as_completed(futures):
            indexed_results.append(future.result())
    indexed_results.sort(key=lambda pair: pair[0])
    return [item for _, item in indexed_results]
