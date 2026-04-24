"""Shared core contracts for updated notable analysis."""

from .config_models import CapabilityProfile, CustomerBundle, QueryPolicyBundle, RuntimeConfig
from .context import ContextBundle, ContextProvider, normalize_advisory_context, resolve_context_bundle
from .enrichment import QueryResultEnrichmentInput, enrich_report_with_query_result
from .investigation import (
    QueryInvestigationResult,
    ReadOnlyQueryExecutor,
    execute_query_plan_with_policy,
)
from .models import (
    AdvisoryContextSnippet,
    AlertEvidence,
    AnalysisReport,
    EvidenceSection,
    InvestigationHypothesis,
    NormalizedAlert,
    QueryExecutionRequest,
    QueryPlan,
    QueryResultEvidence,
    WritebackDraft,
    WritebackResult,
)
from .policy import PolicyDecision, validate_capability_profile, validate_query_plan_policy
from .prompting import (
    PromptAssemblyInput,
    PromptAssemblyResult,
    PromptPack,
    assemble_prompt_payload,
    resolve_prompt_pack,
)
from .writeback import WritebackAdapter, WritebackApproval, execute_writeback_with_approval
from .vocabulary import (
    CapabilityName,
    EvidenceType,
    HypothesisType,
    ProfileName,
    QueryDialect,
    QueryStrategy,
    WritebackStatus,
)

__all__ = [
    "AdvisoryContextSnippet",
    "AlertEvidence",
    "AnalysisReport",
    "CapabilityName",
    "CapabilityProfile",
    "ContextBundle",
    "ContextProvider",
    "CustomerBundle",
    "EvidenceSection",
    "EvidenceType",
    "HypothesisType",
    "InvestigationHypothesis",
    "NormalizedAlert",
    "PolicyDecision",
    "ProfileName",
    "PromptAssemblyInput",
    "PromptAssemblyResult",
    "PromptPack",
    "QueryDialect",
    "QueryExecutionRequest",
    "QueryResultEnrichmentInput",
    "QueryInvestigationResult",
    "QueryPlan",
    "QueryPolicyBundle",
    "QueryResultEvidence",
    "QueryStrategy",
    "ReadOnlyQueryExecutor",
    "RuntimeConfig",
    "WritebackAdapter",
    "WritebackApproval",
    "WritebackDraft",
    "WritebackResult",
    "WritebackStatus",
    "assemble_prompt_payload",
    "enrich_report_with_query_result",
    "execute_query_plan_with_policy",
    "execute_writeback_with_approval",
    "normalize_advisory_context",
    "resolve_context_bundle",
    "resolve_prompt_pack",
    "validate_capability_profile",
    "validate_query_plan_policy",
]

