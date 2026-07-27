"""Closed-ticket RAG grounding for first-pass alert analysis."""

from __future__ import annotations

import logging
from typing import Any, Dict, Tuple

from .closed_ticket_retrieval import ClosedTicketRetrievalHit, retrieve_closed_tickets_fail_soft
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
    metadata: Dict[str, Any] = {
        "closed_ticket_rag_enabled": enabled,
        "closed_ticket_rag_included": bool(context.strip()),
        "closed_ticket_rag_hit_count": len(hits),
        "closed_ticket_rag_context_chars": len(context),
        "closed_ticket_rag_unavailable": bool(unavailable_reason),
    }
    if unavailable_reason:
        metadata["closed_ticket_rag_unavailable_reason"] = str(unavailable_reason)[:600]
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
) -> Tuple[str, Dict[str, Any]]:
    """Fail-soft closed-ticket retrieval for the first-pass analyzer call."""
    enabled = bool(getattr(config, "CLOSED_TICKET_RAG_ENABLED", False))
    if not enabled:
        return "", build_closed_ticket_rag_metadata(enabled=False)

    try:
        outcome = retrieve_closed_tickets_fail_soft(
            config=config,
            alert_text=alert_text,
        )
        if outcome.error:
            return "", build_closed_ticket_rag_metadata(
                enabled=True,
                hits=outcome.hits,
                context=outcome.context,
                unavailable_reason=outcome.error,
            )
        return outcome.context, build_closed_ticket_rag_metadata(
            enabled=True,
            hits=outcome.hits,
            context=outcome.context,
        )
    except Exception as exc:
        logger.warning(
            "Historical closed-ticket retrieval failed for first-pass analysis: %s",
            exc,
        )
        return "", build_closed_ticket_rag_metadata(
            enabled=True,
            unavailable_reason=str(exc),
        )
