"""Closed-ticket RAG grounding for first-pass alert analysis."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict

from .closed_ticket_retrieval import (
    ClosedTicketRetrievalHit,
    retrieve_closed_tickets_fail_soft,
)
from .config import Config

logger = logging.getLogger(__name__)

HISTORICAL_CLOSED_TICKETS_HEADER = "HISTORICAL_CLOSED_TICKETS"

HISTORICAL_CLOSED_TICKET_RULES = """
HISTORICAL CLOSED-TICKET RULES:
- The HISTORICAL_CLOSED_TICKETS block is advisory precedent from prior closed investigations only.
- Never treat HISTORICAL_CLOSED_TICKETS as direct evidence about the current alert.
- Never copy closed-ticket excerpts into evidence_vs_inference.evidence, ttp_analysis[*].evidence_fields, or ioc_extraction unless the same fact is present in SECURITY ALERT INPUT.
- Prior tickets may inform alert_reconciliation recommended verdict/disposition, confidence, decision_drivers, competing_hypotheses framing, and recommended validation steps in recommended_actions as precedent guidance, not as proof.
- Current alert facts in SECURITY ALERT INPUT override conflicting precedent; explicitly compare similarities, differences, and uncertainty when precedent influences reasoning.
- Do not recommend automatic closure, escalation, or containment solely because a similar ticket was closed a certain way.
- Do not add IOCs or ATT&CK mappings sourced only from HISTORICAL_CLOSED_TICKETS.
- If historical context is weak, missing, or conflicting with current facts, keep guidance broad and use "unknown" where appropriate.
""".strip()

CLOSED_TICKET_RAG_STATUSES = frozenset({"success", "no_match", "degraded", "skipped"})


@dataclass(frozen=True)
class ClosedTicketGroundingResult:
    """Closed-ticket advisory grounding output for prompt assembly and metadata."""

    status: str
    context: str = ""
    snippet_count: int = 0
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def merge_closed_ticket_rag_metadata_into_payload(
    payload: Dict[str, Any],
    closed_ticket_rag_meta: Dict[str, Any],
) -> Dict[str, Any]:
    """Attach closed-ticket RAG metadata fields to an analyze_alert payload."""
    merged = dict(payload)
    metadata = dict(merged.get("metadata") or {})
    metadata.update(closed_ticket_rag_meta)
    merged["metadata"] = metadata
    return merged


def closed_ticket_rag_metadata_for_empty_alert(config: Config) -> Dict[str, Any]:
    """Metadata when analyze_alert rejects empty input (no retrieval run)."""
    enabled = bool(getattr(config, "CLOSED_TICKET_RAG_ENABLED", False))
    return build_closed_ticket_rag_metadata(enabled=enabled)


def _status_for_outcome(
    *,
    enabled: bool,
    hits: list[ClosedTicketRetrievalHit],
    context: str,
    unavailable_reason: str | None,
) -> str:
    if not enabled:
        return "skipped"
    if unavailable_reason:
        return "degraded"
    if context.strip():
        return "success"
    return "no_match"


def build_closed_ticket_rag_metadata(
    *,
    enabled: bool,
    hits: list[ClosedTicketRetrievalHit] | None = None,
    context: str = "",
    unavailable_reason: str | None = None,
) -> Dict[str, Any]:
    """Build metadata fields for closed-ticket RAG without embedding retrieved text."""
    hits = hits or []
    context = context or ""
    status = _status_for_outcome(
        enabled=enabled,
        hits=hits,
        context=context,
        unavailable_reason=unavailable_reason,
    )
    metadata: Dict[str, Any] = {
        "closed_ticket_rag_status": status,
        "closed_ticket_rag_enabled": enabled,
        "closed_ticket_rag_included": bool(context.strip()),
        "closed_ticket_rag_hit_count": len(hits),
        "closed_ticket_rag_snippet_count": len(hits),
        "closed_ticket_rag_context_chars": len(context),
        "closed_ticket_rag_unavailable": bool(unavailable_reason),
    }
    if unavailable_reason:
        metadata["closed_ticket_rag_unavailable_reason"] = str(unavailable_reason)[:600]
        metadata["closed_ticket_rag_message"] = str(unavailable_reason)[:600]
    return metadata


def format_historical_closed_tickets_prompt_block(context: str) -> str:
    """Render the advisory lane block for the first-pass prompt."""
    block = (context or "").strip()
    if not block:
        return f"{HISTORICAL_CLOSED_TICKETS_HEADER}\n(none)\n"
    return block


def retrieve_historical_closed_tickets_for_first_pass(
    config: Config,
    alert_text: str,
    *,
    opensearch_client: Any | None = None,
    bedrock_client: Any | None = None,
) -> ClosedTicketGroundingResult:
    """Fail-soft closed-ticket retrieval for the first-pass analyzer call."""
    enabled = bool(getattr(config, "CLOSED_TICKET_RAG_ENABLED", False))
    if not enabled:
        metadata = build_closed_ticket_rag_metadata(enabled=False)
        return ClosedTicketGroundingResult(
            status=str(metadata["closed_ticket_rag_status"]),
            metadata=metadata,
        )

    try:
        outcome = retrieve_closed_tickets_fail_soft(
            config=config,
            alert_text=alert_text,
            opensearch_client=opensearch_client,
            bedrock_client=bedrock_client,
        )
        metadata = build_closed_ticket_rag_metadata(
            enabled=True,
            hits=outcome.hits,
            context=outcome.context,
            unavailable_reason=outcome.error,
        )
        return ClosedTicketGroundingResult(
            status=str(metadata["closed_ticket_rag_status"]),
            context=outcome.context,
            snippet_count=len(outcome.hits),
            message=str(outcome.error or ""),
            metadata=metadata,
        )
    except Exception as exc:
        logger.warning(
            "Historical closed-ticket retrieval failed for first-pass analysis: %s",
            exc,
        )
        metadata = build_closed_ticket_rag_metadata(
            enabled=True,
            unavailable_reason=str(exc),
        )
        return ClosedTicketGroundingResult(
            status=str(metadata["closed_ticket_rag_status"]),
            message=str(exc),
            metadata=metadata,
        )
