import unittest
from unittest.mock import MagicMock, patch

from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.closed_ticket_retrieval import (
    ClosedTicketRetrievalOutcome,
)
from llm_notable_analysis_onprem_systemd.onprem_service.historical_closed_ticket_grounding import (
    HISTORICAL_CLOSED_TICKET_RULES,
    build_closed_ticket_rag_metadata,
    format_historical_closed_tickets_prompt_block,
    retrieve_historical_closed_tickets_for_first_pass,
)
from llm_notable_analysis_onprem_systemd.onprem_service.local_llm_client import (
    LocalLLMClient,
)
from llm_notable_analysis_onprem_systemd.onprem_service.local_llm_client_nonsdk import (
    LocalLLMClient as NonsdkLocalLLMClient,
)


class _DummyValidator:
    def filter_valid_ttps(self, scored_ttps):
        return scored_ttps


class _FakeHit:
    def __init__(self, ticket_id: str = "t1") -> None:
        self.ticket_id = ticket_id


def _sample_historical_context() -> str:
    return (
        "HISTORICAL_CLOSED_TICKETS\n"
        "Advisory historical closed-ticket excerpts. Not evidence about the current alert.\n"
        "---\n\n"
        "[INC-100 | summary | verdict | score=0.9100]\n"
        "Prior benign closure after validation."
    )


class TestHistoricalClosedTicketGrounding(unittest.TestCase):
    def test_format_block_none_when_empty(self) -> None:
        block = format_historical_closed_tickets_prompt_block("")
        self.assertEqual(block, "HISTORICAL_CLOSED_TICKETS\n(none)\n")

    def test_rules_cover_advisory_and_evidence_boundaries(self) -> None:
        self.assertIn("advisory precedent", HISTORICAL_CLOSED_TICKET_RULES)
        self.assertIn("Never treat HISTORICAL_CLOSED_TICKETS as direct evidence", HISTORICAL_CLOSED_TICKET_RULES)
        self.assertIn("Current alert facts", HISTORICAL_CLOSED_TICKET_RULES)
        self.assertIn("automatic closure", HISTORICAL_CLOSED_TICKET_RULES)
        self.assertIn("Do not add IOCs", HISTORICAL_CLOSED_TICKET_RULES)

    def test_metadata_disabled(self) -> None:
        meta = build_closed_ticket_rag_metadata(enabled=False)
        self.assertEqual(
            meta,
            {
                "closed_ticket_rag_enabled": False,
                "closed_ticket_rag_included": False,
                "closed_ticket_rag_hit_count": 0,
                "closed_ticket_rag_context_chars": 0,
                "closed_ticket_rag_unavailable": False,
            },
        )

    def test_metadata_included_without_payload(self) -> None:
        context = _sample_historical_context()
        meta = build_closed_ticket_rag_metadata(
            enabled=True,
            hits=[_FakeHit(), _FakeHit("t2")],
            context=context,
        )
        self.assertTrue(meta["closed_ticket_rag_enabled"])
        self.assertTrue(meta["closed_ticket_rag_included"])
        self.assertEqual(meta["closed_ticket_rag_hit_count"], 2)
        self.assertEqual(meta["closed_ticket_rag_context_chars"], len(context))
        self.assertFalse(meta["closed_ticket_rag_unavailable"])
        self.assertNotIn("INC-100", str(meta))

    @patch(
        "llm_notable_analysis_onprem_systemd.onprem_service.historical_closed_ticket_grounding.retrieve_closed_tickets_fail_soft"
    )
    def test_retrieve_fail_soft_on_disabled(self, mock_retrieve) -> None:
        config = Config(CLOSED_TICKET_RAG_ENABLED=False)
        context, meta = retrieve_historical_closed_tickets_for_first_pass(
            config, "alert body"
        )
        self.assertEqual(context, "")
        self.assertFalse(meta["closed_ticket_rag_enabled"])
        mock_retrieve.assert_not_called()

    @patch(
        "llm_notable_analysis_onprem_systemd.onprem_service.historical_closed_ticket_grounding.retrieve_closed_tickets_fail_soft"
    )
    def test_retrieve_enabled_returns_context_and_metadata(self, mock_retrieve) -> None:
        context = _sample_historical_context()
        mock_retrieve.return_value = ClosedTicketRetrievalOutcome(
            hits=[_FakeHit()],
            context=context,
        )
        config = Config(CLOSED_TICKET_RAG_ENABLED=True)

        out_context, meta = retrieve_historical_closed_tickets_for_first_pass(
            config, "powershell alert"
        )

        self.assertEqual(out_context, context)
        self.assertTrue(meta["closed_ticket_rag_included"])
        self.assertEqual(meta["closed_ticket_rag_hit_count"], 1)
        mock_retrieve.assert_called_once_with(config=config, alert_text="powershell alert")

    @patch(
        "llm_notable_analysis_onprem_systemd.onprem_service.historical_closed_ticket_grounding.retrieve_closed_tickets_fail_soft",
    )
    def test_retrieve_marks_unavailable_on_soft_error_outcome(self, mock_retrieve) -> None:
        mock_retrieve.return_value = ClosedTicketRetrievalOutcome(
            hits=[],
            context="",
            error="postgres unavailable",
        )
        config = Config(CLOSED_TICKET_RAG_ENABLED=True)
        context, meta = retrieve_historical_closed_tickets_for_first_pass(config, "alert")
        self.assertEqual(context, "")
        self.assertTrue(meta["closed_ticket_rag_unavailable"])
        self.assertIn("postgres unavailable", meta["closed_ticket_rag_unavailable_reason"])


