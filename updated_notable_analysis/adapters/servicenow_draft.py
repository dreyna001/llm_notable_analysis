"""ServiceNow draft-ticket writeback construction."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from updated_notable_analysis.core.models import AnalysisReport, WritebackDraft
from updated_notable_analysis.core.validators import (
    normalize_optional_string,
    require_int_gt_zero,
    require_non_empty_string,
)


@dataclass(slots=True)
class ServiceNowIncidentDraftConfig:
    """Configuration for deterministic ServiceNow incident draft construction."""

    assignment_group: str
    category: str = "security"
    subcategory: str | None = None
    impact: str = "2"
    urgency: str = "2"
    max_summary_chars: int = 160
    max_body_chars: int = 8000

    def __post_init__(self) -> None:
        """Validate ServiceNow draft configuration."""
        self.assignment_group = require_non_empty_string(
            self.assignment_group, "assignment_group"
        )
        self.category = require_non_empty_string(self.category, "category")
        self.subcategory = normalize_optional_string(self.subcategory, "subcategory")
        self.impact = require_non_empty_string(self.impact, "impact")
        self.urgency = require_non_empty_string(self.urgency, "urgency")
        self.max_summary_chars = require_int_gt_zero(
            self.max_summary_chars, "max_summary_chars"
        )
        self.max_body_chars = require_int_gt_zero(self.max_body_chars, "max_body_chars")


@dataclass(slots=True)
class ServiceNowIncidentDraftBuilder:
    """Build bounded ServiceNow incident drafts from validated analysis reports."""

    config: ServiceNowIncidentDraftConfig

    def __post_init__(self) -> None:
        """Validate builder dependencies."""
        if not isinstance(self.config, ServiceNowIncidentDraftConfig):
            raise ValueError("Field 'config' must be ServiceNowIncidentDraftConfig.")

    def build(
        self,
        report: AnalysisReport,
        *,
        source_record_ref: str,
        source_system: str = "splunk",
        routing_key: str | None = None,
    ) -> WritebackDraft:
        """Build a ServiceNow incident draft without creating a downstream ticket."""
        if not isinstance(report, AnalysisReport):
            raise ValueError("Field 'report' must be AnalysisReport.")
        source_record_ref = require_non_empty_string(source_record_ref, "source_record_ref")
        source_system = require_non_empty_string(source_system, "source_system")
        routing_key = normalize_optional_string(routing_key, "routing_key")

        summary = _bounded_text(
            _build_summary(report, source_record_ref),
            self.config.max_summary_chars,
        )
        body = _bounded_text(_build_body(report), self.config.max_body_chars)
        fields = _build_servicenow_fields(
            config=self.config,
            summary=summary,
            body=body,
            source_record_ref=source_record_ref,
            source_system=source_system,
        )

        return WritebackDraft(
            target_system="servicenow",
            target_operation="incident_draft",
            summary=summary,
            body=body,
            routing_key=routing_key or self.config.assignment_group,
            external_ref=source_record_ref,
            fields=fields,
        )


def _build_summary(report: AnalysisReport, source_record_ref: str) -> str:
    """Build a compact incident short description."""
    status = report.alert_reconciliation.get("status")
    if isinstance(status, str) and status.strip():
        return f"Security notable {source_record_ref}: {status.strip()}"
    first_hypothesis = report.competing_hypotheses[0].hypothesis
    return f"Security notable {source_record_ref}: {first_hypothesis}"


def _build_body(report: AnalysisReport) -> str:
    """Build a deterministic ServiceNow incident draft body."""
    sections = [
        "Updated Notable Analysis Report",
        "",
        "Alert reconciliation:",
        _json_block(report.alert_reconciliation),
        "",
        "Competing hypotheses:",
        *(
            _format_hypothesis(idx, hypothesis)
            for idx, hypothesis in enumerate(report.competing_hypotheses, start=1)
        ),
        "",
        "Evidence sections:",
        *(
            f"{idx}. [{section.evidence_type.value}] {section.summary}"
            for idx, section in enumerate(report.evidence_sections, start=1)
        ),
        "",
        "IOC extraction:",
        _json_block(report.ioc_extraction),
        "",
        "TTP analysis:",
        _json_block(tuple(report.ttp_analysis)),
    ]
    if report.query_result_section:
        sections.extend(("", "Query-result section:", _json_block(report.query_result_section)))
    if report.advisory_context_refs:
        sections.extend(("", "Advisory context refs:", _json_block(report.advisory_context_refs)))
    return "\n".join(sections)


def _format_hypothesis(idx: int, hypothesis) -> str:  # noqa: ANN001
    """Format one hypothesis for the draft body."""
    return "\n".join(
        (
            f"{idx}. [{hypothesis.hypothesis_type.value}] {hypothesis.hypothesis}",
            f"   Support: {'; '.join(hypothesis.evidence_support)}",
            f"   Gaps: {'; '.join(hypothesis.evidence_gaps)}",
            f"   Best pivots: {'; '.join(hypothesis.best_pivots) or 'none'}",
        )
    )


def _build_servicenow_fields(
    *,
    config: ServiceNowIncidentDraftConfig,
    summary: str,
    body: str,
    source_record_ref: str,
    source_system: str,
) -> dict[str, Any]:
    """Build ServiceNow-compatible draft fields."""
    fields: dict[str, Any] = {
        "short_description": summary,
        "description": body,
        "assignment_group": config.assignment_group,
        "category": config.category,
        "impact": config.impact,
        "urgency": config.urgency,
        "source_system": source_system,
        "source_record_ref": source_record_ref,
        "draft_only": True,
    }
    if config.subcategory is not None:
        fields["subcategory"] = config.subcategory
    return fields


def _bounded_text(value: str, max_chars: int) -> str:
    """Return text constrained to max_chars with an explicit truncation marker."""
    text = require_non_empty_string(value, "value")
    if len(text) <= max_chars:
        return text
    suffix = " [truncated]"
    if max_chars <= len(suffix):
        return text[:max_chars]
    return f"{text[: max_chars - len(suffix)]}{suffix}"


def _json_block(value: Any) -> str:
    """Render stable JSON for structured draft body sections."""
    return json.dumps(value, sort_keys=True, indent=2, default=str)
