"""Native Storage Queue dispatcher for deferred case embedding."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .case_embed import EmbedResult, embed_case_envelope
from .config import load_config
from .queue_publisher import EmbedQueueJob


class CaseEmbeddingFailedError(RuntimeError):
    """Embedding failed and the Queue message must remain retryable/poisonable."""


EmbedWorkflow = Callable[[EmbedQueueJob], Any]


def normalize_embed_queue_message(payload: str | bytes) -> EmbedQueueJob:
    """Validate the exact versioned embed-job schema."""

    return EmbedQueueJob.from_json(payload)


def dispatch_case_embed_job(
    job: EmbedQueueJob,
    *,
    workflow: EmbedWorkflow | None = None,
) -> Any:
    """Dispatch a normalized native job to an injected embedding workflow."""

    selected_workflow = workflow or _native_embed_workflow
    result = selected_workflow(job)
    if isinstance(result, EmbedResult) and result.status == "failed":
        raise CaseEmbeddingFailedError(result.message or "case embedding failed")
    return result


def _native_embed_workflow(job: EmbedQueueJob) -> EmbedResult:
    config = load_config()
    return embed_case_envelope(
        container_name=job.case_envelope_container,
        blob_name=job.case_envelope_blob_name,
        config=config,
    )


def dispatch_embed_queue_message(
    payload: str | bytes,
    *,
    workflow: EmbedWorkflow | None = None,
) -> Any:
    """Normalize one Queue message before dispatching it."""

    return dispatch_case_embed_job(
        normalize_embed_queue_message(payload),
        workflow=workflow,
    )


__all__ = [
    "CaseEmbeddingFailedError",
    "dispatch_case_embed_job",
    "dispatch_embed_queue_message",
    "normalize_embed_queue_message",
]
