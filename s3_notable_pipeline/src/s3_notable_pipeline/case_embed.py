"""Post-archive case chunk embedding for the AWS analyst portal."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable

from .config import Config

_SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9_-]+")
_MAX_CHUNK_TEXT_CHARS = 2500
_MAX_ALERT_FIELDS = 40
_MAX_JSON_DEPTH = 40
_ALERT_SUMMARY_KEYS = (
    "summary",
    "description",
    "title",
    "search_name",
    "searchName",
    "rule_name",
    "rule",
    "signature",
    "notable_id",
    "event_id",
    "correlation_id",
    "text",
)
_ALERT_HIGH_VALUE_KEYS = {
    "action",
    "command",
    "command_line",
    "commandLine",
    "correlation_id",
    "dest",
    "dest_ip",
    "destination",
    "destination_ip",
    "description",
    "domain",
    "event_id",
    "file_hash",
    "file_name",
    "file_path",
    "finding_id",
    "host",
    "hostname",
    "ip",
    "notable_id",
    "parent_process",
    "process",
    "process_name",
    "process_path",
    "riskScore",
    "risk_score",
    "rule",
    "rule_name",
    "searchName",
    "search_name",
    "signature",
    "src",
    "src_ip",
    "source",
    "source_ip",
    "summary",
    "text",
    "title",
    "url",
    "user",
    "username",
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
    """One deterministic retrieval chunk derived from a case envelope."""

    chunk_id: str
    case_id: str
    source_lane: str
    section: str
    field_path: str
    text: str
    metadata: dict[str, Any]

    @property
    def search_text(self) -> str:
        """Return the lexical search text stored next to the embedding."""

        return f"{self.section} {self.field_path} {self.text}".strip()


@dataclass(frozen=True)
class EmbedResult:
    """Result of embedding one archived case."""

    status: str
    case_id: str
    chunk_count: int = 0
    message: str = ""


def embed_case_envelope(
    *,
    bucket: str,
    key: str,
    config: Config,
    s3_client: Any,
    bedrock_client: Any,
    dynamodb_client: Any,
) -> EmbedResult:
    """Load one case envelope, rewrite chunks, and update CaseIndex status."""

    case_id = ""
    try:
        envelope = _load_case_envelope(bucket=bucket, key=key, s3_client=s3_client)
        case_id = str(envelope.get("case_id", "")).strip()
        if not case_id:
            raise ValueError("case envelope is missing case_id")
        chunks = build_case_chunks(envelope, config)
        rewrite_case_chunks(
            bucket=bucket,
            case_id=case_id,
            chunks=chunks,
            config=config,
            s3_client=s3_client,
            bedrock_client=bedrock_client,
        )
        update_retrieval_status(
            dynamodb_client=dynamodb_client,
            config=config,
            case_id=case_id,
            status="ready",
            message=f"embedded {len(chunks)} chunk(s)",
        )
        return EmbedResult(status="ready", case_id=case_id, chunk_count=len(chunks))
    except Exception as exc:
        if case_id:
            update_retrieval_status(
                dynamodb_client=dynamodb_client,
                config=config,
                case_id=case_id,
                status="failed",
                message=str(exc),
            )
        return EmbedResult(status="failed", case_id=case_id, message=str(exc))


def build_case_chunks(envelope: dict[str, Any], config: Config) -> list[CaseChunk]:
    """Build deterministic case chunks from envelope JSON, never rendered reports."""

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
            chunks.append(
                _make_chunk(
                    envelope=envelope,
                    source_lane="alert_payload",
                    section="alert.summary",
                    field_path="$",
                    text=text,
                    ordinal=ordinal,
                )
            )
            if len(chunks) >= budget:
                return chunks

    ordinal = 0
    for field_path, text in _iter_alert_key_fields(alert_payload):
        for part in _split_text(text):
            chunks.append(
                _make_chunk(
                    envelope=envelope,
                    source_lane="alert_payload",
                    section="alert.key_fields",
                    field_path=field_path,
                    text=part,
                    ordinal=ordinal,
                )
            )
            ordinal += 1
            if len(chunks) >= budget:
                return chunks

    if not isinstance(analysis, dict):
        return chunks
    for section, key in _ANALYSIS_SECTIONS:
        if key not in analysis:
            continue
        for ordinal, (field_path, text) in enumerate(
            _iter_section_parts(analysis[key], f"$.{key}")
        ):
            chunks.append(
                _make_chunk(
                    envelope=envelope,
                    source_lane="case_analysis",
                    section=section,
                    field_path=field_path,
                    text=text,
                    ordinal=ordinal,
                )
            )
            if len(chunks) >= budget:
                return chunks
    return chunks


def rewrite_case_chunks(
    *,
    bucket: str,
    case_id: str,
    chunks: list[CaseChunk],
    config: Config,
    s3_client: Any,
    bedrock_client: Any,
) -> None:
    """Delete existing chunk objects and write fresh embedded chunks."""

    prefix = f"{config.CASE_ARCHIVE_CHUNKS_PREFIX}/{case_id}/"
    _delete_prefix(bucket=bucket, prefix=prefix, s3_client=s3_client)
    for chunk in chunks:
        embedding = embed_text(chunk.search_text, config, bedrock_client)
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
            "embedding_model": config.CASE_QA_EMBEDDING_MODEL,
            "metadata": chunk.metadata,
        }
        s3_client.put_object(
            Bucket=bucket,
            Key=f"{prefix}{chunk.chunk_id}.json",
            Body=json.dumps(body, ensure_ascii=False, default=str).encode("utf-8"),
            ContentType="application/json",
        )


def embed_text(text: str, config: Config, bedrock_client: Any) -> list[float]:
    """Embed text with Titan and validate the configured vector dimensions."""

    response = bedrock_client.invoke_model(
        modelId=config.CASE_QA_EMBEDDING_MODEL,
        body=json.dumps(
            {
                "inputText": text,
                "dimensions": config.CASE_QA_VECTOR_DIMENSIONS,
                "normalize": config.CASE_QA_EMBED_NORMALIZE,
            }
        ),
        accept="application/json",
        contentType="application/json",
    )
    body = response.get("body")
    payload = body.read() if hasattr(body, "read") else body
    parsed = json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)
    embedding = parsed.get("embedding")
    if embedding is None and isinstance(parsed.get("embeddingsByType"), dict):
        embedding = parsed["embeddingsByType"].get("float")
    if not isinstance(embedding, list) or len(embedding) != config.CASE_QA_VECTOR_DIMENSIONS:
        raise ValueError("Bedrock embedding response dimensions did not match config")
    return [float(value) for value in embedding]


def update_retrieval_status(
    *,
    dynamodb_client: Any,
    config: Config,
    case_id: str,
    status: str,
    message: str = "",
) -> None:
    """Update CaseIndex retrieval status after embed completion or failure."""

    dynamodb_client.update_item(
        TableName=config.CASE_INDEX_TABLE,
        Key={"case_id": {"S": case_id}},
        UpdateExpression=(
            "SET retrieval_status = :status, "
            "retrieval_status_message = :message, "
            "retrieval_updated_at = :updated_at"
        ),
        ExpressionAttributeValues={
            ":status": {"S": status},
            ":message": {"S": message[:500]},
            ":updated_at": {"S": _utc_now()},
        },
    )


def _load_case_envelope(bucket: str, key: str, s3_client: Any) -> dict[str, Any]:
    response = s3_client.get_object(Bucket=bucket, Key=key)
    body = response["Body"].read()
    envelope = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
    if not isinstance(envelope, dict):
        raise ValueError("case envelope must be a JSON object")
    return envelope


def _delete_prefix(bucket: str, prefix: str, s3_client: Any) -> None:
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        response = s3_client.list_objects_v2(**kwargs)
        keys = [{"Key": item["Key"]} for item in response.get("Contents", [])]
        for start in range(0, len(keys), 1000):
            batch = keys[start : start + 1000]
            if batch:
                s3_client.delete_objects(Bucket=bucket, Delete={"Objects": batch})
        if not response.get("IsTruncated"):
            return
        token = response.get("NextContinuationToken")


def _make_chunk(
    *,
    envelope: dict[str, Any],
    source_lane: str,
    section: str,
    field_path: str,
    text: str,
    ordinal: int,
) -> CaseChunk:
    case_id = str(envelope["case_id"])
    chunk_id = build_chunk_id(
        case_id=case_id,
        source_lane=source_lane,
        section=section,
        ordinal=ordinal,
    )
    source = envelope.get("source") if isinstance(envelope.get("source"), dict) else {}
    artifacts = (
        envelope.get("artifacts") if isinstance(envelope.get("artifacts"), dict) else {}
    )
    return CaseChunk(
        chunk_id=chunk_id,
        case_id=case_id,
        source_lane=source_lane,
        section=section,
        field_path=field_path,
        text=f"{section}\n{field_path}\n{text}".strip(),
        metadata={
            "case_id": case_id,
            "chunk_id": chunk_id,
            "stored_source_lane": source_lane,
            "section": section,
            "field_path": field_path,
            "source_filename": source.get("source_filename", ""),
            "finding_id": envelope.get("finding_id", ""),
            "report_markdown_key": artifacts.get("report_markdown_key", ""),
            "report_html_key": artifacts.get("report_html_key", ""),
        },
    )


def build_chunk_id(
    *, case_id: str, source_lane: str, section: str, ordinal: int
) -> str:
    """Build a stable chunk id for one section ordinal."""

    return ":".join(
        (
            _safe_component(case_id),
            _safe_component(source_lane),
            _safe_component(section),
            str(int(ordinal)),
        )
    )


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


def _iter_leaf_values(
    value: Any, path: str = "$", *, depth: int = 0
) -> Iterable[tuple[str, Any]]:
    if depth >= _MAX_JSON_DEPTH:
        yield path, "[max JSON depth reached]"
        return
    if isinstance(value, dict):
        for key in sorted(value):
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


def _iter_alert_key_fields(alert_payload: Any) -> Iterable[tuple[str, str]]:
    if not isinstance(alert_payload, dict):
        return
    yielded = 0
    for path, value in _iter_leaf_values(alert_payload):
        key = path.rsplit(".", 1)[-1].split("[", 1)[0].strip("'")
        if key not in _ALERT_HIGH_VALUE_KEYS:
            continue
        text = _string_or_none(value)
        if text is None:
            continue
        yield path, f"{path}: {text}"
        yielded += 1
        if yielded >= _MAX_ALERT_FIELDS:
            return


def _build_alert_summary_text(alert_payload: Any) -> str | None:
    if isinstance(alert_payload, str):
        return alert_payload.strip()[:_MAX_CHUNK_TEXT_CHARS] or None
    if not isinstance(alert_payload, dict):
        return None
    lines = []
    for key in _ALERT_SUMMARY_KEYS:
        value = _string_or_none(alert_payload.get(key))
        if value is not None:
            lines.append(f"{key}: {value}")
    if not lines:
        return None
    return "\n".join(lines)


def _iter_section_parts(
    value: Any, root_path: str, *, depth: int = 0
) -> Iterable[tuple[str, str]]:
    if depth >= _MAX_JSON_DEPTH:
        yield root_path, "[max JSON depth reached]"
        return
    text = _json_text(value)
    if not isinstance(value, dict | list):
        for part in _split_text(text):
            yield root_path, part
        return
    if len(text) <= _MAX_CHUNK_TEXT_CHARS:
        yield root_path, text
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from _iter_section_parts(
                item,
                f"{root_path}[{index}]",
                depth=depth + 1,
            )
        return
    for key in sorted(value):
        yield from _iter_section_parts(
            value[key],
            _field_path_join(root_path, str(key)),
            depth=depth + 1,
        )


def _split_text(text: str) -> list[str]:
    normalized = text.strip()
    if not normalized:
        return []
    return [
        normalized[start : start + _MAX_CHUNK_TEXT_CHARS]
        for start in range(0, len(normalized), _MAX_CHUNK_TEXT_CHARS)
    ]


def _json_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2)


def _string_or_none(value: Any) -> str | None:
    if value is None or isinstance(value, dict | list | tuple | set):
        return None
    text = str(value).strip()
    return text or None


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
