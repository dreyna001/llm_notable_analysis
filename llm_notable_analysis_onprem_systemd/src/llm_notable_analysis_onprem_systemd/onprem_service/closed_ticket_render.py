"""Deterministic rendering and chunking for closed ServiceNow ticket payloads."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Sequence

from .config import Config

_SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9_-]+")
_MAX_JSON_DEPTH = 40
_TARGET_CHUNK_CHARS = 2800
_MIN_CHUNK_CHARS = 2000
_MAX_CHUNK_CHARS = 3200
_CHUNK_OVERLAP_CHARS = 250
_MAX_LEAVES_PER_SECTION = 500
_MAX_INDEX_CHUNKS_DEFAULT = 120

_SUMMARY_LEAF_LIMIT = 48


@dataclass(frozen=True)
class ClosedTicketRecord:
    """One closed ticket row used for rendering and indexing."""

    ticket_id: str
    ticket_number: str | None
    source_table: str | None
    source_url: str | None
    state: str | None
    is_active: bool
    closed_at: datetime | None
    source_updated_at: datetime | None
    raw_payload: Any
    journals_payload: Any
    expires_at: datetime | None
    content_hash: str | None = None


@dataclass(frozen=True)
class ClosedTicketAttachmentRecord:
    """Attachment metadata linked to one closed ticket."""

    attachment_id: str
    ticket_id: str
    filename: str | None
    content_type: str | None
    metadata: dict[str, Any]
    semantic_text: str | None = None
    extraction_status: str | None = None


@dataclass(frozen=True)
class ClosedTicketChunkRecord:
    """A deterministic retrieval chunk for one closed ticket."""

    chunk_id: str
    ticket_id: str
    ordinal: int
    section: str
    field_path: str
    text: str
    metadata: dict[str, Any]
    chunk_schema_version: int
    embedding_model: str


def _config_int(config: Config, name: str, default: int) -> int:
    return max(1, int(getattr(config, name, default)))


def closed_ticket_embedding_model(config: Config) -> str:
    """Resolve the embedding model name for closed-ticket chunks."""
    for key in (
        "CLOSED_TICKET_EMBEDDING_MODEL",
        "RAG_EMBEDDING_MODEL",
        "CASE_QA_EMBEDDING_MODEL",
    ):
        value = getattr(config, key, None)
        if value:
            return str(value).strip()
    return "mixedbread-ai/mxbai-embed-large-v1"


def closed_ticket_chunk_schema_version(config: Config) -> int:
    """Resolve chunk schema version for closed-ticket chunks."""
    return _config_int(config, "CLOSED_TICKET_CHUNK_SCHEMA_VERSION", 1)


def _safe_component(value: str) -> str:
    raw = str(value)
    sanitized = _SAFE_COMPONENT_RE.sub("_", raw).strip("_")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    if not sanitized:
        return f"unknown_{digest}"
    if sanitized != raw or len(sanitized) > 100:
        return f"{sanitized[:87]}_{digest}"
    return sanitized


def build_closed_ticket_chunk_id(
    *, ticket_id: str, section: str, ordinal: int
) -> str:
    """Build a stable chunk id for one ticket section ordinal."""
    return ":".join(
        (
            _safe_component(ticket_id),
            _safe_component(section),
            str(int(ordinal)),
        )
    )


def _field_path_join(base_path: str, key: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        return f"{base_path}.{key}"
    escaped = key.replace("\\", "\\\\").replace("'", "\\'")
    return f"{base_path}['{escaped}']"


def _scalar_render_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _iter_leaf_values(
    value: Any, path: str = "$", *, depth: int = 0
) -> Iterable[tuple[str, Any]]:
    """Yield deterministic leaf scalar values from nested JSON-like data."""
    if depth >= _MAX_JSON_DEPTH:
        yield path, "[max JSON depth reached]"
        return
    if isinstance(value, dict):
        keys = sorted(value)
        if set(keys) <= {"display_value", "value", "link"} and (
            "display_value" in value or "value" in value
        ):
            for key in sorted(k for k in keys if k in {"display_value", "value"}):
                leaf_path = _field_path_join(path, key)
                leaf_value = value.get(key)
                if isinstance(leaf_value, (dict, list)):
                    yield from _iter_leaf_values(
                        leaf_value, leaf_path, depth=depth + 1
                    )
                else:
                    yield leaf_path, leaf_value
            return
        for key in keys:
            yield from _iter_leaf_values(
                value[key],
                _field_path_join(path, str(key)),
                depth=depth + 1,
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _iter_leaf_values(item, f"{path}[{index}]", depth=depth + 1)
    else:
        yield path, value


def _leaf_lines(value: Any, root_path: str = "$") -> list[tuple[str, str]]:
    """Collect bounded leaf path/value lines for one JSON subtree."""
    lines: list[tuple[str, str]] = []
    for path, raw in _iter_leaf_values(value, root_path):
        rendered = _scalar_render_value(raw)
        if not rendered:
            continue
        lines.append((path, f"{path}: {rendered}"))
        if len(lines) >= _MAX_LEAVES_PER_SECTION:
            break
    return lines


def _chunk_char_budget() -> int:
    return min(_MAX_CHUNK_CHARS, max(_MIN_CHUNK_CHARS, _TARGET_CHUNK_CHARS))


def _split_with_overlap(text: str) -> list[str]:
    """Split large text into overlapping chunks with deterministic boundaries."""
    normalized = text.strip()
    if not normalized:
        return []
    limit = _chunk_char_budget()
    overlap = max(0, min(_CHUNK_OVERLAP_CHARS, limit // 4))
    if len(normalized) <= limit:
        return [normalized]
    parts: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + limit)
        parts.append(normalized[start:end].strip())
        if end >= len(normalized):
            break
        start = max(start + 1, end - overlap)
    return [part for part in parts if part]


def _section_chunks_from_lines(
    lines: Sequence[tuple[str, str]],
    *,
    section: str,
    ordinal_start: int,
) -> list[tuple[str, str, str, int]]:
    """Build section chunks as (section, field_path, text, ordinal)."""
    if not lines:
        return []
    bodies = _split_with_overlap("\n".join(line for _, line in lines))
    chunks: list[tuple[str, str, str, int]] = []
    ordinal = ordinal_start
    for body in bodies:
        field_path = lines[0][0]
        chunks.append((section, field_path, body, ordinal))
        ordinal += 1
    return chunks


def _ticket_core_text(record: ClosedTicketRecord) -> str:
    parts: list[str] = [
        f"ticket_id: {record.ticket_id}",
    ]
    if record.ticket_number:
        parts.append(f"ticket_number: {record.ticket_number}")
    if record.source_table:
        parts.append(f"source_table: {record.source_table}")
    if record.state:
        parts.append(f"state: {record.state}")
    if record.closed_at is not None:
        parts.append(f"closed_at: {record.closed_at.isoformat()}")
    if record.source_url:
        parts.append(f"source_url: {record.source_url}")
    return "\n".join(parts)


def _ticket_summary_text(record: ClosedTicketRecord) -> str | None:
    lines = _leaf_lines(record.raw_payload, "$.raw_payload")
    preview = lines[:_SUMMARY_LEAF_LIMIT]
    if not preview:
        return None
    body = "\n".join(line for _, line in preview)
    core = _ticket_core_text(record)
    return f"{core}\n---\n{body}".strip()


def _normalize_journals(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("entries", "journals", "records", "result"):
            nested = value.get(key)
            if isinstance(nested, list):
                return nested
        return [value]
    return [value]


def _make_chunk(
    *,
    record: ClosedTicketRecord,
    section: str,
    field_path: str,
    text: str,
    ordinal: int,
    config: Config,
    extra_metadata: dict[str, Any] | None = None,
) -> ClosedTicketChunkRecord:
    chunk_id = build_closed_ticket_chunk_id(
        ticket_id=record.ticket_id,
        section=section,
        ordinal=ordinal,
    )
    metadata = {
        "ticket_id": record.ticket_id,
        "ticket_number": record.ticket_number,
        "chunk_id": chunk_id,
        "section": section,
        "field_path": field_path,
        "source_url": record.source_url,
        "source_table": record.source_table,
        "closed_at": (
            record.closed_at.isoformat() if record.closed_at is not None else None
        ),
        "content_hash": record.content_hash,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    rendered = f"{section}\n{field_path}\n{text}".strip()
    return ClosedTicketChunkRecord(
        chunk_id=chunk_id,
        ticket_id=record.ticket_id,
        ordinal=ordinal,
        section=section,
        field_path=field_path,
        text=rendered,
        metadata=metadata,
        chunk_schema_version=closed_ticket_chunk_schema_version(config),
        embedding_model=closed_ticket_embedding_model(config),
    )


def build_closed_ticket_chunks(
    record: ClosedTicketRecord,
    config: Config,
    *,
    attachments: Sequence[ClosedTicketAttachmentRecord] = (),
) -> list[ClosedTicketChunkRecord]:
    """Build deterministic closed-ticket chunks; never mixes multiple tickets."""
    chunks: list[ClosedTicketChunkRecord] = []
    budget = _config_int(config, "CLOSED_TICKET_MAX_INDEX_CHUNKS_PER_TICKET", _MAX_INDEX_CHUNKS_DEFAULT)
    ordinal = 0

    core_text = _ticket_core_text(record)
    for part in _split_with_overlap(core_text):
        chunks.append(
            _make_chunk(
                record=record,
                section="ticket.core",
                field_path="$",
                text=part,
                ordinal=ordinal,
                config=config,
            )
        )
        ordinal += 1
        if len(chunks) >= budget:
            return chunks

    summary = _ticket_summary_text(record)
    if summary:
        for part in _split_with_overlap(summary):
            chunks.append(
                _make_chunk(
                    record=record,
                    section="ticket.summary",
                    field_path="$.raw_payload",
                    text=part,
                    ordinal=ordinal,
                    config=config,
                )
            )
            ordinal += 1
            if len(chunks) >= budget:
                return chunks

    payload_lines = _leaf_lines(record.raw_payload, "$.raw_payload")
    for section, field_path, text, chunk_ordinal in _section_chunks_from_lines(
        payload_lines,
        section="ticket.payload",
        ordinal_start=ordinal,
    ):
        chunks.append(
            _make_chunk(
                record=record,
                section=section,
                field_path=field_path,
                text=text,
                ordinal=chunk_ordinal,
                config=config,
            )
        )
        ordinal = chunk_ordinal + 1
        if len(chunks) >= budget:
            return chunks

    for index, entry in enumerate(_normalize_journals(record.journals_payload)):
        journal_lines = _leaf_lines(entry, f"$.journals[{index}]")
        for section, field_path, text, chunk_ordinal in _section_chunks_from_lines(
            journal_lines,
            section="ticket.journals",
            ordinal_start=ordinal,
        ):
            chunks.append(
                _make_chunk(
                    record=record,
                    section=section,
                    field_path=field_path,
                    text=text,
                    ordinal=chunk_ordinal,
                    config=config,
                    extra_metadata={"journal_index": index},
                )
            )
            ordinal = chunk_ordinal + 1
            if len(chunks) >= budget:
                return chunks

    for attachment in attachments:
        if attachment.ticket_id != record.ticket_id:
            continue
        semantic = (attachment.semantic_text or "").strip()
        if not semantic:
            continue
        meta = {
            "attachment_id": attachment.attachment_id,
            "filename": attachment.filename,
            "content_type": attachment.content_type,
            "extraction_status": attachment.extraction_status,
        }
        for part in _split_with_overlap(semantic):
            chunks.append(
                _make_chunk(
                    record=record,
                    section="attachment.semantic",
                    field_path=f"$.attachments[{attachment.attachment_id}]",
                    text=part,
                    ordinal=ordinal,
                    config=config,
                    extra_metadata=meta,
                )
            )
            ordinal += 1
            if len(chunks) >= budget:
                return chunks
    return chunks
