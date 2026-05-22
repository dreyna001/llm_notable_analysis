import unittest
from typing import Any, Dict, List

from llm_notable_analysis_onprem_systemd.onprem_service.elastic_query_generation import (
    build_elastic_query_generation_prompt,
    build_elastic_query_grounding_refs,
    merge_elastic_query_fields_by_position,
    normalize_competing_hypotheses,
    validate_elastic_query_contract,
)


def _primary_query(index_pattern: str = "logs-auth") -> Dict[str, Any]:
    return {
        "index_pattern": index_pattern,
        "body": {
            "size": 25,
            "query": {
                "bool": {
                    "filter": [
                        {"range": {"@timestamp": {"gte": "now-24h", "lte": "now"}}},
                        {"term": {"user.name": "admin"}},
                    ]
                }
            },
        },
    }


def _valid_hypotheses() -> List[Dict[str, Any]]:
    base: List[Dict[str, Any]] = []
    for idx in range(6):
        base.append(
            {
                "hypothesis_type": "benign" if idx < 3 else "adversary",
                "hypothesis": f"hypothesis {idx}",
                "query_strategy": "resolve_unknown",
                "primary_elastic_query": _primary_query(),
                "why_this_query": "check authentication events",
                "supports_if": "matching events are routine",
                "weakens_if": "matching events are absent or anomalous",
            }
        )
    return base


class TestElasticQueryGeneration(unittest.TestCase):
    def test_build_elastic_query_generation_prompt_contains_inputs(self) -> None:
        prompt = build_elastic_query_generation_prompt(
            alert_text="Suspicious logon alert",
            hypotheses=normalize_competing_hypotheses(
                _valid_hypotheses(),
                elastic_query_enabled=False,
            ),
            soc_operational_context="SOC_OPERATIONAL_CONTEXT\n[1] auth runbook",
            elasticsearch_grounding_context=(
                "ELASTICSEARCH_GROUNDING_CONTEXT\n"
                "[1] [elastic.txt :: Auth] logs-auth user.name @timestamp"
            ),
            alert_time="2026-01-01T00:00:00Z",
        )

        self.assertIn("Suspicious logon alert", prompt)
        self.assertIn("INPUT_COMPETING_HYPOTHESES", prompt)
        self.assertIn("ELASTICSEARCH_GROUNDING_CONTEXT", prompt)
        self.assertIn("Elasticsearch Query DSL", prompt)
        self.assertIn("Return ONLY a single JSON object", prompt)

    def test_merge_elastic_query_fields_by_position_keeps_base_hypotheses(self) -> None:
        base = [
            {
                "hypothesis_type": item["hypothesis_type"],
                "hypothesis": item["hypothesis"],
            }
            for item in _valid_hypotheses()
        ]
        generated_payload = {
            "competing_hypotheses": [
                {
                    "query_strategy": "Resolve_Unknown",
                    "primary_elastic_query": _primary_query(),
                    "why_this_query": " check baseline ",
                    "supports_if": " baseline exists ",
                    "weakens_if": " no baseline ",
                }
            ]
        }

        merged = merge_elastic_query_fields_by_position(
            base_hypotheses=base,
            generated_payload=generated_payload,
        )

        self.assertEqual(len(merged), 6)
        self.assertEqual(merged[0]["hypothesis"], base[0]["hypothesis"])
        self.assertEqual(merged[0]["query_strategy"], "resolve_unknown")
        self.assertEqual(merged[0]["primary_elastic_query"]["index_pattern"], "logs-auth")
        self.assertEqual(merged[1]["query_strategy"], "")

    def test_validate_elastic_query_contract_accepts_valid_payload(self) -> None:
        payload = {"competing_hypotheses": _valid_hypotheses()}
        ok, err = validate_elastic_query_contract(
            payload,
            allowed_fields="@timestamp,user.name",
            max_rows=100,
        )
        self.assertTrue(ok, msg=err)

    def test_validate_elastic_query_contract_rejects_placeholders_and_scripts(
        self,
    ) -> None:
        payload = {"competing_hypotheses": _valid_hypotheses()}
        payload["competing_hypotheses"][0]["primary_elastic_query"] = {
            "index_pattern": "<INDEX>",
            "body": {"size": 10, "query": {"match_all": {}}},
        }
        ok, err = validate_elastic_query_contract(payload)
        self.assertFalse(ok)
        self.assertIn("placeholder", err or "")

        payload = {"competing_hypotheses": _valid_hypotheses()}
        payload["competing_hypotheses"][0]["primary_elastic_query"]["body"][
            "script_fields"
        ] = {"x": {"script": "doc['user.name'].value"}}
        ok, err = validate_elastic_query_contract(payload)
        self.assertFalse(ok)
        self.assertIn("denied DSL key", err or "")

    def test_validate_elastic_query_contract_rejects_wildcard_when_disabled(self) -> None:
        payload = {"competing_hypotheses": _valid_hypotheses()}
        payload["competing_hypotheses"][0]["primary_elastic_query"] = _primary_query(
            "logs-*"
        )
        ok, err = validate_elastic_query_contract(payload)
        self.assertFalse(ok)
        self.assertIn("wildcard", err or "")

    def test_validate_elastic_query_contract_rejects_missing_time_filter(self) -> None:
        payload = {"competing_hypotheses": _valid_hypotheses()}
        payload["competing_hypotheses"][0]["primary_elastic_query"]["body"] = {
            "size": 10,
            "query": {"bool": {"filter": [{"term": {"user.name": "admin"}}]}},
        }
        ok, err = validate_elastic_query_contract(payload)
        self.assertFalse(ok)
        self.assertIn("@timestamp", err or "")

    def test_validate_elastic_query_contract_rejects_non_allowlisted_field(self) -> None:
        payload = {"competing_hypotheses": _valid_hypotheses()}
        ok, err = validate_elastic_query_contract(
            payload,
            allowed_fields="@timestamp,host.name",
        )
        self.assertFalse(ok)
        self.assertIn("user.name", err or "")

    def test_build_elastic_query_grounding_refs_returns_source_sections(self) -> None:
        refs = build_elastic_query_grounding_refs(
            _primary_query(),
            (
                "ELASTICSEARCH_GROUNDING_CONTEXT\n"
                "[1] [elastic_reference.txt :: Authentication] "
                "logs-auth user.name @timestamp\n"
            ),
        )

        self.assertEqual(
            refs,
            [
                {
                    "source_file": "elastic_reference.txt",
                    "section_path": "Authentication",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
