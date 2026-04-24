"""Prompt assembly utilities for normalized alert and advisory context inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from ..config_models import CustomerBundle
from ..models import AdvisoryContextSnippet, NormalizedAlert
from ..validators import normalize_mapping, require_non_empty_string
from .models import PromptPack
from .resolver import resolve_prompt_pack


@dataclass(slots=True)
class PromptAssemblyInput:
    """Input contract for prompt assembly."""

    normalized_alert: NormalizedAlert
    customer_bundle: CustomerBundle
    advisory_context_snippets: Sequence[AdvisoryContextSnippet] = ()

    def __post_init__(self) -> None:
        """Validate prompt-assembly input fields."""
        if not isinstance(self.normalized_alert, NormalizedAlert):
            raise ValueError("Field 'normalized_alert' must be NormalizedAlert.")
        if not isinstance(self.customer_bundle, CustomerBundle):
            raise ValueError("Field 'customer_bundle' must be CustomerBundle.")
        for snippet in self.advisory_context_snippets:
            if not isinstance(snippet, AdvisoryContextSnippet):
                raise ValueError(
                    "Field 'advisory_context_snippets' must contain AdvisoryContextSnippet."
                )
        self.advisory_context_snippets = tuple(self.advisory_context_snippets)


@dataclass(slots=True)
class PromptAssemblyResult:
    """Output contract for assembled prompt payloads.

    Advisory context remains separate from direct alert payload in this contract.
    """

    prompt_pack_name: str
    system_instructions: str
    analyst_prompt: str
    alert_direct_payload: str
    advisory_context: Sequence[AdvisoryContextSnippet]
    metadata: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        """Validate assembled prompt payload fields."""
        self.prompt_pack_name = require_non_empty_string(
            self.prompt_pack_name, "prompt_pack_name"
        )
        self.system_instructions = require_non_empty_string(
            self.system_instructions, "system_instructions"
        )
        self.analyst_prompt = require_non_empty_string(self.analyst_prompt, "analyst_prompt")
        self.alert_direct_payload = require_non_empty_string(
            self.alert_direct_payload, "alert_direct_payload"
        )
        for snippet in self.advisory_context:
            if not isinstance(snippet, AdvisoryContextSnippet):
                raise ValueError("Field 'advisory_context' must contain AdvisoryContextSnippet.")
        self.advisory_context = tuple(self.advisory_context)
        self.metadata = normalize_mapping(self.metadata, "metadata")


def _render_advisory_context_block(snippets: Sequence[AdvisoryContextSnippet]) -> str:
    """Render advisory context snippets into a deterministic prompt block."""
    if not snippets:
        return "No advisory context snippets were provided."
    lines = []
    for snippet in snippets:
        lines.append(f"- [{snippet.provenance_ref}] {snippet.title}: {snippet.content}")
    return "\n".join(lines)


def assemble_prompt_payload(
    prompt_input: PromptAssemblyInput,
    prompt_packs: Mapping[str, PromptPack],
) -> PromptAssemblyResult:
    """Assemble a deterministic prompt payload using prompt-pack and advisory-context seams."""
    prompt_pack = resolve_prompt_pack(prompt_input.customer_bundle, prompt_packs)

    required_sections = ", ".join(prompt_pack.required_report_sections)
    optional_sections = ", ".join(prompt_pack.allowed_optional_sections) or "none"
    instructions = "\n".join(prompt_pack.customer_instructions) or "No extra instructions."
    advisory_context_block = _render_advisory_context_block(prompt_input.advisory_context_snippets)

    system_instructions = (
        f"Prompt pack: {prompt_pack.pack_name}\n"
        f"Version: {prompt_pack.analysis_prompt_version}\n"
        f"Tone: {prompt_pack.report_tone}\n"
        f"Required sections: {required_sections}\n"
        f"Allowed optional sections: {optional_sections}\n"
        f"Customer instructions:\n{instructions}\n"
        "Treat advisory context as guidance only, not direct alert evidence."
    )
    analyst_prompt = (
        f"Source system: {prompt_input.normalized_alert.source_system}\n"
        f"Source type: {prompt_input.normalized_alert.source_type}\n"
        f"Source ref: {prompt_input.normalized_alert.source_record_ref}\n"
        f"Advisory context:\n{advisory_context_block}"
    )

    return PromptAssemblyResult(
        prompt_pack_name=prompt_pack.pack_name,
        system_instructions=system_instructions,
        analyst_prompt=analyst_prompt,
        alert_direct_payload=prompt_input.normalized_alert.raw_content,
        advisory_context=prompt_input.advisory_context_snippets,
        metadata={"analysis_prompt_version": prompt_pack.analysis_prompt_version},
    )

