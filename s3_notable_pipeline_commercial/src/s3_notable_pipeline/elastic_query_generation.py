"""Elasticsearch query-generation contract and normalization helpers."""

from __future__ import annotations

import json
import re
from datetime import datetime
from fnmatch import fnmatch
from typing import Any

ELASTIC_QUERY_STRATEGIES = {"resolve_unknown", "check_contradiction"}
ELASTIC_QUERY_FIELDS = (
    "query_strategy",
    "primary_elastic_query",
    "why_this_query",
    "supports_if",
    "weakens_if",
)
ELASTIC_QUERY_GROUNDING_FIELDS = ("primary_elastic_query_grounding_refs",)

_PLACEHOLDER_RE = re.compile(r"<[^>]+>|\.\.\.")
_GROUNDING_LINE_RE = re.compile(
    r"^\[\d+\]\s+\[(?P<source>.*?)\s+::\s+(?P<section>.*?)\]\s+(?P<excerpt>.*)$"
)
_DURATION_RE = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.IGNORECASE)
_NOW_MATH_RE = re.compile(r"^now(?:-(\d+)([smhd]))?$", re.IGNORECASE)
_INDEX_FORBIDDEN_CHARS = {",", "/", "\\", "?", "#"}
_DENIED_DSL_KEYS = {
    "aggs",
    "aggregations",
    "highlight",
    "query_string",
    "runtime_mappings",
    "script",
    "script_fields",
    "simple_query_string",
    "wildcard",
}
_FIELD_QUERY_KEYS = {"term", "terms", "match", "match_phrase", "range", "prefix"}

ELASTIC_QUERY_GENERATION_RULES = """
ELASTICSEARCH QUERY GENERATION (Enabled):
- Generated Elasticsearch Query DSL is unvalidated draft investigation guidance.
  Do not claim the query was executed or that results were observed.
- For each input hypothesis, include exactly one primary Elasticsearch Query DSL request.
- Each hypothesis must include:
  - query_strategy: "resolve_unknown" or "check_contradiction"
  - primary_elastic_query: an object with index_pattern and body
  - why_this_query: short rationale
  - supports_if: result pattern that strengthens the hypothesis
  - weakens_if: result pattern that weakens the hypothesis
- Each query must name the hypothesis uncertainty it is testing and use exact alert
  fields or values where available.
- primary_elastic_query.index_pattern must name exactly one target Elastic index or
  index pattern. Respect wildcard policy and do not emit comma-separated multi-index
  strings.
- primary_elastic_query.body must be an Elasticsearch _search body.
- Do not use placeholders such as <INDEX>, <FIELD>, or similar tokens.
- Do not output pseudo-queries or prose.
- Do not invent index patterns, ECS/vendor dotted fields, or timestamp fields. Use only
  fields and indexes from SECURITY ALERT INPUT or ELASTICSEARCH_GROUNDING_CONTEXT.
- Keep each search read-only, bounded, and decision-oriented.
- Use only read-only Elasticsearch _search Query DSL. Do not generate KQL, Lucene,
  ES|QL, SQL, Kibana API calls, or prose queries.
- Prefer bool.filter, must_not, term, terms, exists, and range clauses for evidence
  filtering. Avoid relevance-scoring patterns; security hunts should be decision
  filters, not text-ranking searches.
- Use only bounded _search Query DSL. Do not use aggregations, query_string,
  simple_query_string, regex, wildcard clauses, scripts, highlighting, or runtime mappings.
- When ALERT_TIME is provided, build a bounded range filter around it on the configured
  timestamp field. Otherwise stay within ELASTICSEARCH_MAX_TIME_RANGE.
- Every query must include a lower and upper bound range filter on the configured
  timestamp field.
""".strip()

