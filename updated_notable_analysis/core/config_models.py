"""Config, profile, and policy-bundle contracts for the shared core."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .validators import (
    ensure_no_overlap,
    normalize_mapping,
    normalize_optional_string,
    normalize_string_list,
    parse_enum,
    require_bool,
    require_int_gt_zero,
    require_non_empty_string,
)
from .vocabulary import CapabilityName


@dataclass(slots=True)
class RuntimeConfig:
    """Environment-neutral runtime config fields consumed by shared core logic."""

    default_profile_name: str | None = None
    default_customer_bundle_name: str | None = None
    llm_model_name: str | None = None
    llm_timeout_seconds: int = 60

    def __post_init__(self) -> None:
        """Validate runtime config fields."""
        self.default_profile_name = normalize_optional_string(
            self.default_profile_name, "default_profile_name"
        )
        self.default_customer_bundle_name = normalize_optional_string(
            self.default_customer_bundle_name, "default_customer_bundle_name"
        )
        self.llm_model_name = normalize_optional_string(self.llm_model_name, "llm_model_name")
        self.llm_timeout_seconds = require_int_gt_zero(
            self.llm_timeout_seconds, "llm_timeout_seconds"
        )


@dataclass(slots=True)
class CapabilityProfile:
    """Named capability profile with explicit enable and disable lists."""

    profile_name: str
    enabled_capabilities: Sequence[CapabilityName | str]
    disabled_capabilities: Sequence[CapabilityName | str] = ()
    approval_requirements: Mapping[str, bool] | None = None

    def __post_init__(self) -> None:
        """Validate and normalize capability profile fields."""
        self.profile_name = require_non_empty_string(self.profile_name, "profile_name")
        self.enabled_capabilities = tuple(
            parse_enum(value, CapabilityName, "enabled_capabilities")
            for value in self.enabled_capabilities
        )
        if not self.enabled_capabilities:
            raise ValueError("Field 'enabled_capabilities' must contain at least one capability.")
        self.disabled_capabilities = tuple(
            parse_enum(value, CapabilityName, "disabled_capabilities")
            for value in self.disabled_capabilities
        )
        ensure_no_overlap(
            self.enabled_capabilities,
            self.disabled_capabilities,
            field_name="enabled_capabilities/disabled_capabilities",
        )
        raw_approvals = normalize_mapping(self.approval_requirements, "approval_requirements")
        normalized_approvals: dict[str, bool] = {}
        for key, value in raw_approvals.items():
            key_name = require_non_empty_string(key, "approval_requirements key")
            normalized_approvals[key_name] = require_bool(
                value, f"approval_requirements[{key_name}]"
            )
        self.approval_requirements = normalized_approvals


@dataclass(slots=True)
class CustomerBundle:
    """Operator-selected customer bundle for prompts, context, policy, and sinks."""

    prompt_pack_name: str
    context_bundle_name: str
    query_policy_bundle_name: str
    sink_bundle_name: str
    input_mapping_bundle_name: str

    def __post_init__(self) -> None:
        """Validate customer-bundle string references."""
        self.prompt_pack_name = require_non_empty_string(
            self.prompt_pack_name, "prompt_pack_name"
        )
        self.context_bundle_name = require_non_empty_string(
            self.context_bundle_name, "context_bundle_name"
        )
        self.query_policy_bundle_name = require_non_empty_string(
            self.query_policy_bundle_name, "query_policy_bundle_name"
        )
        self.sink_bundle_name = require_non_empty_string(self.sink_bundle_name, "sink_bundle_name")
        self.input_mapping_bundle_name = require_non_empty_string(
            self.input_mapping_bundle_name, "input_mapping_bundle_name"
        )


@dataclass(slots=True)
class QueryPolicyBundle:
    """Deterministic read-only query policy bundle contract."""

    allowed_indexes: Sequence[str]
    allowed_commands: Sequence[str]
    denied_commands: Sequence[str]
    max_time_range: str
    max_rows: int
    execution_timeout_seconds: int
    approval_required: bool = False

    def __post_init__(self) -> None:
        """Validate and normalize query policy bundle fields."""
        self.allowed_indexes = normalize_string_list(
            self.allowed_indexes, "allowed_indexes", allow_empty=False
        )
        self.allowed_commands = tuple(
            command.lower()
            for command in normalize_string_list(
                self.allowed_commands, "allowed_commands", allow_empty=False
            )
        )
        self.denied_commands = tuple(
            command.lower()
            for command in normalize_string_list(self.denied_commands, "denied_commands")
        )
        overlap = set(self.allowed_commands).intersection(self.denied_commands)
        if overlap:
            overlap_str = ", ".join(sorted(overlap))
            raise ValueError(
                f"Query policy commands overlap between allowed and denied: {overlap_str}"
            )
        self.max_time_range = require_non_empty_string(self.max_time_range, "max_time_range")
        self.max_rows = require_int_gt_zero(self.max_rows, "max_rows")
        self.execution_timeout_seconds = require_int_gt_zero(
            self.execution_timeout_seconds, "execution_timeout_seconds"
        )
        self.approval_required = require_bool(self.approval_required, "approval_required")

