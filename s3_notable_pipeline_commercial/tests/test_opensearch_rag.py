"""Focused tests for application-managed OpenSearch RAG."""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from botocore.credentials import Credentials

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.config import Config
from s3_notable_pipeline.opensearch_retrieval import (
    build_scoped_hybrid_query,
    retrieve_documents,
)
from s3_notable_pipeline.opensearch_client import OpenSearchClient
from s3_notable_pipeline.rag_ingestion import (
    ManifestDocument,
    build_rag_documents,
    chunk_text,
    reconcile_document_ids,
    ingest_manifest,
    parse_s3_document,
    tombstone_documents,
    validate_manifest,
)
from s3_notable_pipeline.rag_ingest_handler import handler


class FakeBedrockClient:
    def invoke_model(self, **_kwargs):
        return {"body": io.BytesIO(json.dumps({"embedding": [0.01] * 1024}).encode())}


class FakeAdapter:
    def __init__(self):
        self.searches = []
        self.bulks = []

    def search(self, **kwargs):
        self.searches.append(kwargs)
        return {
            "hits": {
                "hits": [
                    {
                        "_id": "chunk-1",
                        "_score": 2.5,
                        "_source": {
                            "tenant_id": "tenant-a",
                            "corpus_id": "soc",
                            "text": "Escalate suspicious sign-ins.",
                            "source_file": "sop.md",
                            "source_key": "knowledge/sop.md",
                            "metadata": {"provenance": {"manifest_id": "m-1"}},
                        },
                    }
                ]
            }
        }

    def bulk(self, **kwargs):
        self.bulks.append(kwargs)
        return {"errors": False}


class FakeResponse:
    status_code = 200
    text = '{"errors": false, "hits": {"hits": []}}'
    headers = {"content-type": "application/json"}

    def json(self):
        return json.loads(self.text)


class StatusResponse(FakeResponse):
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self):
        self.requests = []

    def request(self, *args, **kwargs):
        self.requests.append((args, kwargs))
        return FakeResponse()


