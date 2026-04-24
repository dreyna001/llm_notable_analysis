"""Tests for local JSON advisory context provider."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from updated_notable_analysis.core.context import ContextBundle
from updated_notable_analysis.core.models import NormalizedAlert
from updated_notable_analysis.onprem.context_provider import LocalJsonAdvisoryContextProvider


class TestLocalJsonAdvisoryContextProvider(unittest.TestCase):
    """Behavior-focused tests for filesystem-backed advisory context."""

    def _alert(self) -> NormalizedAlert:
        """Return a valid normalized alert fixture."""
        return NormalizedAlert(
            schema_version="1.0",
            source_system="splunk",
            source_type="notable",
            source_record_ref="notable-123",
            received_at="2026-04-21T10:11:12Z",
            raw_content_type="json",
            raw_content='{"event":"failed_auth"}',
        )

    def _bundle(self) -> ContextBundle:
        """Return a context bundle fixture."""
        return ContextBundle(
            bundle_name="soc_context_default",
            enabled_context_sources=("soc_sops",),
            vector_backend="local_json",
            index_names=("soc_sops", "splunk_dictionary"),
            retrieval_limit=5,
            context_budget_chars=1000,
            provenance_required=True,
        )

    def _write_json(self, path: Path, payload: object) -> None:
        """Write a JSON payload for tests."""
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_loads_matching_index_files_and_filters_enabled_sources(self) -> None:
        """Provider should load bundle indexes and filter disabled source types."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_json(
                root / "soc_sops.json",
                {
                    "snippets": [
                        {
                            "source_type": "soc_sops",
                            "source_id": "later",
                            "title": "Later SOP",
                            "content": "Later context.",
                            "provenance_ref": "kb://soc/later",
                            "rank": 20,
                        },
                        {
                            "source_type": "soc_sops",
                            "source_id": "first",
                            "title": "First SOP",
                            "content": "First context.",
                            "provenance_ref": "kb://soc/first",
                            "rank": 1,
                        },
                        {
                            "source_type": "disabled_source",
                            "source_id": "ignored",
                            "title": "Ignored",
                            "content": "Ignored context.",
                            "provenance_ref": "kb://ignored",
                            "rank": 0,
                        },
                    ]
                },
            )
            self._write_json(
                root / "splunk_dictionary.json",
                {
                    "snippets": [
                        {
                            "source_type": "splunk_field_dictionary",
                            "source_id": "disabled-by-source-filter",
                            "title": "Splunk Dictionary",
                            "content": "Dictionary context.",
                            "provenance_ref": "kb://splunk/dict",
                        }
                    ]
                },
            )

            provider = LocalJsonAdvisoryContextProvider(context_dir=root)
            snippets = provider.get_advisory_context(self._alert(), self._bundle())

            self.assertEqual([snippet.source_id for snippet in snippets], ["first", "later"])
            self.assertEqual(snippets[0].source_file, str(root / "soc_sops.json"))
            self.assertEqual(snippets[0].provenance_ref, "kb://soc/first")

    def test_missing_index_file_is_empty_not_failure(self) -> None:
        """Missing optional index files should simply return no snippets."""
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = LocalJsonAdvisoryContextProvider(context_dir=temp_dir)

            self.assertEqual(provider.get_advisory_context(self._alert(), self._bundle()), ())

    def test_malformed_context_file_fails_closed(self) -> None:
        """Malformed configured context files should raise deterministic ValueError."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "soc_sops.json").write_text("{not-json", encoding="utf-8")
            provider = LocalJsonAdvisoryContextProvider(context_dir=root)

            with self.assertRaisesRegex(ValueError, "not valid JSON"):
                provider.get_advisory_context(self._alert(), self._bundle())

    def test_invalid_snippet_contract_fails_closed(self) -> None:
        """Invalid snippet shape should not be silently ignored."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_json(root / "soc_sops.json", {"snippets": [{"source_type": "soc_sops"}]})
            provider = LocalJsonAdvisoryContextProvider(context_dir=root)

            with self.assertRaisesRegex(ValueError, "snippet 0"):
                provider.get_advisory_context(self._alert(), self._bundle())

    def test_requires_existing_context_directory(self) -> None:
        """Configured context directory must exist."""
        with self.assertRaises(ValueError):
            LocalJsonAdvisoryContextProvider(context_dir="/path/that/does/not/exist")


if __name__ == "__main__":
    unittest.main()
