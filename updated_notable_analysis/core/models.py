"""Canonical domain models for the updated notable-analysis shared core."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from .validators import (
    normalize_mapping,
    normalize_optional_non_negative_int,
    normalize_optional_string,
    normalize_string_list,
    parse_datetime,
    parse_enum,
    require_non_empty_string,
)
from .vocabulary import EvidenceType, HypothesisType, QueryDialect, QueryStrategy, WritebackStatus


@dataclass(slots=True)
class NormalizedAlert:
    """Canonical baseline analysis input object."""

    schema_version: str
    source_system: str
    source_type: str
    source_record_ref: str
    received_at: datetime | str
    raw_content_type: str
    raw_content: str
    alert_time: datetime | str | None = None
    title: str | None = None
    severity: str | None = None
    finding_id: str | None = None
    notable_id: str | None = None
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        """Validate and normalize normalized alert fields."""
        self.schema_version = require_non_empty_string(self.schema_version, "schema_version")
        self.source_system = require_non_empty_string(self.source_system, "source_system")
        self.source_type = require_non_empty_string(self.source_type, "source_type")
        self.source_record_ref = require_non_empty_string(
            self.source_record_ref, "source_record_ref"
        )
        self.received_at = parse_datetime(self.received_at, "received_at")
        self.raw_content_type = require_non_empty_string(
            self.raw_content_type, "raw_content_type"
        )
        self.raw_content = require_non_empty_string(self.raw_content, "raw_content")
        self.alert_time = (
            None if self.alert_time is None else parse_datetime(self.alert_time, "alert_time")
        )
        self.title = normalize_optional_string(self.title, "title")
        self.severity = normalize_optional_string(self.severity, "severity")
        self.finding_id = normalize_optional_string(self.finding_id, "finding_id")
        self.notable_id = normalize_optional_string(self.notable_id, "notable_id")
        self.metadata = normalize_mapping(self.metadata, "metadata")


@dataclass(slots=True)
class AlertEvidence:
    """Structured direct evidence item from alert payload facts."""

    evidence_type: EvidenceType | str
    label: str
    value: str

    def __post_init__(self) -> None:
        """Validate and normalize direct evidence fields."""
        self.evidence_type = parse_enum(self.evidence_type, EvidenceType, "evidence_type")
        if self.evidence_type is not EvidenceType.ALERT_DIRECT:
            raise ValueError("AlertEvidence requires evidence_type='alert_direct'.")
        self.label = require_non_empty_string(self.label, "label")
        self.value = require_non_empty_string(self.value, "value")


@dataclass(slots=True)
class AdvisoryContextSnippet:
    """Normalized advisory retrieval item used in prompt grounding and citations."""

    source_type: str
    source_id: str
    title: str
    content: str
    provenance_ref: str
    source_file: str | None = None
    section_path: str | None = None
    rank: int | None = None

    def __post_init__(self) -> None:
        """Validate advisory context snippet fields."""
        self.source_type = require_non_empty_string(self.source_type, "source_type")
        self.source_id = require_non_empty_string(self.source_id, "source_id")
        self.title = require_non_empty_string(self.title, "title")
        self.content = require_non_empty_string(self.content, "content")
        self.provenance_ref = require_non_empty_string(self.provenance_ref, "provenance_ref")
        self.source_file = normalize_optional_string(self.source_file, "source_file")
        self.section_path = normalize_optional_string(self.section_path, "section_path")
        self.rank = normalize_optional_non_negative_int(self.rank, "rank")


@dataclass(slots=True)
class InvestigationHypothesis:
    """Canonical hypothesis object for report and investigation planning."""

    hypothesis_type: HypothesisType | str
    hypothesis: str
    evidence_support: Sequence[str]
    evidence_gaps: Sequence[str]
    best_pivots: Sequence[str] = ()

    def __post_init__(self) -> None:
        """Validate and normalize hypothesis fields."""
        self.hypothesis_type = parse_enum(
            self.hypothesis_type, HypothesisType, "hypothesis_type"
        )
        self.hypothesis = require_non_empty_string(self.hypothesis, "hypothesis")
        self.evidence_support = normalize_string_list(
            self.evidence_support, "evidence_support", allow_empty=False
        )
        self.evidence_gaps = normalize_string_list(
            self.evidence_gaps, "evidence_gaps", allow_empty=False
        )
        self.best_pivots = normalize_string_list(self.best_pivots, "best_pivots")


@dataclass(slots=True)
class QueryPlan:
    """Canonical read-only query-plan contract."""

    query_dialect: QueryDialect | str
    query_strategy: QueryStrategy | str
    query_text: str
    purpose: str
    time_range: str | None = None
    max_rows: int | None = None
    execution_timeout_seconds: int | None = None
    expected_signal: str | None = None
    grounding_refs: Sequence[str] = ()

    def __post_init__(self) -> None:
        """Validate and normalize query-plan fields."""
        self.query_dialect = parse_enum(self.query_dialect, QueryDialect, "query_dialect")
        self.query_strategy = parse_enum(self.query_strategy, QueryStrategy, "query_strategy")
        self.query_text = require_non_empty_string(self.query_text, "query_text")
        self.purpose = require_non_empty_string(self.purpose, "purpose")
        self.time_range = normalize_optional_string(self.time_range, "time_range")
        self.max_rows = normalize_optional_non_negative_int(self.max_rows, "max_rows")
        self.execution_timeout_seconds = normalize_optional_non_negative_int(
            self.execution_timeout_seconds, "execution_timeout_seconds"
        )
        self.expected_signal = normalize_optional_string(
            self.expected_signal, "expected_signal"
        )
        self.grounding_refs = normalize_string_list(self.grounding_refs, "grounding_refs")


@dataclass(slots=True)
class QueryExecutionRequest:
    """Normalized read-only query execution request for adapter boundaries."""

    query_plan: QueryPlan
    policy_bundle_name: str
    source_system: str

    def __post_init__(self) -> None:
        """Validate execution request fields."""
        if not isinstance(self.query_plan, QueryPlan):
            raise ValueError("Field 'query_plan' must be QueryPlan.")
        self.policy_bundle_name = require_non_empty_string(
            self.policy_bundle_name, "policy_bundle_name"
        )
        self.source_system = require_non_empty_string(self.source_system, "source_system")


@dataclass(slots=True)
class QueryResultEvidence:
    """Normalized read-only query-result evidence object."""

    evidence_type: EvidenceType | str
    query_dialect: QueryDialect | str
    query_text: str
    result_summary: str
    raw_result_ref: str
    rows_returned: int | None = None
    execution_time_ms: int | None = None
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        """Validate and normalize query-result evidence fields."""
        self.evidence_type = parse_enum(self.evidence_type, EvidenceType, "evidence_type")
        if self.evidence_type is not EvidenceType.QUERY_RESULT:
            raise ValueError("QueryResultEvidence requires evidence_type='query_result'.")
        self.query_dialect = parse_enum(self.query_dialect, QueryDialect, "query_dialect")
        self.query_text = require_non_empty_string(self.query_text, "query_text")
        self.result_summary = require_non_empty_string(self.result_summary, "result_summary")
        self.raw_result_ref = require_non_empty_string(self.raw_result_ref, "raw_result_ref")
        self.rows_returned = normalize_optional_non_negative_int(
            self.rows_returned, "rows_returned"
        )
        self.execution_time_ms = normalize_optional_non_negative_int(
            self.execution_time_ms, "execution_time_ms"
        )
        self.metadata = normalize_mapping(self.metadata, "metadata")


@dataclass(slots=True)
class EvidenceSection:
    """Normalized report evidence section."""

    evidence_type: EvidenceType | str
    summary: str

    def __post_init__(self) -> None:
        """Validate report evidence section fields."""
        self.evidence_type = parse_enum(self.evidence_type, EvidenceType, "evidence_type")
        self.summary = require_non_empty_string(self.summary, "summary")


def _normalize_hypothesis(value: InvestigationHypothesis | Mapping[str, Any]) -> InvestigationHypothesis:
    """Normalize one hypothesis entry into InvestigationHypothesis."""
    if isinstance(value, InvestigationHypothesis):
        return value
    if isinstance(value, Mapping):
        return InvestigationHypothesis(
            hypothesis_type=value["hypothesis_type"],
            hypothesis=value["hypothesis"],
            evidence_support=value.get("evidence_support", ()),
            evidence_gaps=value.get("evidence_gaps", ()),
            best_pivots=value.get("best_pivots", ()),
        )
    raise ValueError("Hypothesis entries must be InvestigationHypothesis or mapping.")


def _normalize_evidence_section(value: EvidenceSection | Mapping[str, Any]) -> EvidenceSection:
    """Normalize one report evidence section into EvidenceSection."""
    if isinstance(value, EvidenceSection):
        return value
    if isinstance(value, Mapping):
        return EvidenceSection(
            evidence_type=value["evidence_type"],
            summary=value["summary"],
        )
    raise ValueError("Evidence sections must be EvidenceSection or mapping.")


@dataclass(slots=True)
class AnalysisReport:
    """Canonical report object for baseline and enriched analysis paths."""

    schema_version: str
    alert_reconciliation: Mapping[str, Any]
    competing_hypotheses: Sequence[InvestigationHypothesis | Mapping[str, Any]]
    evidence_sections: Sequence[EvidenceSection | Mapping[str, Any]]
    ioc_extraction: Mapping[str, Any]
    ttp_analysis: Sequence[Mapping[str, Any]]
    query_result_section: Mapping[str, Any] | None = None
    advisory_context_refs: Sequence[str] = ()
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        """Validate and normalize report contract fields."""
        self.schema_version = require_non_empty_string(self.schema_version, "schema_version")
        self.alert_reconciliation = normalize_mapping(
            self.alert_reconciliation, "alert_reconciliation"
        )
        self.competing_hypotheses = tuple(
            _normalize_hypothesis(item) for item in self.competing_hypotheses
        )
        if not self.competing_hypotheses:
            raise ValueError("Field 'competing_hypotheses' must contain at least one entry.")
        self.evidence_sections = tuple(
            _normalize_evidence_section(item) for item in self.evidence_sections
        )
        if not self.evidence_sections:
            raise ValueError("Field 'evidence_sections' must contain at least one entry.")
        self.ioc_extraction = normalize_mapping(self.ioc_extraction, "ioc_extraction")
        if not isinstance(self.ttp_analysis, Sequence):
            raise ValueError("Field 'ttp_analysis' must be a sequence of mappings.")
        normalized_ttps: list[dict[str, Any]] = []
        for idx, item in enumerate(self.ttp_analysis):
            if not isinstance(item, Mapping):
                raise ValueError(f"Field 'ttp_analysis[{idx}]' must be a mapping.")
            normalized_ttps.append(dict(item))
        self.ttp_analysis = tuple(normalized_ttps)
        self.query_result_section = normalize_mapping(
            self.query_result_section, "query_result_section"
        )
        self.advisory_context_refs = normalize_string_list(
            self.advisory_context_refs, "advisory_context_refs"
        )
        self.metadata = normalize_mapping(self.metadata, "metadata")


@dataclass(slots=True)
class WritebackDraft:
    """Normalized pre-write downstream payload."""

    target_system: str
    target_operation: str
    summary: str
    body: str
    routing_key: str | None = None
    external_ref: str | None = None
    fields: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        """Validate and normalize writeback draft fields."""
        self.target_system = require_non_empty_string(self.target_system, "target_system")
        self.target_operation = require_non_empty_string(
            self.target_operation, "target_operation"
        )
        self.summary = require_non_empty_string(self.summary, "summary")
        self.body = require_non_empty_string(self.body, "body")
        self.routing_key = normalize_optional_string(self.routing_key, "routing_key")
        self.external_ref = normalize_optional_string(self.external_ref, "external_ref")
        self.fields = normalize_mapping(self.fields, "fields")


@dataclass(slots=True)
class WritebackResult:
    """Normalized post-write result contract."""

    status: WritebackStatus | str
    target_system: str
    external_id: str | None = None
    message: str | None = None
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        """Validate and normalize writeback result fields."""
        self.status = parse_enum(self.status, WritebackStatus, "status")
        self.target_system = require_non_empty_string(self.target_system, "target_system")
        self.external_id = normalize_optional_string(self.external_id, "external_id")
        self.message = normalize_optional_string(self.message, "message")
        self.metadata = normalize_mapping(self.metadata, "metadata")

