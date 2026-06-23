"""Deterministic case-aware Knowledge Base query construction for portal chat."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from .case_chat import RetrievedSource

_CASE_AWARE_KB_QUERY_MAX_CONTEXT_CHARS = 800

_FQDN_RE = re.compile(
    r"\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)+\b",
    re.IGNORECASE,
)
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_DOMAIN_USER_RE = re.compile(r"\b[a-z0-9_-]+\\[a-z0-9_.$-]+\b", re.IGNORECASE)
_KV_FACT_RE = re.compile(
    r"\b(dest_host|src_host|user|host|dest|src|alert_type|search_name)=([^\s,;]+)",
    re.IGNORECASE,
)


def build_case_aware_kb_query(
    question: str,
    *,
    case_sources: Sequence["RetrievedSource"] | None = None,
    selected_case_id: str | None = None,
    max_context_chars: int = _CASE_AWARE_KB_QUERY_MAX_CONTEXT_CHARS,
) -> str:
    """Build a bounded KB retrieval query from the question and case context."""
    normalized_question = str(question or "").strip()
    if not normalized_question:
        return ""

    context_lines: list[str] = []
    seen: set[str] = set()

    def _append(line: str) -> None:
        candidate = line.strip()
        if not candidate:
            return
        key = candidate.lower()
        if key in seen:
            return
        seen.add(key)
        context_lines.append(candidate)

    case_id = str(selected_case_id or "").strip()
    if case_id:
        _append(f"selected_case_id={case_id}")

    case_text_parts: list[str] = []
    for source in case_sources or ():
        if str(source.source_lane or "").strip() != "current_case":
            continue
        text = str(source.text or "").strip()
        if text:
            case_text_parts.append(text)

    combined_case_text = "\n".join(case_text_parts)
    if combined_case_text:
        for match in _KV_FACT_RE.finditer(combined_case_text):
            _append(f"{match.group(1).lower()}={match.group(2)}")
        for pattern in (_FQDN_RE, _IPV4_RE, _DOMAIN_USER_RE):
            for match in pattern.finditer(combined_case_text):
                value = match.group(0)
                _append(value)
                if pattern is _FQDN_RE and "." in value:
                    short_host = value.split(".", 1)[0]
                    if short_host:
                        _append(short_host)

    if not context_lines:
        return normalized_question

    context_block = "\n".join(context_lines)
    if len(context_block) > max(0, max_context_chars):
        context_block = context_block[:max_context_chars].rstrip()

    return f"{normalized_question}\n{context_block}".strip()
