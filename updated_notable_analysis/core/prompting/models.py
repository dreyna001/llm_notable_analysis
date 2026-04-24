"""Prompt-pack contracts for customer-specific analysis guidance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..validators import normalize_string_list, require_non_empty_string


@dataclass(slots=True)
class PromptPack:
    """Customer prompt-pack contract.

    Attributes:
        pack_name: Stable name used by customer bundle selection.
        analysis_prompt_version: Version label for operator change tracking.
        report_tone: Expected report tone, for example analyst_neutral or executive.
        required_report_sections: Required output sections this prompt pack expects.
        allowed_optional_sections: Optional report sections that are still contract-safe.
        customer_instructions: Additional customer guidance kept separate from workflow code.
    """

    pack_name: str
    analysis_prompt_version: str
    report_tone: str
    required_report_sections: Sequence[str]
    allowed_optional_sections: Sequence[str] = ()
    customer_instructions: Sequence[str] = ()

    def __post_init__(self) -> None:
        """Validate and normalize prompt-pack fields."""
        self.pack_name = require_non_empty_string(self.pack_name, "pack_name")
        self.analysis_prompt_version = require_non_empty_string(
            self.analysis_prompt_version, "analysis_prompt_version"
        )
        self.report_tone = require_non_empty_string(self.report_tone, "report_tone")
        self.required_report_sections = normalize_string_list(
            self.required_report_sections, "required_report_sections", allow_empty=False
        )
        self.allowed_optional_sections = normalize_string_list(
            self.allowed_optional_sections, "allowed_optional_sections"
        )
        self.customer_instructions = normalize_string_list(
            self.customer_instructions, "customer_instructions"
        )

