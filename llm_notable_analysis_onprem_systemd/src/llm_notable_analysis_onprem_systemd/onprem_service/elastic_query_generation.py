"""Elasticsearch query-generation contract and normalization helpers.

This module mirrors the SPL query-generation path with an Elastic-specific
Query DSL contract for read-only `_search` requests.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple

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
_DENIED_DSL_KEYS = {
    "script",
    "script_fields",
    "runtime_mappings",
    "update",
    "delete",
    "pipeline",
}
_FIELD_QUERY_KEYS = {
    "term",
    "terms",
    "match",
    "match_phrase",
    "range",
    "wildcard",
    "prefix",
    "regexp",
}

ELASTIC_QUERY_GENERATION_RULES = """
ELASTICSEARCH QUERY GENERATION (Enabled):
- For each of the EXACTLY 6 hypotheses, include exactly one primary Elasticsearch Query DSL request.
- Each hypothesis must include:
  - query_strategy: "resolve_unknown" or "check_contradiction"
  - primary_elastic_query: an object with index_pattern and body
  - why_this_query: short rationale
  - supports_if: result pattern that strengthens the hypothesis
  - weakens_if: result pattern that weakens the hypothesis
- primary_elastic_query.index_pattern must name the target Elastic index or index pattern.
- primary_elastic_query.body must be an Elasticsearch _search body.
- Do not use placeholders such as <INDEX>, <FIELD>, or similar tokens.
- Do not output pseudo-queries or prose.
- Do not invent environment-specific index patterns or field names unless explicitly present in SECURITY ALERT INPUT or ELASTICSEARCH_GROUNDING_CONTEXT.
- Keep each search read-only, bounded, and decision-oriented.
""".strip()

ELASTIC_QUERY_CONTEXT_RULES = """
ELASTICSEARCH QUERY CONTEXT RULES:
- Treat SOC_OPERATIONAL_CONTEXT as advisory context only.
- Treat ELASTICSEARCH_GROUNDING_CONTEXT as advisory Elastic-environment context only.
- Never treat SOC_OPERATIONAL_CONTEXT as direct alert evidence.
- Do not use index patterns or field names unless they appear in SECURITY ALERT INPUT or ELASTICSEARCH_GROUNDING_CONTEXT.
- SOC_OPERATIONAL_CONTEXT may explain analyst process, but it does not authorize environment-specific Elastic tokens.
- Use Elasticsearch Query DSL for _search only, not KQL, ES|QL, SQL, or Kibana APIs.
""".strip()

ELASTIC_QUERY_OUTPUT_SCHEMA = """
Return ONLY a single JSON object with this shape:
{
  "competing_hypotheses": [
    {
      "query_strategy": "resolve_unknown|check_contradiction",
      "primary_elastic_query": {
        "index_pattern": "logs-*",
        "body": {
          "size": 25,
          "query": {
            "bool": {
              "filter": []
            }
          }
        }
      },
      "why_this_query": "string",
      "supports_if": "string",
      "weakens_if": "string"
    }
  ]
}

Requirements:
- Output exactly 6 items in competing_hypotheses.
- Keep the same order as INPUT_COMPETING_HYPOTHESES.
- Include only the query fields above per hypothesis item.
- Do not include markdown fences or extra prose.
""".strip()


def build_elastic_query_generation_prompt(
    *,
    alert_text: str,
    hypotheses: List[Dict[str, Any]],
    soc_operational_context: str = "",
    elasticsearch_grounding_context: str = "",
    alert_time: Optional[str] = None,
) -> str:
    """Build a bounded second-call prompt for Elastic query generation only."""
    alert_time_str = f"\n**ALERT_TIME:** {alert_time}\n" if alert_time else ""
    soc_context_block = (soc_operational_context or "").strip()
    if not soc_context_block:
        soc_context_block = "SOC_OPERATIONAL_CONTEXT\n(none)\n"
    elastic_grounding_block = (elasticsearch_grounding_context or "").strip()
    if not elastic_grounding_block:
        elastic_grounding_block = "ELASTICSEARCH_GROUNDING_CONTEXT\n(none)\n"

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

{ELASTIC_QUERY_CONTEXT_RULES}

---

{ELASTIC_QUERY_GENERATION_RULES}

---

{ELASTIC_QUERY_OUTPUT_SCHEMA}
"""


