"""Behavior tests for the Sonnet analyzer orchestration path."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from anthropic.types import TextBlock, ToolUseBlock
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from azure_notable_pipeline.ttp_analyzer import (
    ANALYZE_NOTABLE_TOOL,
    AnthropicAnalyzer,
    validate_competing_hypotheses_balance,
    validate_response_schema,
)
from azure_notable_pipeline.azure_anthropic_gateway import (
    AnthropicGatewayRateLimitError,
)
from azure_notable_pipeline.config import Config


def _valid_payload() -> dict:
    return {
        "ttp_analysis": [
            {
                "ttp_id": "T1059",
                "ttp_name": "Command and Scripting Interpreter",
                "confidence_score": 0.8,
                "explanation": "process_name=powershell.exe. Uncertainty: parent only.",
                "evidence_fields": ["process_name=powershell.exe"],
            }
        ],
        "ioc_extraction": {
            "ip_addresses": [],
            "domains": [],
            "user_accounts": [],
            "hostnames": [],
            "file_paths": [],
            "process_names": ["powershell.exe"],
            "file_hashes": [],
            "event_ids": [],
            "urls": [],
        },
        "evidence_vs_inference": {
            "evidence": ["process_name=powershell.exe"],
            "inferences": [],
        },
        "alert_reconciliation": {
            "verdict": "unknown",
            "confidence": 0.5,
            "one_sentence_summary": "PowerShell was observed.",
            "decision_drivers": ["process_name=powershell.exe"],
            "recommended_actions": ["Review process telemetry."],
        },
        "competing_hypotheses": [],
    }


def _message(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(
        content=[
            ToolUseBlock(
                id="toolu_123",
                input=payload,
                name="analyze_notable",
                type="tool_use",
            )
        ],
        stop_reason="tool_use",
        stop_details=None,
        usage=SimpleNamespace(input_tokens=10, output_tokens=20),
    )


def test_valid_structured_response_preserves_output_contract() -> None:
    client = Mock()
    client.messages.create.return_value = _message(_valid_payload())
    analyzer = AnthropicAnalyzer(deployment="claude-sonnet-4-6", gateway=client)

    ttps = analyzer.analyze_ttp('{"process_name":"powershell.exe"}')

    assert [ttp["ttp_id"] for ttp in ttps] == ["T1059"]
    assert analyzer.last_llm_response["alert_reconciliation"]["verdict"] == "unknown"
    assert analyzer.last_llm_response["metadata"]["model"] == "claude-sonnet-4-6"
    assert analyzer.last_llm_response["metadata"]["repair_attempted"] is False
    assert client.messages.create.call_count == 1


def test_schema_or_policy_failure_gets_exactly_one_repair_call() -> None:
    invalid = _valid_payload()
    invalid["alert_reconciliation"]["one_sentence_summary"] = "See https://example.com"
    client = Mock()
    client.messages.create.side_effect = [_message(invalid), _message(_valid_payload())]
    analyzer = AnthropicAnalyzer(gateway=client)

    ttps = analyzer.analyze_ttp("process_name=powershell.exe")

    assert ttps
    assert client.messages.create.call_count == 2
    assert analyzer.last_llm_response["metadata"]["repair_attempted"] is True
    repair_prompt = client.messages.create.call_args_list[1].kwargs["messages"][0][
        "content"
    ]
    assert "Repair only formatting" in repair_prompt
    assert "Do not add facts" in repair_prompt


def test_second_invalid_response_falls_back_without_third_call() -> None:
    invalid = _valid_payload()
    invalid["alert_reconciliation"]["one_sentence_summary"] = "example.com"
    client = Mock()
    client.messages.create.side_effect = [_message(invalid), _message(invalid)]
    analyzer = AnthropicAnalyzer(gateway=client)

    assert analyzer.analyze_ttp("alert") == []
    assert client.messages.create.call_count == 2
    assert analyzer.last_llm_response["poc_unstructured_output"] is True


def test_refusal_is_typed_failure_and_is_not_repaired() -> None:
    client = Mock()
    client.messages.create.return_value = SimpleNamespace(
        content=[TextBlock(text="refused", type="text")],
        stop_reason="refusal",
        stop_details=None,
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    analyzer = AnthropicAnalyzer(gateway=client)

    assert analyzer.analyze_ttp("alert") == []
    assert client.messages.create.call_count == 1
    assert analyzer.last_llm_response["error"].startswith("LLM API error:")


def test_alert_formatting_and_token_limit_match_existing_contract(monkeypatch) -> None:
    monkeypatch.setenv("MAX_OUTPUT_TOKENS", "999999")
    analyzer = AnthropicAnalyzer(gateway=Mock())

    assert analyzer.max_output_tokens == 8192
    assert analyzer.format_alert_input({"b": 1, "a": 2}) == '{"b":1,"a":2}'
    assert (
        analyzer.format_alert_input(
            {"normalized": True}, raw_content=' {"original":true} ', content_type="json"
        )
        == '{"original":true}'
    )


def test_tool_schema_is_native_and_keeps_required_analysis_fields() -> None:
    assert set(ANALYZE_NOTABLE_TOOL) == {"name", "description", "input_schema"}
    assert "toolSpec" not in ANALYZE_NOTABLE_TOOL
    assert "inputSchema" not in ANALYZE_NOTABLE_TOOL
    assert set(ANALYZE_NOTABLE_TOOL["input_schema"]["required"]) == {
        "ttp_analysis",
        "ioc_extraction",
        "evidence_vs_inference",
        "alert_reconciliation",
        "competing_hypotheses",
    }


def test_schema_and_strict_hypothesis_validators_preserve_existing_policy() -> None:
    payload = _valid_payload()
    ok, error = validate_response_schema(payload)
    assert ok, error

    ok, error = validate_competing_hypotheses_balance(payload, strict=True)
    assert not ok
    assert "exactly 6" in str(error)

    payload["alert_reconciliation"]["verdict"] = "unsupported"
    ok, error = validate_response_schema(payload)
    assert not ok
    assert "alert_reconciliation.verdict" in str(error)


def test_invalid_attack_ids_are_filtered_but_retained_for_audit() -> None:
    payload = _valid_payload()
    payload["ttp_analysis"][0]["ttp_id"] = "T9999"
    client = Mock()
    client.messages.create.return_value = _message(payload)
    analyzer = AnthropicAnalyzer(gateway=client)

    assert analyzer.analyze_ttp("alert") == []
    assert analyzer.last_llm_response["ttp_analysis"] == []
    assert analyzer.last_llm_response["ttp_analysis_raw"][0]["ttp_id"] == "T9999"


def test_runtime_can_propagate_retryable_foundry_failures(monkeypatch) -> None:
    analyzer = AnthropicAnalyzer(gateway=Mock(), propagate_retryable=True)
    monkeypatch.setattr(
        analyzer,
        "_request_analysis",
        lambda _prompt: (_ for _ in ()).throw(
            AnthropicGatewayRateLimitError("limited")
        ),
    )

    with pytest.raises(AnthropicGatewayRateLimitError, match="limited"):
        analyzer.analyze_ttp("alert")


def _query_hypotheses() -> list[dict]:
    return [
        {
            "hypothesis_type": "benign" if index < 3 else "adversary",
            "hypothesis": f"hypothesis {index}",
            "evidence_support": [],
            "evidence_gaps": [],
            "best_pivots": [],
        }
        for index in range(6)
    ]


def test_native_optional_query_generation_keeps_deterministic_validators(
    monkeypatch,
) -> None:
    analyzer = AnthropicAnalyzer(gateway=Mock())
    spl_payload = {
        "competing_hypotheses": [
            {
                "query_strategy": "resolve_unknown",
                "primary_spl_query": "index=main user=alice | stats count",
                "why_this_query": "Counts related events.",
                "supports_if": "Related events exist.",
                "weakens_if": "No events exist.",
            }
            for _ in range(6)
        ]
    }
    monkeypatch.setattr(
        analyzer,
        "_request_json_object",
        lambda _prompt, **_kwargs: (spl_payload, None, '{"generated":true}'),
    )

    spl = analyzer.generate_spl_queries(
        alert_text="user=alice",
        analysis_result={"competing_hypotheses": _query_hypotheses()},
        config=Config(SPL_QUERY_GENERATION_ENABLED=True),
    )

    assert spl["metadata"]["spl_query_generation_status"] == "success"
    assert spl["competing_hypotheses"][0]["primary_spl_query"].startswith(
        "index=main"
    )

    elastic_payload = {
        "competing_hypotheses": [
            {
                "query_strategy": "resolve_unknown",
                "primary_elastic_query": {
                    "index_pattern": "security-events",
                    "body": {
                        "size": 25,
                        "query": {
                            "bool": {
                                "filter": [
                                    {"term": {"user": "alice"}},
                                    {
                                        "range": {
                                            "@timestamp": {
                                                "gte": "now-24h",
                                                "lte": "now",
                                            }
                                        }
                                    },
                                ]
                            }
                        },
                    },
                },
                "why_this_query": "Finds related events.",
                "supports_if": "Related events exist.",
                "weakens_if": "No events exist.",
            }
            for _ in range(6)
        ]
    }
    monkeypatch.setattr(
        analyzer,
        "_request_json_object",
        lambda _prompt, **_kwargs: (elastic_payload, None, '{"generated":true}'),
    )
    elastic = analyzer.generate_elastic_queries(
        alert_text="user=alice",
        analysis_result={"competing_hypotheses": _query_hypotheses()},
        config=Config(
            ELASTIC_QUERY_GENERATION_ENABLED=True,
            ELASTICSEARCH_INDEX_ALLOWLIST="security-events",
            ELASTICSEARCH_ALLOWED_FIELDS="@timestamp,user",
        ),
    )

    assert elastic["metadata"]["elastic_query_generation_status"] == "success"
    assert (
        elastic["competing_hypotheses"][0]["primary_elastic_query"][
            "index_pattern"
        ]
        == "security-events"
    )