ELASTIC_QUERY_CONTEXT_RULES = """
ELASTICSEARCH QUERY CONTEXT RULES:
- Treat SOC_OPERATIONAL_CONTEXT as advisory context only.
- Treat ELASTICSEARCH_GROUNDING_CONTEXT as advisory Elastic-environment context only.
- Never treat SOC_OPERATIONAL_CONTEXT as direct alert evidence.
- Do not use index patterns or field names unless they appear in SECURITY ALERT INPUT or ELASTICSEARCH_GROUNDING_CONTEXT.
- SOC_OPERATIONAL_CONTEXT may explain analyst process, but it does not authorize environment-specific Elastic tokens.
""".strip()

ELASTIC_QUERY_OUTPUT_SCHEMA = """
Return ONLY a single JSON object with this shape:
{
  "competing_hypotheses": [
    {
      "query_strategy": "resolve_unknown|check_contradiction",
      "primary_elastic_query": {"index_pattern": "logs-*", "body": {"size": 25, "query": {"bool": {"filter": []}}}},
      "why_this_query": "string",
      "supports_if": "string",
      "weakens_if": "string"
    }
  ]
}
""".strip()


def duration_to_seconds(value: str) -> int | None:
    """Parse a compact duration such as `24h` into seconds."""

    match = _DURATION_RE.match(str(value or ""))
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    return amount * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def build_elastic_query_generation_prompt(
    *,
    alert_text: str,
    hypotheses: list[dict[str, Any]],
    soc_operational_context: str = "",
    elasticsearch_grounding_context: str = "",
    alert_time: str | None = None,
) -> str:
    """Build a bounded second-call prompt for Elastic query generation only."""

    alert_time_str = f"\n**ALERT_TIME:** {alert_time}\n" if alert_time else ""
    soc_context_block = (soc_operational_context or "").strip() or "SOC_OPERATIONAL_CONTEXT\n(none)\n"
    elastic_grounding_block = (
        (elasticsearch_grounding_context or "").strip()
        or "ELASTICSEARCH_GROUNDING_CONTEXT\n(none)\n"
    )
    hypotheses_block = json.dumps(hypotheses, indent=2, ensure_ascii=True)
    return f"""You are a cybersecurity investigation assistant generating Elasticsearch Query DSL for predefined hypotheses.
{alert_time_str}
---

SECURITY ALERT INPUT:
{alert_text}

---

INPUT_COMPETING_HYPOTHESES (ordered):
{hypotheses_block}

---

{soc_context_block}

---

{elastic_grounding_block}

---

{ELASTIC_QUERY_CONTEXT_RULES}

---

{ELASTIC_QUERY_GENERATION_RULES}

---

{ELASTIC_QUERY_OUTPUT_SCHEMA}
"""


