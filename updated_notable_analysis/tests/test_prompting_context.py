"""Deterministic tests for prompt and context seam contracts."""

from __future__ import annotations

import unittest

from updated_notable_analysis.core.config_models import CustomerBundle
from updated_notable_analysis.core.context import normalize_advisory_context, resolve_context_bundle
from updated_notable_analysis.core.models import AdvisoryContextSnippet, NormalizedAlert
from updated_notable_analysis.core.prompting import (
    PromptAssemblyInput,
    PromptAssemblyResult,
    assemble_prompt_payload,
    resolve_prompt_pack,
)
from updated_notable_analysis.prompt_packs import DEFAULT_PROMPT_PACKS
from updated_notable_analysis.profiles import DEFAULT_CONTEXT_BUNDLES


class TestPromptingAndContextSeams(unittest.TestCase):
    """Behavior-focused tests for Diff 3 prompt and context seam contracts."""

    def _build_alert(self) -> NormalizedAlert:
        """Return a valid normalized alert fixture."""
        return NormalizedAlert(
            schema_version="1.0",
            source_system="splunk",
            source_type="notable",
            source_record_ref="notable-123",
            received_at="2026-04-21T10:11:12Z",
            raw_content_type="json",
            raw_content='{"event":"failed_auth","user":"jdoe"}',
        )

    def _build_customer_bundle(self, prompt_pack_name: str, context_bundle_name: str) -> CustomerBundle:
        """Return a valid customer-bundle fixture."""
        return CustomerBundle(
            prompt_pack_name=prompt_pack_name,
            context_bundle_name=context_bundle_name,
            query_policy_bundle_name="spl_readonly_default",
            sink_bundle_name="local_reports_default",
            input_mapping_bundle_name="splunk_notable_default",
        )

    def test_prompt_pack_resolution_fails_fast_for_unknown_pack(self) -> None:
        """Unknown prompt-pack selection should fail with a deterministic error."""
        bundle = self._build_customer_bundle(
            prompt_pack_name="unknown_pack",
            context_bundle_name="soc_context_default",
        )
        with self.assertRaises(ValueError):
            resolve_prompt_pack(bundle, DEFAULT_PROMPT_PACKS)

    def test_context_bundle_resolution_fails_fast_for_unknown_bundle(self) -> None:
        """Unknown context-bundle selection should fail with a deterministic error."""
        bundle = self._build_customer_bundle(
            prompt_pack_name="soc_standard_v1",
            context_bundle_name="unknown_context_bundle",
        )
        with self.assertRaises(ValueError):
            resolve_context_bundle(bundle, DEFAULT_CONTEXT_BUNDLES)

    def test_prompt_assembly_keeps_advisory_context_separate_from_alert_payload(self) -> None:
        """Prompt assembly should preserve advisory context separation from direct alert payload."""
        alert = self._build_alert()
        bundle = self._build_customer_bundle(
            prompt_pack_name="soc_standard_v1",
            context_bundle_name="soc_context_default",
        )
        snippets = (
            AdvisoryContextSnippet(
                source_type="sop",
                source_id="sop-42",
                title="Authentication SOP",
                content="Escalate after three suspicious failed authentications.",
                provenance_ref="kb://soc/sop/auth-42",
            ),
        )
        prompt_input = PromptAssemblyInput(
            normalized_alert=alert,
            customer_bundle=bundle,
            advisory_context_snippets=snippets,
        )
        result = assemble_prompt_payload(prompt_input, DEFAULT_PROMPT_PACKS)

        self.assertEqual(result.alert_direct_payload, alert.raw_content)
        self.assertEqual(result.advisory_context, snippets)
        self.assertIn("Authentication SOP", result.analyst_prompt)
        self.assertNotIn("Authentication SOP", result.alert_direct_payload)

    def test_prompt_variation_is_bundle_selected_without_workflow_branching(self) -> None:
        """Different prompt packs should produce different instructions from the same input alert."""
        alert = self._build_alert()
        snippets = (
            AdvisoryContextSnippet(
                source_type="dictionary",
                source_id="dict-1",
                title="Splunk field guidance",
                content="Review src_ip and user correlation for this notable type.",
                provenance_ref="kb://splunk/field-dict/notable",
            ),
        )
        standard_bundle = self._build_customer_bundle(
            prompt_pack_name="soc_standard_v1",
            context_bundle_name="soc_context_default",
        )
        executive_bundle = self._build_customer_bundle(
            prompt_pack_name="soc_executive_v1",
            context_bundle_name="soc_context_default",
        )

        standard_result = assemble_prompt_payload(
            PromptAssemblyInput(
                normalized_alert=alert,
                customer_bundle=standard_bundle,
                advisory_context_snippets=snippets,
            ),
            DEFAULT_PROMPT_PACKS,
        )
        executive_result = assemble_prompt_payload(
            PromptAssemblyInput(
                normalized_alert=alert,
                customer_bundle=executive_bundle,
                advisory_context_snippets=snippets,
            ),
            DEFAULT_PROMPT_PACKS,
        )

        self.assertNotEqual(standard_result.prompt_pack_name, executive_result.prompt_pack_name)
        self.assertIn("Tone: analyst_neutral", standard_result.system_instructions)
        self.assertIn("Tone: executive_brief", executive_result.system_instructions)

    def test_normalize_advisory_context_applies_limit_and_budget(self) -> None:
        """Context normalization should enforce retrieval and character budgets."""
        snippets = (
            AdvisoryContextSnippet(
                source_type="sop",
                source_id="one",
                title="One",
                content="12345",
                provenance_ref="ref://one",
            ),
            AdvisoryContextSnippet(
                source_type="sop",
                source_id="two",
                title="Two",
                content="67890",
                provenance_ref="ref://two",
            ),
        )
        normalized = normalize_advisory_context(
            snippets,
            retrieval_limit=5,
            # Budget allows first rendered line but not both lines.
            context_budget_chars=30,
        )
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0].source_id, "one")

    def test_normalize_advisory_context_budget_counts_rendered_line(self) -> None:
        """Budget checks should include provenance and title, not content only."""
        snippet = AdvisoryContextSnippet(
            source_type="sop",
            source_id="rendered-size",
            title="Very long advisory title",
            content="x",
            provenance_ref="kb://this/provenance/path/is/long",
        )
        normalized = normalize_advisory_context(
            (snippet,),
            retrieval_limit=1,
            # Old logic would include the snippet because content length is 1.
            context_budget_chars=1,
        )
        self.assertEqual(normalized, ())

    def test_normalize_advisory_context_invalid_limits_raise_value_error(self) -> None:
        """Malformed numeric limits should fail with deterministic ValueError."""
        snippet = AdvisoryContextSnippet(
            source_type="sop",
            source_id="limits",
            title="title",
            content="content",
            provenance_ref="ref://limits",
        )
        with self.assertRaises(ValueError):
            normalize_advisory_context(
                (snippet,),
                retrieval_limit="5",  # type: ignore[arg-type]
                context_budget_chars=100,
            )
        with self.assertRaises(ValueError):
            normalize_advisory_context(
                (snippet,),
                retrieval_limit=1,
                context_budget_chars="10",  # type: ignore[arg-type]
            )

    def test_prompt_assembly_result_rejects_non_string_payload_fields(self) -> None:
        """PromptAssemblyResult should enforce required string contract fields."""
        with self.assertRaises(ValueError):
            PromptAssemblyResult(
                prompt_pack_name=123,  # type: ignore[arg-type]
                system_instructions=456,  # type: ignore[arg-type]
                analyst_prompt=True,  # type: ignore[arg-type]
                alert_direct_payload=object(),  # type: ignore[arg-type]
                advisory_context=(),
            )


if __name__ == "__main__":
    unittest.main()

