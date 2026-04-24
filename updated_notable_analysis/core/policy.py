"""Deterministic policy checks for core profiles and query execution plans."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .config_models import CapabilityProfile, QueryPolicyBundle
from .models import QueryPlan
from .validators import normalize_mapping, normalize_optional_string, require_bool, require_non_empty_string
from .vocabulary import CapabilityName, QueryDialect, WRITEBACK_CAPABILITIES


@dataclass(slots=True)
class PolicyDecision:
    """Normalized allow or deny decision from deterministic policy checks."""

    allowed: bool
    reason_code: str
    message: str | None = None
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        """Validate policy-decision fields."""
        self.allowed = require_bool(self.allowed, "allowed")
        self.reason_code = require_non_empty_string(self.reason_code, "reason_code")
        self.message = normalize_optional_string(self.message, "message")
        self.metadata = normalize_mapping(self.metadata, "metadata")


def _deny(reason_code: str, message: str, metadata: Mapping[str, Any] | None = None) -> PolicyDecision:
    """Create a deterministic deny policy decision."""
    return PolicyDecision(
        allowed=False,
        reason_code=reason_code,
        message=message,
        metadata=metadata or {},
    )


def _allow(reason_code: str = "allow") -> PolicyDecision:
    """Create a deterministic allow policy decision."""
    return PolicyDecision(allowed=True, reason_code=reason_code, metadata={})


_INDEX_PATTERN = re.compile(
    r"""\bindex\s*=\s*(?:"([^"]+)"|'([^']+)'|([A-Za-z0-9_.\-*]+))""",
    re.IGNORECASE,
)

_DURATION_PATTERN = re.compile(
    r"^\s*(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)\s*$",
    re.IGNORECASE,
)


def _extract_index_names(query_text: str) -> tuple[str, ...]:
    """Extract explicit SPL index=<name> references from query text."""
    indexes: list[str] = []
    for match in _INDEX_PATTERN.finditer(query_text):
        raw_name = next(group for group in match.groups() if group is not None)
        indexes.append(raw_name.strip().lower())
    return tuple(indexes)


def _duration_to_seconds(value: str) -> int | None:
    """Parse a compact duration string into seconds."""
    match = _DURATION_PATTERN.match(value)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith("s"):
        return amount
    if unit.startswith("m"):
        return amount * 60
    if unit.startswith("h"):
        return amount * 60 * 60
    return amount * 24 * 60 * 60


def validate_capability_profile(profile: CapabilityProfile) -> PolicyDecision:
    """Validate profile combinations and writeback approval requirements."""
    enabled = set(profile.enabled_capabilities)

    if CapabilityName.NOTABLE_ANALYSIS not in enabled:
        return _deny(
            reason_code="missing_baseline_capability",
            message="Capability profiles must enable notable_analysis.",
        )

    if (
        CapabilityName.QUERY_RESULT_ENRICHED_ANALYSIS in enabled
        and CapabilityName.READONLY_SPLUNK_INVESTIGATION not in enabled
    ):
        return _deny(
            reason_code="unsupported_capability_combination",
            message=(
                "query_result_enriched_analysis requires readonly_splunk_investigation."
            ),
            metadata={"requires": CapabilityName.READONLY_SPLUNK_INVESTIGATION.value},
        )

    if (
        CapabilityName.TICKET_CREATE_WRITEBACK in enabled
        and CapabilityName.TICKET_DRAFT_WRITEBACK not in enabled
    ):
        return _deny(
            reason_code="unsupported_capability_combination",
            message="ticket_create_writeback requires ticket_draft_writeback.",
            metadata={"requires": CapabilityName.TICKET_DRAFT_WRITEBACK.value},
        )

    enabled_writeback_caps = sorted(
        capability.value for capability in enabled if capability in WRITEBACK_CAPABILITIES
    )
    if enabled_writeback_caps:
        approvals = dict(profile.approval_requirements or {})
        for capability_name in enabled_writeback_caps:
            if approvals.get(capability_name) is not True:
                return _deny(
                    reason_code="missing_writeback_approval_requirement",
                    message=(
                        "Writeback capabilities require explicit approval_requirements=true."
                    ),
                    metadata={"missing_capability": capability_name},
                )

    return _allow()