class TestHistoricalClosedTicketPromptIntegration(unittest.TestCase):
    def _assert_prompt_lane_order(self, prompt: str) -> None:
        alert_idx = prompt.index("SECURITY ALERT INPUT:")
        soc_idx = prompt.index("SOC_OPERATIONAL_CONTEXT", alert_idx)
        soc_rules_idx = prompt.index("SOC CONTEXT RULES", soc_idx)
        historical_idx = prompt.index("HISTORICAL_CLOSED_TICKETS", soc_rules_idx)
        historical_rules_idx = prompt.index("HISTORICAL CLOSED-TICKET RULES", historical_idx)
        rules_idx = prompt.index("RULES:", historical_rules_idx)
        self.assertLess(soc_idx, soc_rules_idx)
        self.assertLess(soc_rules_idx, historical_idx)
        self.assertLess(historical_idx, historical_rules_idx)
        self.assertLess(historical_rules_idx, rules_idx)

    def test_sdk_build_prompt_includes_historical_lane_and_rules(self) -> None:
        client = LocalLLMClient(config=Config(), ttp_validator=_DummyValidator())
        prompt = client._build_prompt(
            "alert text",
            soc_operational_context="SOC_OPERATIONAL_CONTEXT\n[1] kb snippet\n",
            historical_closed_tickets_context=_sample_historical_context(),
        )
        self.assertIn("HISTORICAL CLOSED-TICKET RULES", prompt)
        self.assertIn("Prior benign closure", prompt)
        self._assert_prompt_lane_order(prompt)

    def test_nonsdk_build_prompt_includes_historical_lane_and_rules(self) -> None:
        client = NonsdkLocalLLMClient(config=Config(), ttp_validator=_DummyValidator())
        prompt = client._build_prompt(
            "alert text",
            soc_operational_context="SOC_OPERATIONAL_CONTEXT\n[1] kb snippet\n",
            historical_closed_tickets_context=_sample_historical_context(),
        )
        self.assertIn("HISTORICAL CLOSED-TICKET RULES", prompt)
        self.assertIn("Prior benign closure", prompt)
        self._assert_prompt_lane_order(prompt)

    def test_build_prompt_shows_none_lane_when_historical_missing(self) -> None:
        client = LocalLLMClient(config=Config(), ttp_validator=_DummyValidator())
        prompt = client._build_prompt("alert text")
        self.assertIn("HISTORICAL_CLOSED_TICKETS\n(none)", prompt)
        self.assertIn("HISTORICAL CLOSED-TICKET RULES", prompt)

    @patch(
        "llm_notable_analysis_onprem_systemd.onprem_service.local_llm_client.retrieve_historical_closed_tickets_for_first_pass",
        return_value=(_sample_historical_context(), {
            "closed_ticket_rag_enabled": True,
            "closed_ticket_rag_included": True,
            "closed_ticket_rag_hit_count": 1,
            "closed_ticket_rag_context_chars": 42,
            "closed_ticket_rag_unavailable": False,
        }),
    )
    @patch(
        "llm_notable_analysis_onprem_systemd.onprem_service.local_llm_client.LocalLLMClient._build_soc_operational_context",
        return_value="",
    )
    def test_analyze_alert_metadata_records_closed_ticket_lane(
        self,
        _mock_soc,
        _mock_historical,
    ) -> None:
        client = LocalLLMClient(
            config=Config(CLOSED_TICKET_RAG_ENABLED=True),
            ttp_validator=_DummyValidator(),
        )
        complete_result = MagicMock()
        complete_result.text = (
            '{"alert_reconciliation":{"verdict":"unknown","confidence":"0.5",'
            '"one_sentence_summary":"test","decision_drivers":[],"recommended_actions":[]},'
            '"competing_hypotheses":[],"evidence_vs_inference":{"evidence":[],"inferences":[]},'
            '"ioc_extraction":{"urls":[]},"ttp_analysis":[]}'
        )
        complete_result.latency_seconds = 0.1
        client._sdk_client.complete = MagicMock(return_value=complete_result)

        result = client.analyze_alert("powershell encoded command")

        metadata = result["metadata"]
        self.assertTrue(metadata["closed_ticket_rag_enabled"])
        self.assertTrue(metadata["closed_ticket_rag_included"])
        self.assertEqual(metadata["closed_ticket_rag_hit_count"], 1)
        self.assertEqual(metadata["closed_ticket_rag_context_chars"], 42)
        self.assertFalse(metadata["closed_ticket_rag_unavailable"])


if __name__ == "__main__":
    unittest.main()
