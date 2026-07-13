"""Deterministic case chunking and native Azure embedding workflow."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable

from .azure_openai_gateway import embed_texts
from .blob_store import delete_blobs, list_blobs, read_blob, write_blob
from .config import Config
from .cosmos_store import CosmosStore

_SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9_-]+")
_MAX_CHUNK_TEXT_CHARS = 2500
_MAX_ALERT_FIELDS = 40
_MAX_JSON_DEPTH = 40
_ALERT_SUMMARY_KEYS = (
    "summary", "description", "title", "search_name", "searchName", "rule_name",
    "rule", "signature", "notable_id", "event_id", "correlation_id", "text",
)
_ALERT_HIGH_VALUE_KEYS = {
    "action", "command", "command_line", "commandLine", "correlation_id", "dest",
    "dest_ip", "destination", "destination_ip", "description", "domain", "event_id",
    "file_hash", "file_name", "file_path", "finding_id", "host", "hostname", "ip",
    "notable_id", "parent_process", "process", "process_name", "process_path",
    "riskScore", "risk_score", "rule", "rule_name", "searchName", "search_name",
    "signature", "src", "src_ip", "source", "source_ip", "summary", "text", "title",
    "url", "user", "username",
}
_ANALYSIS_SECTIONS: tuple[tuple[str, str], ...] = (
    ("analysis.alert_reconciliation", "alert_reconciliation"),
    ("analysis.competing_hypotheses", "competing_hypotheses"),
    ("analysis.evidence_vs_inference", "evidence_vs_inference"),
    ("analysis.ioc_extraction", "ioc_extraction"),
    ("analysis.ttp_analysis", "ttp_analysis"),
    ("analysis.query_result_section", "query_result_section"),
    ("analysis.servicenow_section", "servicenow_section"),
)


@dataclass(frozen=True)
class CaseChunk:
    chunk_id: str
    case_id: str
    source_lane: str
    section: str
    field_path: str
    text: str
    metadata: dict[str, Any]

    @property
    def search_text(self) -> str:
        return f"{self.section} {self.field_path} {self.text}".strip()


@dataclass(frozen=True)
class EmbedResult:
    status: str
    case_id: str
    chunk_count: int = 0
    message: str = ""


def embed_case_envelope(
    *,
    container_name: str,
    blob_name: str,
    config: Config,
    blob_store: Any | None = None,
    cosmos: CosmosStore | Any | None = None,
    embedding_gateway: Any | None = None,
) -> EmbedResult:
    """Load one envelope, replace its chunks, and converge Cosmos retrieval state."""

    case_id = ""
    persistence = cosmos or CosmosStore.from_config(config)
    try:
        envelope = _load_case_envelope(
            container_name=container_name,
            blob_name=blob_name,
            blob_store=blob_store,
        )
        case_id = str(envelope.get("case_id", "")).strip()
        if not case_id:
            raise ValueError("case envelope is missing case_id")
        chunks = build_case_chunks(envelope, config)
        rewrite_case_chunks(
            container_name=container_name,
            case_id=case_id,
            chunks=chunks,
            config=config,
            blob_store=blob_store,
            embedding_gateway=embedding_gateway,
        )
        update_retrieval_status(
            cosmos=persistence,
            config=config,
            case_id=case_id,
            status="ready",
            message=f"embedded {len(chunks)} chunk(s)",
        )
        return EmbedResult(status="ready", case_id=case_id, chunk_count=len(chunks))
    except Exception as exc:
        if case_id:
            try:
                update_retrieval_status(
                    cosmos=persistence,
                    config=config,
                    case_id=case_id,
                    status="failed",
                    message=str(exc),
                )
            except Exception as status_exc:
                raise RuntimeError(
                    f"embedding failed and retrieval status could not be persisted: {status_exc}"
                ) from exc
        return EmbedResult(status="failed", case_id=case_id, message=str(exc))


def build_case_chunks(envelope: dict[str, Any], config: Config) -> list[CaseChunk]:
    case_id = str(envelope.get("case_id", "")).strip()
    if not case_id:
        raise ValueError("case envelope is missing case_id")
    chunks: list[CaseChunk] = []
    budget = max(1, int(config.CASE_QA_MAX_INDEX_CHUNKS_PER_CASE))
    alert_payload = envelope.get("alert_payload")
    analysis = envelope.get("analysis")

    alert_summary = _build_alert_summary_text(alert_payload)
    if alert_summary:
        for ordinal, text in enumerate(_split_text(alert_summary)):
            chunks.append(_make_chunk(envelope, "alert_payload", "alert.summary", "$", text, ordinal))
            if len(chunks) >= budget:
                return chunks
    ordinal = 0
    for field_path, text in _iter_alert_key_fields(alert_payload):
        for part in _split_text(text):
            chunks.append(_make_chunk(envelope, "alert_payload", "alert.key_fields", field_path, part, ordinal))
            ordinal += 1
            if len(chunks) >= budget:
                return chunks
    if not isinstance(analysis, dict):
        return chunks
    for section, key in _ANALYSIS_SECTIONS:
        if key not in analysis:
            continue
        for ordinal, (field_path, text) in enumerate(_iter_section_parts(analysis[key], f"$.{key}")):
            chunks.append(_make_chunk(envelope, "case_analysis", section, field_path, text, ordinal))
            if len(chunks) >= budget:
                return chunks
    return chunks


def rewrite_case_chunks(
    *,
    container_name: str,
    case_id: str,
    chunks: list[CaseChunk],
    config: Config,
    blob_store: Any | None = None,
    embedding_gateway: Any | None = None,
) -> None:
    """Replace one case prefix with deterministic JSON chunks and 1024-d vectors."""

    prefix = f"{config.CASE_ARCHIVE_CHUNKS_PREFIX}/{case_id}/"
    deleted = 0
    maximum = config.CASE_QA_MAX_INDEX_CHUNKS_PER_CASE
    while True:
        remaining = maximum - deleted
        if remaining < 0:
            raise ValueError("existing case chunk prefix exceeds the configured bounded limit")
        existing = list_blobs(
            container_name,
            prefix=prefix,
            limit=max(1, min(256, remaining + 1)),
            store=blob_store,
        )
        if not existing:
            break
        if len(existing) > remaining:
            raise ValueError("existing case chunk prefix exceeds the configured bounded limit")
        delete_blobs(
            container_name,
            [item.blob_name for item in existing],
            store=blob_store,
        )
        deleted += len(existing)
    vectors = embed_texts(
        [chunk.search_text for chunk in chunks],
        gateway=embedding_gateway,
        deployment=config.AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT or None,
    )
    if len(vectors) != len(chunks):
        raise ValueError("embedding response count did not match case chunks")
    for chunk, embedding in zip(chunks, vectors, strict=True):
        if len(embedding) != config.CASE_QA_VECTOR_DIMENSIONS:
            raise ValueError("Azure OpenAI embedding dimensions did not match config")
        body = {
            "chunk_schema_version": 1,
            "chunk_id": chunk.chunk_id,
            "case_id": chunk.case_id,
            "source_lane": chunk.source_lane,
            "section": chunk.section,
            "field_path": chunk.field_path,
            "text": chunk.text,
            "search_text": chunk.search_text,
            "embedding": embedding,
            "embedding_model": config.AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT,
            "metadata": chunk.metadata,
        }
        write_blob(
            container_name,
            f"{prefix}{chunk.chunk_id}.json",
            json.dumps(body, ensure_ascii=False, default=str).encode("utf-8"),
            content_type="application/json",
            overwrite=True,
            store=blob_store,
        )


def update_retrieval_status(
    *, cosmos: Any, config: Config, case_id: str, status: str, message: str = ""
) -> None:
    cosmos.update_case_retrieval_status(
        config.CASE_INDEX_CONTAINER,
        case_id=case_id,
        status=status,
        message=message[:500],
        updated_at=_utc_now(),
        max_attempts=3,
    )


def _load_case_envelope(*, container_name: str, blob_name: str, blob_store: Any | None) -> dict[str, Any]:
    body = read_blob(container_name, blob_name, store=blob_store)
    try:
        envelope = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("case envelope must be valid UTF-8 JSON") from exc
    if not isinstance(envelope, dict):
        raise ValueError("case envelope must be a JSON object")
    return envelope


def _make_chunk(envelope: dict[str, Any], source_lane: str, section: str, field_path: str, text: str, ordinal: int) -> CaseChunk:
    case_id = str(envelope["case_id"])
    chunk_id = build_chunk_id(case_id=case_id, source_lane=source_lane, section=section, ordinal=ordinal)
    source = envelope.get("source") if isinstance(envelope.get("source"), dict) else {}
    artifacts = envelope.get("artifacts") if isinstance(envelope.get("artifacts"), dict) else {}
    return CaseChunk(
        chunk_id=chunk_id, case_id=case_id, source_lane=source_lane, section=section,
        field_path=field_path, text=f"{section}\n{field_path}\n{text}".strip(),
        metadata={
            "case_id": case_id, "chunk_id": chunk_id, "stored_source_lane": source_lane,
            "section": section, "field_path": field_path,
            "source_filename": source.get("source_filename", ""),
            "finding_id": envelope.get("finding_id", ""),
            "report_markdown_key": artifacts.get("report_markdown_key", ""),
            "report_html_key": artifacts.get("report_html_key", ""),
        },
    )


def build_chunk_id(*, case_id: str, source_lane: str, section: str, ordinal: int) -> str:
    return ":".join((_safe_component(case_id), _safe_component(source_lane), _safe_component(section), str(int(ordinal))))


def _safe_component(value: str) -> str:
    raw = str(value)
    sanitized = _SAFE_COMPONENT_RE.sub("_", raw).strip("_")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    if not sanitized:
        return f"unknown_{digest}"
    if sanitized != raw or len(sanitized) > 100:
        return f"{sanitized[:87]}_{digest}"
    return sanitized


def _field_path_join(base_path: str, key: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        return f"{base_path}.{key}"
    escaped = key.replace("\\", "\\\\").replace("'", "\\'")
    return f"{base_path}['{escaped}']"


def _iter_leaf_values(value: Any, path: str = "$", *, depth: int = 0) -> Iterable[tuple[str, Any]]:
    if depth >= _MAX_JSON_DEPTH:
        yield path, "[max JSON depth reached]"
    elif isinstance(value, dict):
        for key in sorted(value):
            yield from _iter_leaf_values(value[key], _field_path_join(path, str(key)), depth=depth + 1)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _iter_leaf_values(item, f"{path}[{index}]", depth=depth + 1)
    else:
        yield path, value


def _iter_alert_key_fields(alert_payload: Any) -> Iterable[tuple[str, str]]:
    if not isinstance(alert_payload, dict):
        return
    yielded = 0
    for path, value in _iter_leaf_values(alert_payload):
        key = path.rsplit(".", 1)[-1].split("[", 1)[0].strip("'")
        text = _string_or_none(value)
        if key in _ALERT_HIGH_VALUE_KEYS and text is not None:
            yield path, f"{path}: {text}"
            yielded += 1
            if yielded >= _MAX_ALERT_FIELDS:
                return


def _build_alert_summary_text(alert_payload: Any) -> str | None:
    if isinstance(alert_payload, str):
        return alert_payload.strip()[:_MAX_CHUNK_TEXT_CHARS] or None
    if not isinstance(alert_payload, dict):
        return None
    lines = [f"{key}: {text}" for key in _ALERT_SUMMARY_KEYS if (text := _string_or_none(alert_payload.get(key))) is not None]
    return "\n".join(lines) or None


def _iter_section_parts(value: Any, root_path: str, *, depth: int = 0) -> Iterable[tuple[str, str]]:
    if depth >= _MAX_JSON_DEPTH:
        yield root_path, "[max JSON depth reached]"
        return
    text = _json_text(value)
    if not isinstance(value, dict | list):
        for part in _split_text(text):
            yield root_path, part
    elif len(text) <= _MAX_CHUNK_TEXT_CHARS:
        yield root_path, text
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _iter_section_parts(item, f"{root_path}[{index}]", depth=depth + 1)
    else:
        for key in sorted(value):
            yield from _iter_section_parts(value[key], _field_path_join(root_path, str(key)), depth=depth + 1)


def _split_text(text: str) -> list[str]:
    normalized = text.strip()
    return [normalized[start:start + _MAX_CHUNK_TEXT_CHARS] for start in range(0, len(normalized), _MAX_CHUNK_TEXT_CHARS)] if normalized else []


def _json_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2)


def _string_or_none(value: Any) -> str | None:
    if value is None or isinstance(value, dict | list | tuple | set):
        return None
    return str(value).strip() or None


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = ["CaseChunk", "EmbedResult", "build_case_chunks", "build_chunk_id", "embed_case_envelope", "rewrite_case_chunks", "update_retrieval_status"]
