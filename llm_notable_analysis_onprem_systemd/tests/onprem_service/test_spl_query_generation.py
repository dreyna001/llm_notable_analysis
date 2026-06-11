import unittest
from typing import Any, Dict, List

from llm_notable_analysis_onprem_systemd.onprem_service.spl_query_generation import (
    build_spl_query_grounding_refs,
    build_spl_query_generation_prompt,
    merge_spl_query_fields_by_position,
    normalize_competing_hypotheses,
    validate_spl_query_contract,
)


def _valid_hypotheses() -> List[Dict[str, Any]]:
    return [
        {
            "hypothesis_type": "benign",
            "hypothesis": "admin maintenance",
            "query_strategy": "resolve_unknown",
            "primary_spl_query": "search user=admin | head 50",
            "why_this_query": "check normal admin access pattern",
            "supports_if": "access frequency is routine",
            "weakens_if": "new host or unusual command appears",
        },
        {
            "hypothesis_type": "benign",
            "hypothesis": "scheduled task",
            "query_strategy": "resolve_unknown",
            "primary_spl_query": "search task_name=*backup* | head 50",
            "why_this_query": "confirm expected scheduler activity",
            "supports_if": "task owner and time are expected",
            "weakens_if": "unexpected task owner appears",
        },
        {
            "hypothesis_type": "benign",
            "hypothesis": "service account routine",
            "query_strategy": "check_contradiction",
            "primary_spl_query": "search user=svc_backup action=logon | head 50",
            "why_this_query": "validate historical service account behavior",
            "supports_if": "similar events appear over prior days",
            "weakens_if": "activity appears only once in new context",
        },
        {
            "hypothesis_type": "adversary",
            "hypothesis": "credential theft",
            "query_strategy": "resolve_unknown",
            "primary_spl_query": "search EventCode=4624 user=admin | stats count by src_ip",
            "why_this_query": "identify unusual source concentration",
            "supports_if": "new source IP dominates logons",
            "weakens_if": "source profile matches baseline",
        },
        {
            "hypothesis_type": "adversary",
            "hypothesis": "privilege misuse",
            "query_strategy": "check_contradiction",
            "primary_spl_query": "search EventCode=4672 user=admin | head 50",
            "why_this_query": "inspect privileged operations around alert time",
            "supports_if": "new privileged operations appear",
            "weakens_if": "no elevated actions are present",
        },
        {
            "hypothesis_type": "adversary",
            "hypothesis": "remote execution chain",
            "query_strategy": "resolve_unknown",
            "primary_spl_query": "search process_name=powershell.exe parent_process=wmiprvse.exe | head 50",
            "why_this_query": "confirm suspicious remote exec ancestry",
            "supports_if": "parent-child relation is present",
            "weakens_if": "no suspicious ancestry found",
        },
    ]


