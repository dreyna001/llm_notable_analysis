"""Offline contracts for application-managed Azure AI Search RAG."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from azure_notable_pipeline import case_embed, rag_ingestion
from azure_notable_pipeline.azure_search_adapter import AzureSearchAdapter, build_filter
from azure_notable_pipeline.case_chunk_retrieval import retrieve_case_chunks_for_question
from azure_notable_pipeline.case_embed import embed_case_envelope
from azure_notable_pipeline.rag_ingest_handler import (
    RagIngestMessageError,
    dispatch_queue_message,
    normalize_queue_message,
)
from azure_notable_pipeline.rag_ingestion import (
    ManifestDocument,
    build_rag_documents,
    chunk_text,
    ingest_manifest,
    reconcile_document_ids,
    validate_manifest,
)


def _config(**overrides):
    values = {
        "AZURE_SEARCH_ENDPOINT": "https://search.example.gov",
        "RAG_AZURE_SEARCH_INDEX": "soc-rag",
        "RAG_RETRIEVAL_BACKEND": "azure_search",
        "RAG_SOURCE_CONTAINER": "knowledge",
        "RAG_SOURCE_PREFIX": "rag-sources",
        "RAG_TENANT_ID": "tenant-a",
        "RAG_CORPUS_ID": "soc",
        "RAG_CHUNK_MAX_CHARS": 2500,
        "RAG_INGEST_MAX_DOCUMENT_BYTES": 1000,
        "CASE_QA_AZURE_SEARCH_INDEX": "case-rag",
        "CASE_INDEX_CONTAINER": "case-index",
        "CASE_QA_VECTOR_DIMENSIONS": 1024,
        "CASE_QA_MAX_INDEX_CHUNKS_PER_CASE": 20,
        "CASE_QA_VECTOR_TOP_K": 5,
        "CASE_QA_MAX_TOTAL_CHUNKS": 5,
        "CASE_QA_CONTEXT_BUDGET_CHARS": 5000,
        "AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT": "embedding-1024",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeEmbeddingGateway:
    def __init__(self):
        self.calls = []
        self.embeddings = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            data=[
                SimpleNamespace(index=index, embedding=[0.01] * 1024)
                for index, _ in enumerate(kwargs["input"])
            ]
        )


class FakeSearchAdapter:
    def __init__(self, old_ids=None, old_documents=None):
        self.old_ids = list(old_ids or [])
        self.old_documents = list(old_documents or [])
        self.uploads = []
        self.merges = []
        self.searches = []

    def list_ids(self, **kwargs):
        self.searches.append(("list_ids", kwargs))
        return list(self.old_ids)

    def upload_documents(self, **kwargs):
        self.uploads.append(kwargs)
        return len(kwargs["documents"])

    def merge_documents(self, **kwargs):
        self.merges.append(kwargs)
        return len(kwargs["documents"])

    def search(self, **kwargs):
        self.searches.append(("search", kwargs))
        return list(self.old_documents)

    def hybrid_search(self, **kwargs):
        self.searches.append(("hybrid", kwargs))
        return [
            {
                "id": "chunk-1",
                "chunk_id": "chunk-1",
                "case_id": kwargs["case_id"],
                "tenant_id": kwargs["tenant_id"],
                "corpus_id": kwargs["corpus_id"],
                "run_id": kwargs["run_id"],
                "text": "encoded command details",
                "search_text": "encoded command details",
            }
        ]


class FakeBlobStore:
    def __init__(self, manifest, source=b"Password resets require escalation."):
        self.manifest = manifest
        self.source = source

    def get_blob_client(self, *, container, blob, version_id=None):
        payload = json.dumps(self.manifest).encode() if blob.endswith("manifest.json") else self.source

        class Client:
            def get_blob_properties(self):
                return SimpleNamespace(size=len(payload), etag='"etag-1"')

            def download_blob(self):
                return SimpleNamespace(readall=lambda: payload)

        return Client()


def _manifest():
    return {
        "manifest_schema_version": 1,
        "manifest_id": "manifest-1",
        "manifest_version": "v1",
        "tenant_id": "tenant-a",
        "corpus_id": "soc",
        "documents": [
            {
                "container": "knowledge",
                "blob_name": "rag-sources/sop.md",
                "version_id": "source-v1",
                "source_file": "sop.md",
            }
        ],
    }


def test_search_scope_requires_tenant_and_corpus_and_escapes_values():
    value = build_filter(
        tenant_id="tenant'a",
        corpus_id="soc",
        case_id="case-1",
        run_id="run-1",
    )
    assert "tenant_id eq 'tenant''a'" in value
    assert "corpus_id eq 'soc'" in value
    assert "case_id eq 'case-1'" in value
    assert "run_id eq 'run-1'" in value
    with pytest.raises(ValueError, match="tenant_id and corpus_id"):
        build_filter(tenant_id="tenant-a", corpus_id="")


def test_native_adapter_sends_hybrid_vector_query_and_scope_filter():
    class Client:
        def __init__(self):
            self.calls = []

        def search(self, **kwargs):
            self.calls.append(kwargs)
            return [{"id": "doc-1", "text": "SOP", "active": True}]

    client = Client()
    adapter = AzureSearchAdapter(endpoint="https://search.example.gov", index_name="soc-rag", client=client)
    result = adapter.hybrid_search(
        query_text="password reset",
        query_embedding=[0.1, 0.2],
        tenant_id="tenant-a",
        corpus_id="soc",
        top_k=3,
    )
    assert result[0]["id"] == "doc-1"
    assert client.calls[0]["filter"] == "tenant_id eq 'tenant-a' and corpus_id eq 'soc' and active eq true"
    assert client.calls[0]["vector_queries"][0].fields == "embedding"


def test_manifest_ingestion_pushes_provenance_then_tombstones_stale_chunks(monkeypatch):
    gateway = FakeEmbeddingGateway()
    adapter = FakeSearchAdapter(old_ids=["old-id"])
    result = ingest_manifest(
        manifest_container="knowledge",
        manifest_blob_name="rag-sources/manifest.json",
        manifest_version_id="manifest-v1",
        config=_config(),
        blob_store=FakeBlobStore(_manifest()),
        embedding_gateway=gateway,
        adapter=adapter,
    )
    assert result.indexed_count == 1
    assert result.tombstoned_count == 1
    assert adapter.uploads[0]["documents"][0]["tenant_id"] == "tenant-a"
    assert adapter.uploads[0]["documents"][0]["source_version_id"] == "source-v1"
    assert adapter.merges[0]["documents"][0]["id"] == "old-id"
    assert len(gateway.calls) == 1


def test_manifest_is_validated_before_search_mutation_and_chunk_ids_are_stable():
    payload = _manifest()
    payload["documents"].append(dict(payload["documents"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        validate_manifest(payload)
    first = chunk_text("a\n\nb", max_chars=10)
    second = chunk_text("a\n\nb", max_chars=10)
    assert first == second == ["a", "b"]
    assert reconcile_document_ids(["a", "b"], ["b", "c"]) == {
        "missing": ["a"],
        "orphaned": ["c"],
        "matched": ["b"],
    }


def test_queue_schema_is_strict_and_dispatch_does_not_swallow_failures():
    payload = {
        "schema_version": 1,
        "manifest_container": "knowledge",
        "manifest_blob_name": "rag-sources/manifest.json",
        "manifest_version_id": "v1",
        "manifest_etag": "",
    }
    assert normalize_queue_message(json.dumps(payload)).manifest_blob_name.endswith("manifest.json")
    with pytest.raises(RagIngestMessageError, match="extra fields"):
        normalize_queue_message(json.dumps({**payload, "unexpected": True}))
    with pytest.raises(RuntimeError, match="ingestion failed"):
        dispatch_queue_message(
            json.dumps(payload),
            config=_config(),
            workflow=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("ingestion failed")),
        )


def test_search_case_replacement_uploads_generation_before_old_generation_tombstone(monkeypatch):
    gateway = FakeEmbeddingGateway()
    adapter = FakeSearchAdapter(old_documents=[{"id": "old", "run_id": "run-old"}])
    envelope = {
        "case_id": "case-1",
        "run_id": "run-new",
        "source": {"source_filename": "alert.json"},
        "alert_payload": {"summary": "Suspicious command", "user": "alice"},
        "analysis": {"alert_reconciliation": {"verdict": "likely_true_positive"}},
    }
    monkeypatch.setattr(case_embed, "read_blob", lambda *_args, **_kwargs: json.dumps(envelope).encode())
    cosmos = SimpleNamespace(
        updates=[],
        update_case_retrieval_status=lambda container, **kwargs: cosmos.updates.append(kwargs),
    )
    result = embed_case_envelope(
        container_name="output",
        blob_name="cases/case-1.json",
        config=_config(CASE_QA_RETRIEVAL_BACKEND="azure_search"),
        cosmos=cosmos,
        embedding_gateway=gateway,
        search_adapter=adapter,
    )
    assert result.status == "ready"
    assert adapter.uploads and adapter.merges
    assert adapter.uploads[0]["documents"][0]["run_id"] == "run-new"
    assert adapter.merges[0]["documents"][0]["id"] == "old"
    assert cosmos.updates[-1]["status"] == "ready"


def test_case_retrieval_uses_search_and_filters_to_latest_run(monkeypatch):
    gateway = FakeEmbeddingGateway()
    adapter = FakeSearchAdapter()
    case_store = SimpleNamespace(
        get_case=lambda *_args: {
            "case_id": "case-1",
            "retrieval_status": "ready",
            "latest_run_id": "run-1",
        }
    )
    chunks = retrieve_case_chunks_for_question(
        case_id="case-1",
        question="encoded command",
        config=_config(CASE_QA_RETRIEVAL_BACKEND="azure_search"),
        case_store=case_store,
        embedding_gateway=gateway,
        search_adapter=adapter,
    )
    assert chunks[0]["chunk_id"] == "chunk-1"
    hybrid = [call for call in adapter.searches if call[0] == "hybrid"][0][1]
    assert hybrid["tenant_id"] == "tenant-a"
    assert hybrid["case_id"] == "case-1"
    assert hybrid["run_id"] == "run-1"
