"""Retrieval-bound pinned-case Q&A for the AWS portal."""

from __future__ import annotations

import json
from typing import Any

from .case_index import get_case_metadata
from .config import Config
from .portal_chat import PortalAnswer, synthesize_case_answer


def answer_selected_case_question(
    *,
    case_id: str,
    question: str,
    config: Config,
    dynamodb_client: Any,
    s3_client: Any,
    bedrock_client: Any,
) -> PortalAnswer:
    """Answer one question using only chunks from the selected case."""

    selected_case_id = str(case_id or "").strip()
    if not selected_case_id:
        raise ValueError("selected_case_id is required")
    normalized_question = str(question or "").strip()
    if not normalized_question:
        raise ValueError("question is required")
    if len(normalized_question) > config.CASE_QA_MAX_QUESTION_CHARS:
        raise ValueError("question exceeds CASE_QA_MAX_QUESTION_CHARS")
    if not config.CASE_QA_ENABLED:
        return PortalAnswer(
            answer="Case Q&A is disabled.",
            answer_status="insufficient_context",
            citations=[],
        )
    chunks = retrieve_selected_case_chunks(
        case_id=selected_case_id,
        config=config,
        dynamodb_client=dynamodb_client,
        s3_client=s3_client,
    )
    return synthesize_case_answer(
        question=normalized_question,
        sources=chunks,
        config=config,
        bedrock_client=bedrock_client,
    )


def retrieve_selected_case_chunks(
    *,
    case_id: str,
    config: Config,
    dynamodb_client: Any,
    s3_client: Any,
) -> list[dict[str, Any]]:
    """Return bounded chunk objects only when retrieval_status is ready."""

    metadata = get_case_metadata(
        config=config,
        dynamodb_client=dynamodb_client,
        case_id=case_id,
    )
    if not metadata:
        raise LookupError("case not found")
    if str(metadata.get("retrieval_status", "")).lower() != "ready":
        return []
    prefix = f"{config.CASE_ARCHIVE_CHUNKS_PREFIX}/{case_id}/"
    chunks: list[dict[str, Any]] = []
    token: str | None = None
    while len(chunks) < config.CASE_QA_MAX_TOTAL_CHUNKS:
        kwargs: dict[str, Any] = {"Bucket": config.CASE_ARCHIVE_BUCKET, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        response = s3_client.list_objects_v2(**kwargs)
        for item in response.get("Contents", []):
            key = item.get("Key")
            if not key:
                continue
            chunk = _load_chunk(config.CASE_ARCHIVE_BUCKET, str(key), s3_client)
            if str(chunk.get("case_id", "")) != case_id:
                continue
            chunks.append(chunk)
            if len(chunks) >= config.CASE_QA_MAX_TOTAL_CHUNKS:
                break
        if len(chunks) >= config.CASE_QA_MAX_TOTAL_CHUNKS or not response.get("IsTruncated"):
            break
        token = response.get("NextContinuationToken")
    return chunks


def _load_chunk(bucket: str, key: str, s3_client: Any) -> dict[str, Any]:
    response = s3_client.get_object(Bucket=bucket, Key=key)
    body = response["Body"].read()
    chunk = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
    if not isinstance(chunk, dict):
        raise ValueError("case chunk must be a JSON object")
    return chunk