def validate_query_plan_policy(
    query_plan: QueryPlan, policy_bundle: QueryPolicyBundle
) -> PolicyDecision:
    """Validate query plan against deterministic read-only policy bundle rules."""
    if query_plan.query_dialect is not QueryDialect.SPL:
        return _deny(
            reason_code="unsupported_query_dialect",
            message="Only SPL query dialect is supported in the initial policy bundle.",
        )

    query_text_lower = query_plan.query_text.lower()

    for denied_command in policy_bundle.denied_commands:
        pattern = rf"\b{re.escape(denied_command)}\b"
        if re.search(pattern, query_text_lower):
            return _deny(
                reason_code="policy_denied_command",
                message=f"Query contains denied command: {denied_command}",
                metadata={"denied_command": denied_command},
            )

    allowed_command_found = any(
        re.search(rf"\b{re.escape(command)}\b", query_text_lower)
        for command in policy_bundle.allowed_commands
    )
    if not allowed_command_found:
        return _deny(
            reason_code="policy_missing_allowed_command",
            message="Query does not include any allowed command from policy bundle.",
        )

    referenced_indexes = _extract_index_names(query_plan.query_text)
    if not referenced_indexes:
        return _deny(
            reason_code="policy_missing_allowed_index",
            message="Query must reference at least one explicit allowed index.",
        )

    allowed_indexes = {index_name.lower() for index_name in policy_bundle.allowed_indexes}
    disallowed_indexes = sorted(
        index_name for index_name in set(referenced_indexes) if index_name not in allowed_indexes
    )
    if disallowed_indexes:
        return _deny(
            reason_code="policy_disallowed_index",
            message="Query references an index outside the policy allowlist.",
            metadata={"disallowed_indexes": disallowed_indexes},
        )

    if query_plan.time_range is None:
        return _deny(
            reason_code="policy_missing_time_range",
            message="Query plan must include a bounded time_range.",
        )
    query_time_range_seconds = _duration_to_seconds(query_plan.time_range)
    policy_time_range_seconds = _duration_to_seconds(policy_bundle.max_time_range)
    if query_time_range_seconds is None or policy_time_range_seconds is None:
        return _deny(
            reason_code="policy_invalid_time_range",
            message="Query plan and policy bundle time ranges must use supported duration units.",
            metadata={
                "query_time_range": query_plan.time_range,
                "policy_max_time_range": policy_bundle.max_time_range,
            },
        )
    if query_time_range_seconds > policy_time_range_seconds:
        return _deny(
            reason_code="policy_time_range_exceeded",
            message="Query plan time_range exceeds policy max_time_range.",
            metadata={
                "query_time_range": query_plan.time_range,
                "policy_max_time_range": policy_bundle.max_time_range,
            },
        )

    if query_plan.max_rows is None:
        return _deny(
            reason_code="policy_missing_max_rows",
            message="Query plan must include a max_rows limit.",
        )
    if query_plan.max_rows <= 0 or query_plan.max_rows > policy_bundle.max_rows:
        return _deny(
            reason_code="policy_max_rows_exceeded",
            message="Query plan max_rows must be positive and within the policy limit.",
            metadata={"query_max_rows": query_plan.max_rows, "policy_max_rows": policy_bundle.max_rows},
        )

    if query_plan.execution_timeout_seconds is None:
        return _deny(
            reason_code="policy_missing_execution_timeout",
            message="Query plan must include an execution_timeout_seconds limit.",
        )
    if (
        query_plan.execution_timeout_seconds <= 0
        or query_plan.execution_timeout_seconds > policy_bundle.execution_timeout_seconds
    ):
        return _deny(
            reason_code="policy_execution_timeout_exceeded",
            message="Query plan execution timeout must be positive and within the policy limit.",
            metadata={
                "query_execution_timeout_seconds": query_plan.execution_timeout_seconds,
                "policy_execution_timeout_seconds": policy_bundle.execution_timeout_seconds,
            },
        )

    if policy_bundle.approval_required:
        return _deny(
            reason_code="policy_approval_required",
            message="Query policy bundle requires explicit approval before execution.",
        )

    return _allow()