def _clean_query_body(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clean_primary_query(value: Any) -> Dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    if not isinstance(value, dict):
        return {}
    index_pattern = str(value.get("index_pattern", "")).strip()
    body = _clean_query_body(value.get("body", {}))
    out: Dict[str, Any] = {}
    if index_pattern:
        out["index_pattern"] = index_pattern
    if body:
        out["body"] = body
    return out


def normalize_competing_hypotheses(
    value: Any, *, elastic_query_enabled: bool
) -> List[Dict[str, Any]]:
    """Normalize hypotheses and optionally strip Elastic query fields."""
    if not isinstance(value, list):
        return []
    normalized: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        out = dict(item)
        if not elastic_query_enabled:
            for field in ("primary_elastic_query",) + ELASTIC_QUERY_GROUNDING_FIELDS:
                out.pop(field, None)
            normalized.append(out)
            continue
        out["query_strategy"] = str(out.get("query_strategy", "")).strip().lower()
        out["primary_elastic_query"] = _clean_primary_query(
            out.get("primary_elastic_query", {})
        )
        for field in ("why_this_query", "supports_if", "weakens_if"):
            out[field] = str(out.get(field, "")).strip()
        normalized.append(out)
    return normalized


def merge_elastic_query_fields_by_position(
    *,
    base_hypotheses: List[Dict[str, Any]],
    generated_payload: Dict[str, Any],
    elasticsearch_grounding_context: str = "",
) -> List[Dict[str, Any]]:
    """Merge generated Elastic query fields onto baseline hypotheses by order."""
    base = normalize_competing_hypotheses(base_hypotheses, elastic_query_enabled=False)
    generated = generated_payload.get("competing_hypotheses", [])
    if not isinstance(generated, list):
        generated = []

    merged: List[Dict[str, Any]] = []
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


def _token_present(token: str, text: str) -> bool:
    clean = (token or "").strip().casefold()
    if not clean:
        return False
    return clean in (text or "").casefold()


def _csv_to_set(value: str) -> Set[str]:
    return {part.strip().casefold() for part in (value or "").split(",") if part.strip()}


def _walk(obj: Any) -> List[Any]:
    out = [obj]
    if isinstance(obj, dict):
        for value in obj.values():
            out.extend(_walk(value))
    elif isinstance(obj, list):
        for value in obj:
            out.extend(_walk(value))
    return out


def _has_denied_dsl_key(obj: Any) -> Optional[str]:
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


def _extract_fields(obj: Any) -> Set[str]:
    fields: Set[str] = set()
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


def _extract_sort_or_field_list(value: Any) -> Set[str]:
    fields: Set[str] = set()
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                fields.add(item)
            elif isinstance(item, dict):
                for key in item.keys():
                    fields.add(str(key))
    elif isinstance(value, str):
        fields.add(value)
    elif isinstance(value, dict):
        for key in value.keys():
            fields.add(str(key))
    return fields


def _has_time_filter(body: Dict[str, Any], timestamp_field: str) -> bool:
    for item in _walk(body):
        if not isinstance(item, dict):
            continue
        range_obj = item.get("range")
        if isinstance(range_obj, dict) and timestamp_field in range_obj:
            time_bounds = range_obj.get(timestamp_field)
            if isinstance(time_bounds, dict) and any(
                key in time_bounds for key in ("gte", "gt", "from")
            ):
                return True
    return False


def build_elastic_query_grounding_refs(
    primary_elastic_query: Dict[str, Any],
    elasticsearch_grounding_context: str,
) -> List[Dict[str, str]]:
    """Return source refs from Elastic grounding snippets used by the query."""
    index_pattern = str(primary_elastic_query.get("index_pattern", "")).strip()
    fields = _extract_fields(primary_elastic_query.get("body", {}))
    tokens = [index_pattern] + sorted(fields)
    tokens = [token for token in tokens if token]
    if not tokens or not elasticsearch_grounding_context:
        return []

    refs: List[Dict[str, str]] = []
    seen = set()
    for raw_line in elasticsearch_grounding_context.splitlines():
        match = _GROUNDING_LINE_RE.match(raw_line.strip())
        if not match:
            continue
        line_text = raw_line.casefold()
        if not any(_token_present(token, line_text) for token in tokens):
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


def _token_allowed(token: str, *, alert_text: str, grounding_context: str) -> bool:
    return _token_present(token, alert_text) or _token_present(token, grounding_context)


def _validate_one_primary_query(
    query_obj: Any,
    *,
    alert_text: str,
    elasticsearch_grounding_context: str,
    allowed_fields: str,
    allow_wildcard_indexes: bool,
    max_rows: int,
    timestamp_field: str,
    require_elastic_grounding: bool,
) -> Tuple[bool, Optional[str]]:
    primary = _clean_primary_query(query_obj)
    index_pattern = str(primary.get("index_pattern", "")).strip()
    body = primary.get("body", {})
    if not index_pattern:
        return False, "primary_elastic_query.index_pattern is required"
    if _PLACEHOLDER_RE.search(index_pattern):
        return False, "primary_elastic_query.index_pattern contains placeholder text"
    if "*" in index_pattern and not allow_wildcard_indexes:
        return False, "wildcard index patterns are disabled"
    if require_elastic_grounding and not _token_allowed(
        index_pattern,
        alert_text=alert_text,
        grounding_context=elasticsearch_grounding_context,
    ):
        return False, f"ungrounded index pattern: {index_pattern}"
    if not isinstance(body, dict) or not body:
        return False, "primary_elastic_query.body must be a non-empty object"
    body_text = json.dumps(body, ensure_ascii=True, sort_keys=True)
    if _PLACEHOLDER_RE.search(body_text):
        return False, "primary_elastic_query.body contains placeholder text"
    denied_key = _has_denied_dsl_key(body)
    if denied_key:
        return False, f"primary_elastic_query.body contains denied DSL key: {denied_key}"
    size = body.get("size", max_rows)
    if not isinstance(size, int) or size <= 0 or size > max_rows:
        return False, "primary_elastic_query.body.size exceeds configured max"
    if "query" not in body or not isinstance(body["query"], dict):
        return False, "primary_elastic_query.body.query must be an object"
    if timestamp_field and not _has_time_filter(body, timestamp_field):
        return False, f"primary_elastic_query.body must include range on {timestamp_field}"

    allowed = _csv_to_set(allowed_fields)
    for field in sorted(_extract_fields(body)):
        if field == timestamp_field:
            continue
        if allowed and field.casefold() in allowed:
            continue
        if not allowed and not require_elastic_grounding:
            continue
        if _token_allowed(
            field,
            alert_text=alert_text,
            grounding_context=elasticsearch_grounding_context,
        ):
            continue
        return False, f"ungrounded or non-allowlisted field: {field}"
    return True, None


def validate_elastic_query_contract(
    result: Dict[str, Any],
    *,
    alert_text: str = "",
    elasticsearch_grounding_context: str = "",
    allowed_fields: str = "",
    allow_wildcard_indexes: bool = False,
    max_rows: int = 100,
    timestamp_field: str = "@timestamp",
    require_elastic_grounding: bool = False,
) -> Tuple[bool, Optional[str]]:
    """Validate strict Elastic query contract for per-hypothesis generation."""
    hypotheses = result.get("competing_hypotheses", [])
    if not isinstance(hypotheses, list):
        return False, "competing_hypotheses must be a list"
    if len(hypotheses) != 6:
        return False, f"competing_hypotheses must contain exactly 6 items, got {len(hypotheses)}"

    for i, item in enumerate(hypotheses):
        if not isinstance(item, dict):
            return False, f"competing_hypotheses[{i}] must be an object"
        strategy = str(item.get("query_strategy", "")).strip().lower()
        if strategy not in ELASTIC_QUERY_STRATEGIES:
            return False, f"competing_hypotheses[{i}].query_strategy is invalid"
        for field in ("why_this_query", "supports_if", "weakens_if"):
            if not str(item.get(field, "")).strip():
                return False, f"competing_hypotheses[{i}].{field} is required"
        ok, err = _validate_one_primary_query(
            item.get("primary_elastic_query"),
            alert_text=alert_text,
            elasticsearch_grounding_context=elasticsearch_grounding_context,
            allowed_fields=allowed_fields,
            allow_wildcard_indexes=allow_wildcard_indexes,
            max_rows=max_rows,
            timestamp_field=timestamp_field,
            require_elastic_grounding=require_elastic_grounding,
        )
        if not ok:
            return False, f"competing_hypotheses[{i}]: {err}"
    return True, None
