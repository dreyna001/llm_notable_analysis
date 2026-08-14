"""Offline end-to-end tests for optional analyzer profile orchestration."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from azure_notable_pipeline import blob_handler
from azure_notable_pipeline.azure_search_retrieval import GroundingContextResult
from azure_notable_pipeline.blob_store import BlobInfo, BlobReadResult
from azure_notable_pipeline.config import Config
from azure_notable_pipeline.elasticsearch_query_grounding import (
    ElasticsearchGroundingResult,
)
from azure_notable_pipeline.spl_query_grounding import SplGroundingResult


def _intake() -> blob_handler.BlobCreatedInput:
    return blob_handler.BlobCreatedInput(
        container_name="input",
        blob_name="incoming/profile-case.json",
        etag='"etag-profile"',
        size_bytes=34,
        last_modified="2026-07-13T12:00:00Z",
    )


def _download() -> BlobReadResult:
    body = b'{"finding_id":"profile-case"}'
    return BlobReadResult(
        body=body,
        info=BlobInfo(
            blob_name="incoming/profile-case.json",
            etag='"etag-profile"',
            size_bytes=len(body),
            last_modified=datetime(2026, 7, 13, 12, 0, tzinfo=UTC),
            content_type="application/json",
        ),
    )


class OptionalProfileAnalyzer:
    def __init__(self, operations: list[str]) -> None:
        self.operations = operations
        self.last_llm_response: dict = {}
        self.advisory_context = ""

    def format_alert_input(self, payload, **_kwargs) -> str:
        return json.dumps(payload, separators=(",", ":"))

    def analyze_ttp(
        self,
        _alert_text: str,
        advisory_context: str = "",
        historical_closed_tickets_context: str = "",
    ) -> list:
        self.operations.append("analyze")
        self.advisory_context = advisory_context
        self.last_llm_response = {
            "ttp_analysis": [],
            "alert_reconciliation": {
                "verdict": "unknown",
                "confidence": 0.5,
                "one_sentence_summary": "Profile orchestration fixture.",
                "decision_drivers": [],
                "recommended_actions": [],
            },
            "ioc_extraction": {},
            "evidence_vs_inference": {"evidence": [], "inferences": []},
            "competing_hypotheses": [
                {
                    "hypothesis_type": "adversary",
                    "hypothesis": "Investigate the source.",
                    "best_pivots": ["src_ip"],
                }
            ],
            "metadata": {},
        }
        return []

    def generate_spl_queries(self, **kwargs) -> dict:
        self.operations.append("generate_spl")
        assert kwargs["soc_operational_context"] == "[1] Source: soc-runbook\nSOC context"
        assert "spl-source :: searches/auth" in kwargs["spl_query_grounding_context"]
        out = kwargs["analysis_result"]
        out["competing_hypotheses"][0].update(
            {
                "query_strategy": "resolve_unknown",
                "primary_spl_query": "index=main src_ip=10.0.0.8 | head 10",
                "supports_if": "matching activity exists",
                "weakens_if": "no matching activity exists",
            }
        )
        return out

    def generate_elastic_queries(self, **kwargs) -> dict:
        self.operations.append("generate_elastic")
        assert "elastic-source :: mappings/network" in kwargs[
            "elasticsearch_grounding_context"
        ]
        out = kwargs["analysis_result"]
        out["competing_hypotheses"][0].update(
            {
                "query_strategy": "resolve_unknown",
                "primary_elastic_query": {
                    "index_pattern": "security-events",
                    "body": {"query": {"match_all": {}}},
                },
                "supports_if": "matching activity exists",
                "weakens_if": "no matching activity exists",
            }
        )
        return out

    def interpret_query_results(self, **kwargs) -> dict:
        self.operations.append("interpret")
        out = kwargs["analysis_result"]
        out["metadata"]["interpretation_fixture"] = True
        return out


def _patch_blob_io(monkeypatch, written: dict[str, str]) -> None:
    monkeypatch.setattr(blob_handler, "read_blob_result", lambda *_a, **_k: _download())
    monkeypatch.setattr(
        blob_handler,
        "write_text_blob",
        lambda _container, name, text, **_kwargs: written.__setitem__(name, text),
    )


def test_rag_and_spl_profile_preserve_order_attribution_and_report_schema(
    monkeypatch,
) -> None:
    operations: list[str] = []
    written: dict[str, str] = {}
    analyzer = OptionalProfileAnalyzer(operations)
    _patch_blob_io(monkeypatch, written)

    def retrieve_rag(*_args, **_kwargs):
        operations.append("rag")
        return GroundingContextResult(
            status="success",
            context="[1] Source: soc-runbook\nSOC context",
            snippet_count=1,
        )

    def retrieve_spl(**_kwargs):
        operations.append("spl_grounding")
        return SplGroundingResult(
            status="success",
            context="SPL_QUERY_GROUNDING_CONTEXT\n[1] [spl-source :: searches/auth] query",
            snippet_count=1,
        )

    def execute_spl(*_args, **_kwargs):
        operations.append("execute_spl")
        return [
            {
                "status": "success",
                "executor": "rest",
                "query": "index=main src_ip=10.0.0.8 | head 10",
                "result_count": 1,
                "sample_columns": ["src_ip"],
                "sample_rows": [{"src_ip": "10.0.0.8"}],
                "search_id": "sid-1",
                "hypothesis_index": 0,
                "query_strategy": "resolve_unknown",
            }
        ]

    monkeypatch.setattr(blob_handler, "retrieve_soc_context", retrieve_rag)
    monkeypatch.setattr(blob_handler, "retrieve_spl_query_grounding", retrieve_spl)
    monkeypatch.setattr(blob_handler, "execute_hypothesis_queries", execute_spl)
    monkeypatch.setattr(
        blob_handler, "_splunk_investigation_api_token", lambda _config: "token"
    )

    result = blob_handler.process_blob_created(
        _intake(),
        config=Config(
            CAPABILITY_PROFILES="core,rag,spl_readonly",
            RAG_AZURE_SEARCH_INDEX="soc-index",
            SPL_QUERY_RAG_ENABLED=True,
            SPL_QUERY_AZURE_SEARCH_INDEX="spl-index",
            SPLUNK_BASE_URL="https://splunk.example.test",
            QUERY_RESULT_INTERPRETATION_ENABLED=True,
        ),
        analyzer=analyzer,
    )

    assert result["status"] == "success"
    assert operations == [
        "rag",
        "analyze",
        "spl_grounding",
        "generate_spl",
        "execute_spl",
        "interpret",
    ]
    assert analyzer.advisory_context == "[1] Source: soc-runbook\nSOC context"
    report = json.loads(written["reports/profile-case.json"])
    assert report["metadata"] == {
        "rag_status": "success",
        "rag_snippet_count": 1,
        "closed_ticket_rag_enabled": False,
        "closed_ticket_rag_included": False,
        "closed_ticket_rag_hit_count": 0,
        "closed_ticket_rag_context_chars": 0,
        "closed_ticket_rag_unavailable": False,
        "interpretation_fixture": True,
        "investigation_query_backend": "splunk",
        "investigation_query_executor": "rest",
        "investigation_query_result_count": 1,
        "spl_query_rag_status": "success",
        "spl_query_rag_snippet_count": 1,
    }
    assert report["query_result_section"]["summary"]["executed"] == 1
    assert report["investigation_query_results"][0]["search_id"] == "sid-1"


def test_elastic_profile_uses_native_grounding_and_deterministic_executor(
    monkeypatch,
) -> None:
    operations: list[str] = []
    written: dict[str, str] = {}
    analyzer = OptionalProfileAnalyzer(operations)
    _patch_blob_io(monkeypatch, written)
    monkeypatch.setattr(
        blob_handler,
        "retrieve_soc_context",
        lambda *_a, **_k: GroundingContextResult(status="skipped", message="RAG disabled"),
    )

    def retrieve_elastic(**_kwargs):
        operations.append("elastic_grounding")
        return ElasticsearchGroundingResult(
            status="success",
            context=(
                "ELASTICSEARCH_GROUNDING_CONTEXT\n"
                "[1] [elastic-source :: mappings/network] query"
            ),
            snippet_count=1,
        )

    def execute_elastic(*_args, **_kwargs):
        operations.append("execute_elastic")
        return [
            {
                "status": "denied",
                "executor": "elasticsearch",
                "query": "{}",
                "message": "query index_pattern is not in allowed index policy",
                "hypothesis_index": 0,
                "query_strategy": "resolve_unknown",
            }
        ]

    monkeypatch.setattr(
        blob_handler, "retrieve_elasticsearch_grounding", retrieve_elastic
    )
    monkeypatch.setattr(
        blob_handler,
        "execute_hypothesis_elasticsearch_queries",
        execute_elastic,
    )
    monkeypatch.setattr(blob_handler, "_elasticsearch_api_key", lambda _config: "key")

    result = blob_handler.process_blob_created(
        _intake(),
        config=Config(
            CAPABILITY_PROFILES="core,elastic_readonly",
            ELASTICSEARCH_BASE_URL="https://elastic.example.test",
            ELASTICSEARCH_INDEX_ALLOWLIST="security-events",
            ELASTICSEARCH_ALLOWED_FIELDS="src_ip,@timestamp",
            ELASTICSEARCH_GROUNDING_ENABLED=True,
            ELASTICSEARCH_GROUNDING_AZURE_SEARCH_INDEX="elastic-index",
        ),
        analyzer=analyzer,
    )

    assert result["status"] == "success"
    assert operations == [
        "analyze",
        "elastic_grounding",
        "generate_elastic",
        "execute_elastic",
    ]
    report = json.loads(written["reports/profile-case.json"])
    assert report["metadata"]["elasticsearch_grounding_status"] == "success"
    assert report["metadata"]["investigation_query_executor"] == "elasticsearch"
    assert report["query_result_section"]["summary"]["denied"] == 1
