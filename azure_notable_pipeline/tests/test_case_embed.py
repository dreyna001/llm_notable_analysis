"""Native Blob/OpenAI/Cosmos behavior tests for case chunk embedding."""

from __future__ import annotations

import json
from types import SimpleNamespace

from azure_notable_pipeline import case_embed
from azure_notable_pipeline.case_embed import build_case_chunks, embed_case_envelope, rewrite_case_chunks
from azure_notable_pipeline.config import Config


def _config(**overrides):
    values = {
        "CASE_ARCHIVE_CHUNKS_PREFIX": "case_chunks",
        "CASE_INDEX_CONTAINER": "case-index",
        "AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT": "embedding-large",
    }
    values.update(overrides)
    return Config(**values)


def _envelope(**overrides):
    value = {
        "case_id": "case-1", "finding_id": "finding-1",
        "source": {"source_filename": "example.json"},
        "artifacts": {"report_markdown_key": "reports/example.md"},
        "alert_payload": {"summary": "Suspicious login", "user": "alice", "src_ip": "192.0.2.10"},
        "analysis": {"alert_reconciliation": {"verdict": "likely_true_positive", "confidence": 0.8}},
    }
    value.update(overrides)
    return value


class FakeCosmos:
    def __init__(self):
        self.updates = []
    def update_case_retrieval_status(self, container, **kwargs):
        self.updates.append((container, kwargs))


def test_build_case_chunks_preserves_deterministic_search_contract():
    chunks = build_case_chunks(_envelope(), _config())
    assert len(chunks) >= 2
    assert chunks[0].source_lane == "alert_payload"
    assert chunks[0].chunk_id == "case-1:alert_payload:alert_summary_d20928f8bd72:0"
    assert "alert.summary" in chunks[0].search_text
    assert "$" in chunks[0].search_text


def test_rewrite_deletes_prefix_then_writes_native_vectors(monkeypatch):
    operations = []
    chunks = build_case_chunks(_envelope(), _config(CASE_QA_MAX_INDEX_CHUNKS_PER_CASE=2))
    listings = [[SimpleNamespace(blob_name="case_chunks/case-1/old.json")], []]
    monkeypatch.setattr(case_embed, "list_blobs", lambda *args, **kwargs: listings.pop(0))
    monkeypatch.setattr(case_embed, "delete_blobs", lambda container, names, **kwargs: operations.append(("delete", container, names)))
    monkeypatch.setattr(case_embed, "embed_texts", lambda texts, **kwargs: operations.append(("embed", texts, kwargs)) or [[0.01] * 1024 for _ in texts])
    monkeypatch.setattr(case_embed, "write_blob", lambda container, name, body, **kwargs: operations.append(("write", container, name, json.loads(body))))
    rewrite_case_chunks(container_name="output", case_id="case-1", chunks=chunks, config=_config(CASE_QA_MAX_INDEX_CHUNKS_PER_CASE=2))
    assert operations[0] == ("delete", "output", ["case_chunks/case-1/old.json"])
    assert operations[1][0] == "embed"
    written = [op for op in operations if op[0] == "write"]
    assert len(written) == len(chunks)
    assert written[0][3]["embedding_model"] == "embedding-large"
    assert len(written[0][3]["embedding"]) == 1024


def test_embed_updates_ready_and_failure_status(monkeypatch):
    cosmos = FakeCosmos()
    monkeypatch.setattr(case_embed, "read_blob", lambda *_args, **_kwargs: json.dumps(_envelope()).encode())
    monkeypatch.setattr(case_embed, "rewrite_case_chunks", lambda **_kwargs: None)
    ready = embed_case_envelope(container_name="output", blob_name="cases/case-1.json", config=_config(CASE_QA_MAX_INDEX_CHUNKS_PER_CASE=2), cosmos=cosmos)
    assert ready.status == "ready" and ready.chunk_count == 2
    assert cosmos.updates[-1][1]["status"] == "ready"

    monkeypatch.setattr(case_embed, "rewrite_case_chunks", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("OpenAI unavailable")))
    failed = embed_case_envelope(container_name="output", blob_name="cases/case-1.json", config=_config(), cosmos=cosmos)
    assert failed.status == "failed"
    assert cosmos.updates[-1][1]["status"] == "failed"