def _clean_primary_query(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    if not isinstance(value, dict):
        return {}
    index_pattern = str(value.get("index_pattern", "")).strip()
    body = value.get("body", {})
    out: dict[str, Any] = {}
    if index_pattern:
        out["index_pattern"] = index_pattern
    if isinstance(body, dict) and body:
        out["body"] = body
    return out


def normalize_competing_hypotheses(
    value: Any,
    *,
    elastic_query_enabled: bool,
) -> list[dict[str, Any]]:
    """Normalize hypotheses and optionally strip Elastic query fields."""

    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        out = dict(item)
        if not elastic_query_enabled:
            for field in ("primary_elastic_query", *ELASTIC_QUERY_GROUNDING_FIELDS):
                out.pop(field, None)
            normalized.append(out)
            continue
        out["query_strategy"] = str(out.get("query_strategy", "")).strip().lower()
        out["primary_elastic_query"] = _clean_primary_query(out.get("primary_elastic_query", {}))
        for field in ("why_this_query", "supports_if", "weakens_if"):
            out[field] = str(out.get(field, "")).strip()
        normalized.append(out)
    return normalized


def merge_elastic_query_fields_by_position(
    *,
    base_hypotheses: list[dict[str, Any]],
    generated_payload: dict[str, Any],
    elasticsearch_grounding_context: str = "",
) -> list[dict[str, Any]]:
    """Merge generated Elastic query fields onto baseline hypotheses by order."""

    base = normalize_competing_hypotheses(base_hypotheses, elastic_query_enabled=False)
    generated = generated_payload.get("competing_hypotheses", [])
    if not isinstance(generated, list):
        generated = []
    merged: list[dict[str, Any]] = []
    for idx, item in enumerate(base):
        merged_item = dict(item)
        generated_item = generated[idx] if idx < len(generated) else {}
        if isinstance(generated_item, dict):
            for field in ELASTIC_QUERY_FIELDS:
                if field in generated_item:
                    merged_item[field] = generated_item.get(field)
            refs = build_elastic_query_grounding_refs(
                _clean_primary_query(merged_item.get("primary_elastic_query", {})),
                elasticsearch_grounding_context,
            )
            if refs:
                merged_item["primary_elastic_query_grounding_refs"] = refs
        merged.append(merged_item)
    return normalize_competing_hypotheses(merged, elastic_query_enabled=True)


def _csv_to_set(value: str) -> set[str]:
    return {part.strip().casefold() for part in (value or "").split(",") if part.strip()}


def _csv_to_list(value: str) -> list[str]:
    return [part.strip().casefold() for part in (value or "").split(",") if part.strip()]


def _token_present(token: str, text: str) -> bool:
    clean = (token or "").strip().casefold()
    return bool(clean and clean in (text or "").casefold())


def _token_allowed(token: str, *, alert_text: str, grounding_context: str) -> bool:
    return _token_present(token, alert_text) or _token_present(token, grounding_context)


def _walk(obj: Any) -> list[Any]:
    out = [obj]
    if isinstance(obj, dict):
        for value in obj.values():
            out.extend(_walk(value))
    elif isinstance(obj, list):
        for value in obj:
            out.extend(_walk(value))
    return out


def _has_denied_dsl_key(obj: Any) -> str | None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            clean = str(key).strip().lower()
            if clean in _DENIED_DSL_KEYS:
                return clean
            nested = _has_denied_dsl_key(value)
            if nested:
                return nested
    elif isinstance(obj, list):
        for value in obj:
            nested = _has_denied_dsl_key(value)
            if nested:
                return nested
    return None


def _extract_fields(obj: Any) -> set[str]:
    fields: set[str] = set()
    if isinstance(obj, dict):
        if "exists" in obj and isinstance(obj["exists"], dict):
            field = str(obj["exists"].get("field", "")).strip()
            if field:
                fields.add(field)
        for key, value in obj.items():
            clean_key = str(key)
            if clean_key in _FIELD_QUERY_KEYS and isinstance(value, dict):
                for field in value.keys():
                    fields.add(str(field).strip())
            elif clean_key in {"sort", "fields", "_source"}:
                fields.update(_extract_sort_or_field_list(value))
            else:
                fields.update(_extract_fields(value))
    elif isinstance(obj, list):
        for value in obj:
            fields.update(_extract_fields(value))
    return {field for field in fields if field}


def _extract_sort_or_field_list(value: Any) -> set[str]:
    fields: set[str] = set()
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                fields.add(item)
            elif isinstance(item, dict):
                fields.update(str(key) for key in item.keys())
    elif isinstance(value, str):
        fields.add(value)
    elif isinstance(value, dict):
        fields.update(str(key) for key in value.keys())
    return fields


def _now_math_lookback_seconds(value: Any) -> int | None:
    match = _NOW_MATH_RE.match(str(value or "").strip())
    if not match:
        return None
    amount = match.group(1)
    unit = match.group(2)
    if amount is None or unit is None:
        return 0
    return duration_to_seconds(f"{amount}{unit}")


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _validate_timestamp_range(
    body: dict[str, Any],
    *,
    timestamp_field: str,
    max_time_range: str,
) -> tuple[bool, str | None]:
    ranges: list[dict[str, Any]] = []
    for item in _walk(body):
        if not isinstance(item, dict):
            continue
        range_obj = item.get("range")
        if isinstance(range_obj, dict) and isinstance(range_obj.get(timestamp_field), dict):
            ranges.append(range_obj[timestamp_field])
    if not ranges:
        return False, f"primary_elastic_query.body must include range on {timestamp_field}"
    max_seconds = duration_to_seconds(max_time_range)
    if max_seconds is None:
        return False, "ELASTICSEARCH_MAX_TIME_RANGE has invalid format"
    for time_bounds in ranges:
        lower = time_bounds.get("gte", time_bounds.get("gt", time_bounds.get("from")))
        upper = time_bounds.get("lte", time_bounds.get("lt", time_bounds.get("to")))
        if lower is None or upper is None:
            return False, "timestamp range must include lower and upper bounds"
        lower_lookback = _now_math_lookback_seconds(lower)
        upper_lookback = _now_math_lookback_seconds(upper)
        if lower_lookback is not None and upper_lookback is not None:
            if lower_lookback < upper_lookback:
                return False, "timestamp lower bound must be before upper bound"
            if lower_lookback - upper_lookback > max_seconds:
                return False, "timestamp range exceeds configured max"
            continue
        lower_dt = _parse_datetime(lower)
        upper_dt = _parse_datetime(upper)
        if lower_dt and upper_dt:
            if upper_dt < lower_dt:
                return False, "timestamp lower bound must be before upper bound"
            if (upper_dt - lower_dt).total_seconds() > max_seconds:
                return False, "timestamp range exceeds configured max"
            continue
        return False, "timestamp range uses unsupported date format"
    return True, None


def _validate_index_pattern(
    index_pattern: str,
    *,
    allowed_index_patterns: str,
    allow_wildcard_indexes: bool,
    require_elastic_grounding: bool,
    alert_text: str,
    elasticsearch_grounding_context: str,
) -> tuple[bool, str | None]:
    clean = str(index_pattern or "").strip()
    if not clean:
        return False, "primary_elastic_query.index_pattern is required"
    if _PLACEHOLDER_RE.search(clean):
        return False, "primary_elastic_query.index_pattern contains placeholder text"
    if any(char in clean for char in _INDEX_FORBIDDEN_CHARS):
        return False, "primary_elastic_query.index_pattern contains a denied delimiter"
    if "*" in clean and not allow_wildcard_indexes:
        return False, "wildcard index patterns are disabled"
    allowed_patterns = _csv_to_list(allowed_index_patterns)
    if allowed_patterns and not any(fnmatch(clean.casefold(), pattern) for pattern in allowed_patterns):
        return False, "primary_elastic_query.index_pattern is not allowlisted"
    if require_elastic_grounding and not _token_allowed(
        clean,
        alert_text=alert_text,
        grounding_context=elasticsearch_grounding_context,
    ):
        return False, f"ungrounded index pattern: {clean}"
    return True, None


def build_elastic_query_grounding_refs(
    primary_elastic_query: dict[str, Any],
    elasticsearch_grounding_context: str,
) -> list[dict[str, str]]:
    """Return source refs from Elastic grounding snippets used by the query."""

    index_pattern = str(primary_elastic_query.get("index_pattern", "")).strip()
    fields = _extract_fields(primary_elastic_query.get("body", {}))
    tokens = [token for token in [index_pattern, *sorted(fields)] if token]
    if not tokens or not elasticsearch_grounding_context:
        return []
    refs: list[dict[str, str]] = []
    seen = set()
    for raw_line in elasticsearch_grounding_context.splitlines():
        match = _GROUNDING_LINE_RE.match(raw_line.strip())
        if not match or not any(_token_present(token, raw_line) for token in tokens):
            continue
        ref = {
            "source_file": (match.group("source") or "unknown_source").strip(),
            "section_path": (match.group("section") or "root").strip(),
        }
        key = (ref["source_file"], ref["section_path"])
        if key not in seen:
            refs.append(ref)
            seen.add(key)
    return refs


def validate_elastic_query_contract(
    result: dict[str, Any],
    *,
    alert_text: str = "",
    elasticsearch_grounding_context: str = "",
    allowed_fields: str = "",
    allowed_index_patterns: str = "",
    allow_wildcard_indexes: bool = False,
    max_rows: int = 100,
    max_time_range: str = "24h",
    timestamp_field: str = "@timestamp",
    require_elastic_grounding: bool = False,
    expected_hypothesis_count: int | None = 6,
) -> tuple[bool, str | None]:
    """Validate strict Elastic query contract for per-hypothesis generation."""

    hypotheses = result.get("competing_hypotheses", [])
    if not isinstance(hypotheses, list):
        return False, "competing_hypotheses must be a list"
    if expected_hypothesis_count is not None and len(hypotheses) != expected_hypothesis_count:
        return False, (
            f"competing_hypotheses must contain exactly {expected_hypothesis_count} items, "
            f"got {len(hypotheses)}"
        )

    allowed = _csv_to_set(allowed_fields)
    for i, item in enumerate(hypotheses):
        if not isinstance(item, dict):
            return False, f"competing_hypotheses[{i}] must be an object"
        if str(item.get("query_strategy", "")).strip().lower() not in ELASTIC_QUERY_STRATEGIES:
            return False, f"competing_hypotheses[{i}].query_strategy is invalid"
        for field in ("why_this_query", "supports_if", "weakens_if"):
            if not str(item.get(field, "")).strip():
                return False, f"competing_hypotheses[{i}].{field} is required"
        primary = _clean_primary_query(item.get("primary_elastic_query"))
        index_pattern = str(primary.get("index_pattern", "")).strip()
        body = primary.get("body", {})
        index_ok, index_err = _validate_index_pattern(
            index_pattern,
            allowed_index_patterns=allowed_index_patterns,
            allow_wildcard_indexes=allow_wildcard_indexes,
            require_elastic_grounding=require_elastic_grounding,
            alert_text=alert_text,
            elasticsearch_grounding_context=elasticsearch_grounding_context,
        )
        if not index_ok:
            return False, f"competing_hypotheses[{i}]: {index_err}"
        if not isinstance(body, dict) or not body:
            return False, f"competing_hypotheses[{i}]: primary_elastic_query.body must be a non-empty object"
        body_text = json.dumps(body, ensure_ascii=True, sort_keys=True)
        if _PLACEHOLDER_RE.search(body_text):
            return False, f"competing_hypotheses[{i}]: primary_elastic_query.body contains placeholder text"
        denied_key = _has_denied_dsl_key(body)
        if denied_key:
            return False, f"competing_hypotheses[{i}]: primary_elastic_query.body contains denied DSL key: {denied_key}"
        size = body.get("size", max_rows)
        if not isinstance(size, int) or size <= 0 or size > max_rows:
            return False, f"competing_hypotheses[{i}]: primary_elastic_query.body.size exceeds configured max"
        if "query" not in body or not isinstance(body["query"], dict):
            return False, f"competing_hypotheses[{i}]: primary_elastic_query.body.query must be an object"
        time_ok, time_err = _validate_timestamp_range(
            body,
            timestamp_field=timestamp_field,
            max_time_range=max_time_range,
        )
        if not time_ok:
            return False, f"competing_hypotheses[{i}]: {time_err}"
        if not allowed and not require_elastic_grounding:
            return False, "ELASTICSEARCH_ALLOWED_FIELDS must contain at least one field"
        for field in sorted(_extract_fields(body)):
            if field == timestamp_field:
                continue
            if allowed and field.casefold() in allowed:
                continue
            if _token_allowed(field, alert_text=alert_text, grounding_context=elasticsearch_grounding_context):
                continue
            return False, f"competing_hypotheses[{i}]: ungrounded or non-allowlisted field: {field}"
    return True, None