class FakeIngestionS3:
    def __init__(self, manifest):
        self.manifest = manifest
        self.calls = []

    def get_object(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["Key"].endswith("manifest.json"):
            body = json.dumps(self.manifest).encode("utf-8")
        else:
            body = b"Password resets require analyst escalation."
        return {
            "Body": io.BytesIO(body),
            "VersionId": kwargs.get("VersionId", "v1"),
            "ETag": '"etag-1"',
            "ContentLength": len(body),
        }


class FakeIngestionAdapter(FakeAdapter):
    def __init__(self, active_ids=None):
        super().__init__()
        self.active_ids = list(active_ids or [])

    def search(self, **kwargs):
        self.searches.append(kwargs)
        return {"hits": {"hits": [{"_id": value} for value in self.active_ids]}}


def ingestion_config(**overrides):
    values = {
        "RAG_SOURCE_BUCKET": "docs",
        "RAG_SOURCE_PREFIX": "rag-sources",
        "RAG_TENANT_ID": "tenant-a",
        "RAG_INGEST_MAX_DOCUMENT_BYTES": 1000,
        "OPENSEARCH_SOC_INDEX": "soc-knowledge",
        "OPENSEARCH_BULK_BATCH_SIZE": 1,
        "CASE_QA_EMBEDDING_MODEL": "amazon.titan-embed-text-v2:0",
        "CASE_QA_VECTOR_DIMENSIONS": 1024,
        "CASE_QA_EMBED_NORMALIZE": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class OpenSearchRetrievalTests(unittest.TestCase):
    def test_client_config_defaults_to_commercial_region(self):
        config = SimpleNamespace(
            OPENSEARCH_ENDPOINT="https://search.example.test",
            OPENSEARCH_REGION="",
            OPENSEARCH_SERVICE="es",
            OPENSEARCH_TIMEOUT_SECONDS=30,
        )

        with patch.dict("os.environ", {}, clear=True):
            client = OpenSearchClient.from_config(config)

        self.assertEqual(client.region, "us-east-1")

    def test_client_rejects_noncommercial_region(self):
        with self.assertRaisesRegex(ValueError, "OPENSEARCH_REGION must be us-east-1"):
            OpenSearchClient(
                endpoint="https://search.example.test",
                region="us-west-2",
                credentials=Credentials("access", "secret"),
            )

    def test_sigv4_adapter_signs_and_formats_bulk_requests(self):
        session = FakeSession()
        client = OpenSearchClient(
            endpoint="https://search.example.test",
            region="us-east-1",
            credentials=Credentials("access", "secret"),
            session=session,
        )

        client.bulk(
            index="soc-knowledge",
            actions=[
                {
                    "operation": "update",
                    "id": "doc-1",
                    "document": {"active": False},
                }
            ],
        )

        args, kwargs = session.requests[0]
        self.assertEqual(args[:2], ("POST", "https://search.example.test/_bulk"))
        self.assertTrue(kwargs["headers"]["Authorization"].startswith("AWS4-HMAC-SHA256"))
        data = kwargs["data"].decode("utf-8")
        self.assertIn('{"update":{"_index":"soc-knowledge","_id":"doc-1"}}\n', data)
        self.assertIn('{"doc":{"active":false}}\n', data)

    def test_vector_index_is_created_with_knn_mapping(self):
        session = FakeSession()
        responses = iter([StatusResponse(404), StatusResponse(200, "{}")])

        def request(*args, **kwargs):
            session.requests.append((args, kwargs))
            return next(responses)

        session.request = request
        client = OpenSearchClient(
            endpoint="https://search.example.test",
            region="us-east-1",
            credentials=Credentials("access", "secret"),
            session=session,
        )

        client.ensure_vector_index(index="soc-knowledge", dimensions=1024)

        self.assertEqual(session.requests[0][0][0], "HEAD")
        self.assertEqual(session.requests[1][0][0], "PUT")
        mapping = json.loads(session.requests[1][1]["data"])
        self.assertTrue(mapping["settings"]["index"]["knn"])
        self.assertEqual(
            mapping["mappings"]["properties"]["embedding"],
            {"type": "knn_vector", "dimension": 1024},
        )

    def test_hybrid_query_requires_and_applies_scope_filters(self):
        query = build_scoped_hybrid_query(
            query_text="sign in",
            query_embedding=[0.1, 0.2],
            tenant_id="tenant-a",
            corpus_id="soc",
            case_id="case-1",
            top_k=4,
        )

        filters = query["query"]["bool"]["filter"]
        self.assertIn({"term": {"tenant_id.keyword": "tenant-a"}}, filters)
        self.assertIn({"term": {"corpus_id.keyword": "soc"}}, filters)
        self.assertIn({"term": {"case_id.keyword": "case-1"}}, filters)
        self.assertEqual(len(query["query"]["bool"]["should"]), 2)

    def test_retrieval_preserves_source_provenance(self):
        adapter = FakeAdapter()

        documents = retrieve_documents(
            query_text="sign in",
            query_embedding=[0.1],
            index="soc-knowledge",
            tenant_id="tenant-a",
            corpus_id="soc",
            top_k=2,
            adapter=adapter,
        )

        self.assertEqual(documents[0].source_key, "knowledge/sop.md")
        self.assertEqual(documents[0].metadata["provenance"]["manifest_id"], "m-1")
        self.assertEqual(
            adapter.searches[0]["query"]["query"]["bool"]["filter"][0],
            {"term": {"tenant_id.keyword": "tenant-a"}},
        )


class RagIngestionTests(unittest.TestCase):
    def test_ingestion_rejects_manifest_document_count_before_source_reads(self):
        manifest = {
            "manifest_schema_version": 1,
            "manifest_id": "manifest-many",
            "manifest_version": "v1",
            "tenant_id": "tenant-a",
            "corpus_id": "soc",
            "documents": [
                {"bucket": "docs", "key": f"rag-sources/{index}.md", "etag": f"e{index}"}
                for index in range(2)
            ],
        }
        s3 = FakeIngestionS3(manifest)
        with self.assertRaisesRegex(ValueError, "document count limit"):
            ingest_manifest(
                manifest_bucket="docs",
                manifest_key="rag-sources/manifest.json",
                manifest_version_id="manifest-v1",
                manifest_etag="",
                config=ingestion_config(RAG_INGEST_MAX_DOCUMENTS_PER_MANIFEST=1),
                s3_client=s3,
                bedrock_client=FakeBedrockClient(),
                adapter=FakeIngestionAdapter(),
            )
        self.assertEqual(len(s3.calls), 1)

    def test_manifest_ingestion_reads_exact_versions_and_indexes_scoped_chunks(self):
        manifest = {
            "manifest_schema_version": 1,
            "manifest_id": "manifest-1",
            "manifest_version": "v1",
            "tenant_id": "tenant-a",
            "corpus_id": "soc",
            "documents": [
                {
                    "bucket": "docs",
                    "key": "rag-sources/sop.md",
                    "version_id": "v1",
                    "source_file": "sop.md",
                }
            ],
        }
        s3 = FakeIngestionS3(manifest)
        adapter = FakeIngestionAdapter()

        result = ingest_manifest(
            manifest_bucket="docs",
            manifest_key="rag-sources/manifest.json",
            manifest_version_id="manifest-v1",
            manifest_etag="",
            config=ingestion_config(),
            s3_client=s3,
            bedrock_client=FakeBedrockClient(),
            adapter=adapter,
        )

        self.assertEqual(result.indexed_count, 1)
        self.assertEqual(result.tombstoned_count, 0)
        self.assertEqual(s3.calls[0]["VersionId"], "manifest-v1")
        self.assertEqual(s3.calls[1]["VersionId"], "v1")
        self.assertEqual(adapter.bulks[0]["index"], "soc-knowledge")
        self.assertEqual(adapter.bulks[0]["actions"][0]["document"]["tenant_id"], "tenant-a")

    def test_ingestion_rejects_size_before_tombstoning(self):
        manifest = {
            "manifest_schema_version": 1,
            "manifest_id": "manifest-1",
            "manifest_version": "v1",
            "tenant_id": "tenant-a",
            "corpus_id": "soc",
            "documents": [
                {"bucket": "docs", "key": "rag-sources/sop.md", "etag": "etag-1"}
            ],
        }
        s3 = FakeIngestionS3(manifest)
        adapter = FakeIngestionAdapter()
        with self.assertRaisesRegex(ValueError, "size limit"):
            ingest_manifest(
                manifest_bucket="docs",
                manifest_key="rag-sources/manifest.json",
                manifest_version_id="manifest-v1",
                manifest_etag="",
                config=ingestion_config(RAG_INGEST_MAX_DOCUMENT_BYTES=4),
                s3_client=s3,
                bedrock_client=FakeBedrockClient(),
                adapter=adapter,
            )
        self.assertEqual(adapter.bulks, [])

    def test_replacement_is_indexed_before_superseded_chunks_are_tombstoned(self):
        manifest = {
            "manifest_schema_version": 1,
            "manifest_id": "manifest-2",
            "manifest_version": "v2",
            "tenant_id": "tenant-a",
            "corpus_id": "soc",
            "documents": [
                {"bucket": "docs", "key": "rag-sources/sop.md", "version_id": "v2"}
            ],
        }
        adapter = FakeIngestionAdapter(active_ids=["old-chunk"])

        result = ingest_manifest(
            manifest_bucket="docs",
            manifest_key="rag-sources/manifest.json",
            manifest_version_id="manifest-v2",
            manifest_etag="",
            config=ingestion_config(),
            s3_client=FakeIngestionS3(manifest),
            bedrock_client=FakeBedrockClient(),
            adapter=adapter,
        )

        self.assertEqual(result.indexed_count, 1)
        self.assertEqual(result.tombstoned_count, 1)
        self.assertEqual(adapter.bulks[0]["actions"][0]["operation"], "index")
        tombstone = adapter.bulks[1]["actions"][0]
        self.assertEqual(tombstone["operation"], "update")
        self.assertEqual(tombstone["id"], "old-chunk")
        self.assertFalse(tombstone["document"]["active"])

    def test_handler_returns_partial_batch_failures(self):
        event = {
            "Records": [
                {
                    "messageId": "good",
                    "body": json.dumps(
                        {
                            "manifest_bucket": "docs",
                            "manifest_key": "rag-sources/manifest.json",
                            "manifest_version_id": "v1",
                        }
                    ),
                },
                {"messageId": "bad", "body": "not-json"},
            ]
        }
        with patch("s3_notable_pipeline.rag_ingest_handler.ingest_manifest") as mocked:
            result = handler(
                event,
                config=ingestion_config(),
                s3=object(),
                bedrock=object(),
                opensearch=object(),
            )

        mocked.assert_called_once()
        self.assertEqual(result, {"batchItemFailures": [{"itemIdentifier": "bad"}]})

    def test_handler_unwraps_native_s3_notification(self):
        event = {
            "Records": [
                {
                    "messageId": "s3-message",
                    "body": json.dumps(
                        {
                            "Records": [
                                {
                                    "eventSource": "aws:s3",
                                    "s3": {
                                        "bucket": {"name": "docs"},
                                        "object": {
                                            "key": "rag-sources%2Fsoc+manifest.json",
                                            "versionId": "manifest-v2",
                                            "eTag": "etag-v2",
                                        },
                                    },
                                }
                            ]
                        }
                    ),
                }
            ]
        }
        with patch("s3_notable_pipeline.rag_ingest_handler.ingest_manifest") as mocked:
            result = handler(
                event,
                config=ingestion_config(),
                s3=object(),
                bedrock=object(),
                opensearch=object(),
            )

        self.assertEqual(result, {"batchItemFailures": []})
        self.assertEqual(mocked.call_args.kwargs["manifest_bucket"], "docs")
        self.assertEqual(
            mocked.call_args.kwargs["manifest_key"],
            "rag-sources/soc manifest.json",
        )
        self.assertEqual(mocked.call_args.kwargs["manifest_version_id"], "manifest-v2")

    def test_manifest_validation_rejects_duplicate_source_identity(self):
        payload = {
            "manifest_schema_version": 1,
            "manifest_id": "manifest-1",
            "manifest_version": "2026-07-14T00:00:00Z",
            "tenant_id": "tenant-a",
            "corpus_id": "spl",
            "documents": [
                {"bucket": "docs", "key": "a.md", "version_id": "v1"},
                {"bucket": "docs", "key": "a.md", "version_id": "v1"},
            ],
        }

        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_manifest(payload)

    def test_chunking_and_embedding_attach_versioned_provenance(self):
        manifest = validate_manifest(
            {
                "manifest_schema_version": 1,
                "manifest_id": "manifest-1",
                "manifest_version": "v1",
                "tenant_id": "tenant-a",
                "corpus_id": "spl",
                "documents": [{"bucket": "docs", "key": "sop.md", "version_id": "v1"}],
            }
        )
        config = Config(CASE_QA_VECTOR_DIMENSIONS=1024)

        documents = build_rag_documents(
            manifest=manifest,
            source=ManifestDocument(
                bucket="docs",
                key="sop.md",
                version_id="v1",
                source_file="sop.md",
            ),
            text="First paragraph.\n\nSecond paragraph.",
            config=config,
            bedrock_client=FakeBedrockClient(),
            manifest_bucket="docs",
            manifest_key="manifests/spl.json",
        )

        self.assertEqual(len(documents), 2)
        self.assertEqual(documents[0]["tenant_id"], "tenant-a")
        self.assertEqual(documents[0]["source_version_id"], "v1")
        self.assertEqual(documents[0]["manifest_version"], "v1")
        self.assertEqual(len(documents[0]["embedding"]), 1024)

    def test_tombstone_and_reconciliation_are_deterministic(self):
        adapter = FakeAdapter()

        self.assertEqual(tombstone_documents(index="soc-knowledge", document_ids=["a", "b"], adapter=adapter), 2)
        self.assertEqual(adapter.bulks[0]["actions"][0]["operation"], "update")
        self.assertEqual(
            reconcile_document_ids(["a", "b"], ["b", "c"]),
            {"missing": ["a"], "orphaned": ["c"], "matched": ["b"]},
        )
        self.assertEqual(chunk_text("a\n\nb", max_chars=10), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
