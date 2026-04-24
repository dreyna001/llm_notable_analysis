"""Default prompt packs for early shared-core integration testing."""

from __future__ import annotations

from ..core.prompting import PromptPack


DEFAULT_PROMPT_PACKS: dict[str, PromptPack] = {
    "soc_standard_v1": PromptPack(
        pack_name="soc_standard_v1",
        analysis_prompt_version="v1",
        report_tone="analyst_neutral",
        required_report_sections=(
            "alert_reconciliation",
            "competing_hypotheses",
            "ioc_extraction",
            "ttp_analysis",
        ),
        allowed_optional_sections=("query_result_section", "advisory_context_refs"),
        customer_instructions=(
            "Keep direct evidence and advisory context clearly separated.",
            "Mark unsupported facts as unknown.",
        ),
    ),
    "soc_executive_v1": PromptPack(
        pack_name="soc_executive_v1",
        analysis_prompt_version="v1",
        report_tone="executive_brief",
        required_report_sections=(
            "alert_reconciliation",
            "competing_hypotheses",
            "ttp_analysis",
        ),
        allowed_optional_sections=("ioc_extraction", "query_result_section"),
        customer_instructions=(
            "Prioritize risk, business impact, and recommended next action.",
        ),
    ),
}

