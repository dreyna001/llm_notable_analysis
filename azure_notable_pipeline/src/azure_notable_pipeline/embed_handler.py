"""Native Storage Queue dispatcher for deferred case embedding."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .queue_publisher import EmbedQueueJob


class DeferredCaseEmbeddingWorkflowError(RuntimeError):
    """The queue contract exists, but native Blob/Cosmos embedding is deferred."""


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

    if workflow is None:
        raise DeferredCaseEmbeddingWorkflowError(
            "Native case embedding requires the deferred Blob/Cosmos workflow"
        )
    return workflow(job)


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
    "DeferredCaseEmbeddingWorkflowError",
    "dispatch_case_embed_job",
    "dispatch_embed_queue_message",
    "normalize_embed_queue_message",
]
