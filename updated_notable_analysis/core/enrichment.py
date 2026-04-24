"""Deterministic query-result report enrichment helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .models import (
    AnalysisReport,
    EvidenceSection,
    InvestigationHypothesis,
    QueryPlan,
    QueryResultEvidence,
)
from .validators import normalize_mapping
from .vocabulary import EvidenceType, QueryStrategy


@dataclass(slots=True)
class QueryResultEnrichmentInput:
    """Input contract for one deterministic query-result report enrichment pass."""

    baseline_report: AnalysisReport
    query_plan: QueryPlan
    query_result_evidence: QueryResultEvidence

    def __post_init__(self) -> None:
        """Validate enrichment input fields."""
        if not isinstance(self.baseline_report, AnalysisReport):
            raise ValueError("Field 'baseline_report' must be AnalysisReport.")
        if not isinstance(self.query_plan, QueryPlan):
            raise ValueError("Field 'query_plan' must be QueryPlan.")
        if not isinstance(self.query_result_evidence, QueryResultEvidence):
            raise ValueError("Field 'query_result_evidence' must be QueryResultEvidence.")
        if self.query_result_evidence.query_dialect is not self.query_plan.query_dialect:
            raise ValueError("Query-result evidence dialect must match query plan dialect.")
        if self.query_result_evidence.query_text != self.query_plan.query_text:
            raise ValueError("Query-result evidence text must match query plan text.")


def enrich_report_with_query_result(
    enrichment_input: QueryResultEnrichmentInput,
) -> AnalysisReport:
    """Return a new report enriched with approved query-result evidence."""
    if not isinstance(enrichment_input, QueryResultEnrichmentInput):
        raise ValueError("Field 'enrichment_input' must be QueryResultEnrichmentInput.")

    report = enrichment_input.baseline_report
    query_plan = enrichment_input.query_plan
    evidence = enrichment_input.query_result_evidence
    query_entry = _build_query_result_entry(query_plan, evidence)
    query_result_section = _append_query_result_entry(report.query_result_section, query_entry)

    return AnalysisReport(
        schema_version=report.schema_version,
        alert_reconciliation=report.alert_reconciliation,
        competing_hypotheses=tuple(
            _enrich_hypothesis(hypothesis, query_plan, evidence)
            for hypothesis in report.competing_hypotheses
        ),
        evidence_sections=(
            *report.evidence_sections,
            EvidenceSection(
                evidence_type=EvidenceType.QUERY_RESULT,
                summary=_build_evidence_section_summary(query_plan, evidence),
            ),
        ),
        ioc_extraction=report.ioc_extraction,
        ttp_analysis=report.ttp_analysis,
        query_result_section=query_result_section,
        advisory_context_refs=report.advisory_context_refs,
        metadata=_build_enriched_metadata(report.metadata, query_result_section),
    )


def _build_query_result_entry(
    query_plan: QueryPlan, evidence: QueryResultEvidence
) -> dict[str, Any]:
    """Build one serializable query-result entry for the report section."""
    return {
        "query_dialect": query_plan.query_dialect.value,
        "query_strategy": query_plan.query_strategy.value,
        "query_text": query_plan.query_text,
        "purpose": query_plan.purpose,
        "expected_signal": query_plan.expected_signal,
        "grounding_refs": tuple(query_plan.grounding_refs),
        "result_summary": evidence.result_summary,
        "raw_result_ref": evidence.raw_result_ref,
        "rows_returned": evidence.rows_returned,
        "execution_time_ms": evidence.execution_time_ms,
        "hypothesis_effect": _classify_hypothesis_effect(query_plan, evidence),
    }


def _append_query_result_entry(
    existing_section: Mapping[str, Any], query_entry: Mapping[str, Any]
) -> dict[str, Any]:
    """Append one query result entry while preserving prior section metadata."""
    section = normalize_mapping(existing_section, "query_result_section")
    existing_entries = _normalize_existing_query_result_entries(
        section.get("query_results", ())
    )
    query_results = (*existing_entries, dict(query_entry))
    section["status"] = "query_results_applied"
    section["query_result_count"] = len(query_results)
    section["query_results"] = query_results
    return section


def _normalize_existing_query_result_entries(value: Any) -> tuple[dict[str, Any], ...]:
    """Normalize existing query-result entries before appending a new one."""
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("Field 'query_result_section.query_results' must be a sequence.")

    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ValueError(
                f"Field 'query_result_section.query_results[{idx}]' must be a mapping."
            )
        normalized.append(dict(item))
    return tuple(normalized)


def _build_evidence_section_summary(
    query_plan: QueryPlan, evidence: QueryResultEvidence
) -> str:
    """Build the explicit report evidence summary for query results."""
    row_phrase = "unknown rows"
    if evidence.rows_returned is not None:
        row_phrase = f"{evidence.rows_returned} row(s)"
    return (
        f"Approved {query_plan.query_dialect.value.upper()} query "
        f"({query_plan.query_strategy.value}) returned {row_phrase}: "
        f"{evidence.result_summary} Source: {evidence.raw_result_ref}."
    )


def _enrich_hypothesis(
    hypothesis: InvestigationHypothesis,
    query_plan: QueryPlan,
    evidence: QueryResultEvidence,
) -> InvestigationHypothesis:
    """Return a hypothesis annotated with query-result support or gaps."""
    effect = _classify_hypothesis_effect(query_plan, evidence)
    annotation = _build_hypothesis_annotation(query_plan, evidence, effect)

    support = tuple(hypothesis.evidence_support)
    gaps = tuple(hypothesis.evidence_gaps)
    if effect in {"supports_expected_signal", "contradiction_not_observed"}:
        support = (*support, annotation)
    else:
        gaps = (*gaps, annotation)

    return InvestigationHypothesis(
        hypothesis_type=hypothesis.hypothesis_type,
        hypothesis=hypothesis.hypothesis,
        evidence_support=support,
        evidence_gaps=gaps,
        best_pivots=hypothesis.best_pivots,
    )


def _classify_hypothesis_effect(
    query_plan: QueryPlan, evidence: QueryResultEvidence
) -> str:
    """Classify how the query result should affect hypothesis handling."""
    if evidence.rows_returned is None:
        return "query_result_row_count_unknown"
    if query_plan.query_strategy is QueryStrategy.CHECK_CONTRADICTION:
        if evidence.rows_returned > 0:
            return "contradiction_observed"
        return "contradiction_not_observed"
    if evidence.rows_returned > 0:
        return "supports_expected_signal"
    return "expected_signal_not_observed"


def _build_hypothesis_annotation(
    query_plan: QueryPlan,
    evidence: QueryResultEvidence,
    effect: str,
) -> str:
    """Build a deterministic support/gap annotation from query evidence."""
    expected_signal = query_plan.expected_signal or query_plan.purpose
    return (
        f"Query result effect={effect}; expected_signal={expected_signal}; "
        f"summary={evidence.result_summary}; source={evidence.raw_result_ref}."
    )


def _build_enriched_metadata(
    existing_metadata: Mapping[str, Any], query_result_section: Mapping[str, Any]
) -> dict[str, Any]:
    """Return report metadata with query-result enrichment flags."""
    metadata = normalize_mapping(existing_metadata, "metadata")
    metadata["query_result_enriched"] = True
    metadata["query_result_count"] = query_result_section["query_result_count"]
    return metadata
