import unittest

from llm_notable_analysis_onprem.onprem_service import local_llm_client as llm_client_module
from llm_notable_analysis_onprem.onprem_service.config import Config
from llm_notable_analysis_onprem.onprem_service.local_llm_client import (
    LocalLLMClient,
    _normalize_and_fill_defaults,
    _validate_spl_query_contract,
    extract_json_object,
    extract_scored_ttps,
    strip_llm_thinking_preamble,
    validate_competing_hypotheses_balance,
    validate_content_policies,
    validate_response_schema,
)


class _DummyValidator:
    def filter_valid_ttps(self, scored_ttps):
        return scored_ttps


class TestLocalLlmClientContract(unittest.TestCase):
    def test_normalize_defaults_populates_alert_reconciliation_shape(self) -> None:
        parsed = {
            "ttp_analysis": [],
            "ioc_extraction": {},
            "evidence_vs_inference": {},
            "competing_hypotheses": [],
        }

        out = _normalize_and_fill_defaults(parsed)

        self.assertIn("alert_reconciliation", out)
        self.assertEqual(
            out["alert_reconciliation"],
            {
                "verdict": "",
                "confidence": "",
                "one_sentence_summary": "",
                "decision_drivers": [],
                "recommended_actions": [],
            },
        )
        is_valid, err = validate_response_schema(out)
        self.assertTrue(is_valid, msg=err)

    def test_extract_json_object_from_preamble_and_trailing_text(self) -> None:
        raw = 'model preamble {"k": 1, "nested": {"v": 2}} trailing'
        extracted, note = extract_json_object(raw)
        self.assertEqual(extracted, '{"k": 1, "nested": {"v": 2}}')
        self.assertIsNotNone(note)

    def test_strip_llm_thinking_preamble_keeps_tail_after_marker(self) -> None:
        mark = llm_client_module._QWEN_THINK_END
        raw = "preamble" + mark + '{"a": 1}'
        self.assertEqual(strip_llm_thinking_preamble(raw), '{"a": 1}')

    def test_strip_llm_thinking_preamble_no_marker_unchanged(self) -> None:
        raw = '{"b": 2}'
        self.assertEqual(strip_llm_thinking_preamble(raw), '{"b": 2}')

    def test_validate_content_policies_rejects_url_outside_ioc_urls(self) -> None:
        payload = {
            "alert_reconciliation": {
                "verdict": "likely malicious",
                "confidence": "0.7",
                "one_sentence_summary": "N/A",
                "decision_drivers": [],
                "recommended_actions": [],
            },
            "competing_hypotheses": [],
            "evidence_vs_inference": {
                "evidence": ["see https://bad.example/path"],
                "inferences": [],
            },
            "ioc_extraction": {"urls": []},
            "ttp_analysis": [],
        }
        ok, err = validate_content_policies(payload)
        self.assertFalse(ok)
        self.assertIn("Disallowed URL outside ioc_extraction.urls", err or "")

    def test_extract_scored_ttps_normalizes_score_sources(self) -> None:
        parsed = {
            "ttp_analysis": [
                {
                    "ttp_id": "T1059.001",
                    "ttp_name": "PowerShell",
                    "confidence_score": "0.62",
                    "explanation": "test",
                    "evidence_fields": ["process=powershell.exe"],
                },
                {
                    "ttp_id": "T1110",
                    "ttp_name": "Brute Force",
                    "confidence": 0.33,
                    "explanation": "test2",
                    "evidence_fields": [],
                },
            ]
        }

        scored = extract_scored_ttps(parsed)
        self.assertEqual(len(scored), 2)
        self.assertEqual(scored[0]["score"], 0.62)
        self.assertEqual(scored[1]["score"], 0.33)

    def test_normalize_defaults_coerces_alert_reconciliation_types(self) -> None:
        parsed = {
            "ttp_analysis": [],
            "ioc_extraction": {},
            "evidence_vs_inference": {},
            "competing_hypotheses": [],
            "alert_reconciliation": {
                "verdict": 1,
                "confidence": 0.95,
                "one_sentence_summary": None,
                "decision_drivers": "driver-one",
                "recommended_actions": {"action": "reset"},
            },
        }
        out = _normalize_and_fill_defaults(parsed)
        ar = out["alert_reconciliation"]

        self.assertEqual(ar["verdict"], "1")
        self.assertEqual(ar["confidence"], "0.95")
        self.assertEqual(ar["one_sentence_summary"], "")
        self.assertEqual(ar["decision_drivers"], ["driver-one"])
        self.assertEqual(ar["recommended_actions"], ["{'action': 'reset'}"])

    def test_validate_content_policies_rejects_placeholder_token(self) -> None:
        payload = {
            "alert_reconciliation": {
                "verdict": "likely malicious",
                "confidence": "0.7",
                "one_sentence_summary": "placeholder used here",
                "decision_drivers": [],
                "recommended_actions": [],
            },
            "competing_hypotheses": [],
            "evidence_vs_inference": {"evidence": [], "inferences": []},
            "ioc_extraction": {"urls": []},
            "ttp_analysis": [],
        }
        ok, err = validate_content_policies(payload)
        self.assertFalse(ok)
        self.assertIn("Disallowed PLACEHOLDER token", err or "")

    def test_build_prompt_includes_soc_context_rules_block(self) -> None:
        client = LocalLLMClient(config=Config(), ttp_validator=_DummyValidator())
        prompt = client._build_prompt(
            "alert text",
            soc_operational_context="SOC_OPERATIONAL_CONTEXT\n[1] [a :: b] c\n",
        )
        self.assertIn("SOC CONTEXT RULES", prompt)
        self.assertIn("SOC_OPERATIONAL_CONTEXT", prompt)
        self.assertNotIn("SPL QUERY GENERATION (Enabled)", prompt)

    def test_build_prompt_includes_spl_rules_when_enabled(self) -> None:
        client = LocalLLMClient(
            config=Config(SPL_QUERY_GENERATION_ENABLED=True),
            ttp_validator=_DummyValidator(),
        )
        prompt = client._build_prompt("alert text")
        self.assertIn("SPL QUERY GENERATION (Enabled)", prompt)

    def test_normalize_defaults_strips_spl_fields_when_disabled(self) -> None:
        parsed = {
            "alert_reconciliation": {},
            "competing_hypotheses": [
                {
                    "hypothesis_type": "benign",
                    "hypothesis": "normal admin action",
                    "query_strategy": "resolve_unknown",
                    "primary_spl_query": "search user=admin",
                    "why_this_query": "test",
                    "supports_if": "test",
                    "weakens_if": "test",
                }
            ],
            "evidence_vs_inference": {},
            "ioc_extraction": {},
            "ttp_analysis": [],
        }
        out = _normalize_and_fill_defaults(parsed, spl_query_enabled=False)
        self.assertEqual(len(out["competing_hypotheses"]), 1)
        hyp = out["competing_hypotheses"][0]
        self.assertNotIn("query_strategy", hyp)
        self.assertNotIn("primary_spl_query", hyp)

    def test_normalize_defaults_keeps_spl_fields_when_enabled(self) -> None:
        parsed = {
            "alert_reconciliation": {},
            "competing_hypotheses": [
                {
                    "hypothesis_type": "benign",
                    "hypothesis": "normal admin action",
                    "query_strategy": "Resolve_Unknown",
                    "primary_spl_query": " search user=admin ",
                    "why_this_query": " test ",
                    "supports_if": " yes ",
                    "weakens_if": " no ",
                }
            ],
            "evidence_vs_inference": {},
            "ioc_extraction": {},
            "ttp_analysis": [],
        }
        out = _normalize_and_fill_defaults(parsed, spl_query_enabled=True)
        hyp = out["competing_hypotheses"][0]
        self.assertEqual(hyp["query_strategy"], "resolve_unknown")
        self.assertEqual(hyp["primary_spl_query"], "search user=admin")
        self.assertEqual(hyp["why_this_query"], "test")

    def test_validate_competing_hypotheses_strict_requires_three_and_three(self) -> None:
        payload = {
            "competing_hypotheses": [
                {"hypothesis_type": "benign"},
                {"hypothesis_type": "benign"},
                {"hypothesis_type": "benign"},
                {"hypothesis_type": "adversary"},
                {"hypothesis_type": "adversary"},
                {"hypothesis_type": "unknown"},
            ]
        }
        ok, err = validate_competing_hypotheses_balance(payload, strict=True)
        self.assertFalse(ok)
        self.assertIn("hypothesis_type", err or "")

    def test_validate_spl_query_contract_rejects_placeholder_and_pseudo(self) -> None:
        payload = {
            "competing_hypotheses": [
                {
                    "hypothesis_type": "benign",
                    "query_strategy": "resolve_unknown",
                    "primary_spl_query": "search index=<INDEX> ...",
                    "why_this_query": "a",
                    "supports_if": "b",
                    "weakens_if": "c",
                },
                {
                    "hypothesis_type": "benign",
                    "query_strategy": "resolve_unknown",
                    "primary_spl_query": "search user=foo",
                    "why_this_query": "a",
                    "supports_if": "b",
                    "weakens_if": "c",
                },
                {
                    "hypothesis_type": "benign",
                    "query_strategy": "resolve_unknown",
                    "primary_spl_query": "search user=bar",
                    "why_this_query": "a",
                    "supports_if": "b",
                    "weakens_if": "c",
                },
                {
                    "hypothesis_type": "adversary",
                    "query_strategy": "check_contradiction",
                    "primary_spl_query": "search user=baz",
                    "why_this_query": "a",
                    "supports_if": "b",
                    "weakens_if": "c",
                },
                {
                    "hypothesis_type": "adversary",
                    "query_strategy": "check_contradiction",
                    "primary_spl_query": "search user=qux",
                    "why_this_query": "a",
                    "supports_if": "b",
                    "weakens_if": "c",
                },
                {
                    "hypothesis_type": "adversary",
                    "query_strategy": "check_contradiction",
                    "primary_spl_query": "search user=zzz",
                    "why_this_query": "a",
                    "supports_if": "b",
                    "weakens_if": "c",
                },
            ]
        }
        ok, err = _validate_spl_query_contract(payload)
        self.assertFalse(ok)
        self.assertTrue(
            "placeholder token" in (err or "") or "pseudo-query" in (err or "")
        )


if __name__ == "__main__":
    unittest.main()
