"""Shared enums and capability vocabulary for the core package."""

from __future__ import annotations

from enum import StrEnum


class EvidenceType(StrEnum):
    """Supported evidence classes."""

    ALERT_DIRECT = "alert_direct"
    ADVISORY_CONTEXT = "advisory_context"
    QUERY_RESULT = "query_result"
    WORKFLOW_REPORTED = "workflow_reported"
    OPERATOR_DECLARED = "operator_declared"


class HypothesisType(StrEnum):
    """Supported hypothesis classes."""

    BENIGN = "benign"
    ADVERSARY = "adversary"


class QueryDialect(StrEnum):
    """Supported read-only query dialects."""

    SPL = "spl"


class QueryStrategy(StrEnum):
    """Supported bounded query strategies."""

    RESOLVE_UNKNOWN = "resolve_unknown"
    CHECK_CONTRADICTION = "check_contradiction"


class CapabilityName(StrEnum):
    """Supported capability identifiers for profile validation."""

    NOTABLE_ANALYSIS = "notable_analysis"
    RETRIEVAL_GROUNDING = "retrieval_grounding"
    READONLY_SPLUNK_INVESTIGATION = "readonly_splunk_investigation"
    QUERY_RESULT_ENRICHED_ANALYSIS = "query_result_enriched_analysis"
    SPLUNK_COMMENT_WRITEBACK = "splunk_comment_writeback"
    TICKET_DRAFT_WRITEBACK = "ticket_draft_writeback"
    TICKET_CREATE_WRITEBACK = "ticket_create_writeback"


class ProfileName(StrEnum):
    """Recommended initial capability profile names."""

    ANALYSIS_ONLY = "analysis_only"
    ANALYSIS_PLUS_RAG = "analysis_plus_rag"
    ANALYSIS_PLUS_READONLY_SPL = "analysis_plus_readonly_spl"
    ANALYSIS_PLUS_TICKET_DRAFT = "analysis_plus_ticket_draft"
    ANALYSIS_PLUS_RAG_AND_READONLY_SPL = "analysis_plus_rag_and_readonly_spl"


class WritebackStatus(StrEnum):
    """Normalized writeback result status values."""

    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    DENIED = "denied"


READ_ONLY_CAPABILITIES: frozenset[CapabilityName] = frozenset(
    {
        CapabilityName.NOTABLE_ANALYSIS,
        CapabilityName.RETRIEVAL_GROUNDING,
        CapabilityName.READONLY_SPLUNK_INVESTIGATION,
        CapabilityName.QUERY_RESULT_ENRICHED_ANALYSIS,
    }
)

WRITEBACK_CAPABILITIES: frozenset[CapabilityName] = frozenset(
    {
        CapabilityName.SPLUNK_COMMENT_WRITEBACK,
        CapabilityName.TICKET_DRAFT_WRITEBACK,
        CapabilityName.TICKET_CREATE_WRITEBACK,
    }
)

