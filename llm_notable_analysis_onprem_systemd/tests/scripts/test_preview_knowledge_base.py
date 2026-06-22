"""Tests for preview synthetic Knowledge Base retrieval."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from preview_knowledge_base import (  # noqa: E402
    retrieve_preview_knowledge_base,
)


class PreviewKnowledgeBaseTests(unittest.TestCase):
    def test_escalation_question_returns_tier2_sop(self) -> None:
        sources = retrieve_preview_knowledge_base(
            "Should I escalate this to Tier 2?"
        )
        sections = {source.section for source in sources}
        self.assertIn("knowledge_base.sop_tier2_escalation", sections)

    def test_isolation_question_returns_host_isolation_sop(self) -> None:
        sources = retrieve_preview_knowledge_base(
            "How do I isolate the compromised laptop?"
        )
        sections = {source.section for source in sources}
        self.assertIn("knowledge_base.sop_host_isolation", sections)

    def test_hva_question_returns_registry_for_db_prod(self) -> None:
        sources = retrieve_preview_knowledge_base(
            "Is db-prod-01 a high value asset?"
        )
        sections = {source.section for source in sources}
        self.assertIn("knowledge_base.hva_registry", sections)
        hva_text = next(
            source.text
            for source in sources
            if source.section == "knowledge_base.hva_registry"
        )
        self.assertIn("db-prod-01.corp.local", hva_text)

    def test_lateral_movement_question_can_return_network_and_hva_docs(self) -> None:
        sources = retrieve_preview_knowledge_base(
            "RDP lateral movement to db-prod-01 — network segment and HVA handling?"
        )
        sections = {source.section for source in sources}
        self.assertIn("knowledge_base.network_architecture", sections)
        self.assertIn("knowledge_base.hva_registry", sections)

    def test_unrelated_question_returns_no_kb_sources(self) -> None:
        sources = retrieve_preview_knowledge_base("What is the weather today?")
        self.assertEqual(sources, [])


if __name__ == "__main__":
    unittest.main()