class TestSplQueryGeneration(unittest.TestCase):
    def test_build_spl_query_generation_prompt_contains_inputs(self) -> None:
        prompt = build_spl_query_generation_prompt(
            alert_text="Suspicious logon alert",
            hypotheses=normalize_competing_hypotheses(
                _valid_hypotheses(),
                spl_query_enabled=False,
            ),
            soc_operational_context="SOC_OPERATIONAL_CONTEXT\n[1] [dict] use index=main",
            spl_query_grounding_context="SPL_QUERY_GROUNDING_CONTEXT\n[1] [spl] index=main",
            alert_time="2026-01-01T00:00:00Z",
        )
        self.assertIn("Suspicious logon alert", prompt)
        self.assertIn("INPUT_COMPETING_HYPOTHESES", prompt)
        self.assertIn("SOC_OPERATIONAL_CONTEXT", prompt)
        self.assertIn("SPL_QUERY_GROUNDING_CONTEXT", prompt)
        self.assertIn("Return ONLY a single JSON object", prompt)
        self.assertIn("unvalidated draft investigation guidance", prompt)
        self.assertIn("was executed or that results were observed", prompt)
        self.assertIn("When ALERT_TIME is provided", prompt)
        self.assertIn("earliest/latest", prompt)
        self.assertIn("observable fields from the alert", prompt)
        self.assertIn("hypothesis uncertainty it is testing", prompt)
        self.assertIn("2026-01-01T00:00:00Z", prompt)

    def test_merge_spl_query_fields_by_position_keeps_base_hypotheses(self) -> None:
        base = normalize_competing_hypotheses(_valid_hypotheses(), spl_query_enabled=False)
        generated_payload = {
            "competing_hypotheses": [
                {
                    "query_strategy": "Resolve_Unknown",
                    "primary_spl_query": " search user=admin | head 50 ",
                    "why_this_query": " check baseline ",
                    "supports_if": " baseline exists ",
                    "weakens_if": " no baseline ",
                }
            ]
        }
        merged = merge_spl_query_fields_by_position(
            base_hypotheses=base,
            generated_payload=generated_payload,
        )

        self.assertEqual(len(merged), 6)
        self.assertEqual(merged[0]["hypothesis"], base[0]["hypothesis"])
        self.assertEqual(merged[0]["query_strategy"], "resolve_unknown")
        self.assertEqual(merged[0]["primary_spl_query"], "search user=admin | head 50")
        self.assertEqual(merged[1]["query_strategy"], "")

    def test_merge_spl_query_fields_adds_grounding_refs_when_query_uses_context(
        self,
    ) -> None:
        base = normalize_competing_hypotheses(_valid_hypotheses(), spl_query_enabled=False)
        generated_payload = {
            "competing_hypotheses": [
                {
                    "query_strategy": "resolve_unknown",
                    "primary_spl_query": "search index=wineventlog user=admin | head 50",
                    "why_this_query": "check authentication index",
                    "supports_if": "events are present",
                    "weakens_if": "events are absent",
                }
            ]
        }
        grounding_context = (
            "SPL_QUERY_GROUNDING_CONTEXT\n"
            "[1] [splunk_index_field_reference.txt :: Authentication] "
            "Use index=wineventlog for Windows authentication events.\n"
        )

        merged = merge_spl_query_fields_by_position(
            base_hypotheses=base,
            generated_payload=generated_payload,
            spl_query_grounding_context=grounding_context,
        )

        self.assertEqual(
            merged[0]["primary_spl_query_grounding_refs"],
            [
                {
                    "source_file": "splunk_index_field_reference.txt",
                    "section_path": "Authentication",
                }
            ],
        )

    def test_validate_spl_query_contract_accepts_valid_payload(self) -> None:
        payload = {"competing_hypotheses": _valid_hypotheses()}
        ok, err = validate_spl_query_contract(payload)
        self.assertTrue(ok, msg=err)

    def test_validate_spl_query_contract_rejects_placeholder_index_macro_and_datamodel(
        self,
    ) -> None:
        disallowed_queries = [
            "search user=admin index=main",
            "search user=admin sourcetype=wineventlog",
            "search user=admin `my_macro`",
            "search user=admin datamodel=Authentication",
            "search user=<USER>",
            "search user=admin ...",
        ]
        for q in disallowed_queries:
            payload = {"competing_hypotheses": _valid_hypotheses()}
            payload["competing_hypotheses"][0]["primary_spl_query"] = q
            ok, err = validate_spl_query_contract(payload)
            self.assertFalse(ok, msg=f"query unexpectedly accepted: {q}")
            self.assertIsNotNone(err)

    def test_validate_spl_query_contract_allows_tokens_from_spl_grounding(
        self,
    ) -> None:
        query = (
            "search index=wineventlog sourcetype=XmlWinEventLog "
            "`auth_failures` datamodel=Authentication | head 50"
        )
        payload = {"competing_hypotheses": _valid_hypotheses()}
        payload["competing_hypotheses"][0]["primary_spl_query"] = query
        grounding_context = (
            "SPL_QUERY_GROUNDING_CONTEXT\n"
            "[1] [splunk_reference.txt :: Authentication] "
            "Approved SPL tokens: index=wineventlog sourcetype=XmlWinEventLog "
            "`auth_failures` datamodel=Authentication.\n"
        )

        ok, err = validate_spl_query_contract(
            payload,
            alert_text="Suspicious admin logon",
            spl_query_grounding_context=grounding_context,
            require_spl_grounding=True,
        )

        self.assertTrue(ok, msg=err)

    def test_validate_spl_query_contract_rejects_ungrounded_environment_token(
        self,
    ) -> None:
        payload = {"competing_hypotheses": _valid_hypotheses()}
        payload["competing_hypotheses"][0][
            "primary_spl_query"
        ] = "search index=secret_index user=admin | head 50"

        ok, err = validate_spl_query_contract(
            payload,
            alert_text="Suspicious admin logon",
            spl_query_grounding_context=(
                "SPL_QUERY_GROUNDING_CONTEXT\n"
                "[1] [splunk_reference.txt :: Authentication] index=wineventlog\n"
            ),
            require_spl_grounding=True,
        )

        self.assertFalse(ok)
        self.assertIn("ungrounded index", err or "")

    def test_build_spl_query_grounding_refs_returns_source_sections(self) -> None:
        refs = build_spl_query_grounding_refs(
            "search index=wineventlog sourcetype=XmlWinEventLog | head 50",
            (
                "SPL_QUERY_GROUNDING_CONTEXT\n"
                "[1] [splunk_reference.txt :: Authentication] "
                "index=wineventlog sourcetype=XmlWinEventLog\n"
            ),
        )

        self.assertEqual(
            refs,
            [
                {
                    "source_file": "splunk_reference.txt",
                    "section_path": "Authentication",
                }
            ],
        )

    def test_normalize_competing_hypotheses_suppresses_spl_fields_when_disabled(
        self,
    ) -> None:
        normalized = normalize_competing_hypotheses(
            _valid_hypotheses(),
            spl_query_enabled=False,
        )
        self.assertEqual(len(normalized), 6)
        for hyp in normalized:
            self.assertNotIn("query_strategy", hyp)
            self.assertNotIn("primary_spl_query", hyp)
            self.assertNotIn("why_this_query", hyp)
            self.assertNotIn("supports_if", hyp)
            self.assertNotIn("weakens_if", hyp)

    def test_normalize_competing_hypotheses_trims_and_lowercases_when_enabled(
        self,
    ) -> None:
        value = _valid_hypotheses()
        value[0]["query_strategy"] = " Resolve_Unknown "
        value[0]["primary_spl_query"] = " search user=admin | head 50 "
        value[0]["why_this_query"] = " rationale "

        normalized = normalize_competing_hypotheses(value, spl_query_enabled=True)
        first = normalized[0]

        self.assertEqual(first["query_strategy"], "resolve_unknown")
        self.assertEqual(first["primary_spl_query"], "search user=admin | head 50")
        self.assertEqual(first["why_this_query"], "rationale")


if __name__ == "__main__":
    unittest.main()
