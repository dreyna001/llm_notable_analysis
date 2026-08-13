"""Tests for closed ticket render, embed, and OpenSearch indexing."""

from __future__ import annotations

import io
import json
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.closed_ticket_embed import embed_closed_ticket, index_pending_closed_tickets
from s3_notable_pipeline.closed_ticket_render import (
    ClosedTicketRecord,
    build_closed_ticket_chunk_id,
    build_closed_ticket_chunks,
)
from s3_notable_pipeline.config import Config
from s3_notable_pipeline.opensearch_retrieval import build_scoped_hybrid_query, retrieve_closed_ticket_documents
from s3_notable_pipeline.rag_ingestion import index_closed_ticket_chunks

TICKET_SYS_ID = "a1b2c3d4e5f6789012345678abcdef01"
CONTENT_HASH = "abc123def456"


def _embed_config(**overrides: Any) -> Config:
    values = {
        "CLOSED_TICKET_EMBED_ENABLED": True,
        "OUTPUT_BUCKET_NAME": "pipeline-bucket",
        "CLOSED_TICKET_RAW_PREFIX": "closed_tickets",
        "CLOSED_TICKET_REGISTRY_TABLE": "closed-ticket-registry",
        "RAG_TENANT_ID": "tenant-a",
        "RAG_RETRIEVAL_BACKEND": "opensearch",
        "OPENSEARCH_ENDPOINT": "https://search.example.com",
        "OPENSEARCH_CLOSED_TICKET_INDEX": "closed_tickets",
    }
    values.update(overrides)
    return Config(**values)


def _ticket_record(**overrides: Any) -> ClosedTicketRecord:
    expires_at = datetime.now(UTC) + timedelta(days=30)
    record = ClosedTicketRecord(
        ticket_id=TICKET_SYS_ID,
        ticket_number="INC001",
        source_table="sn_si_incident",
        source_url="https://example.service-now.com/nav_to.do",
        state="3",
        is_active=True,
        closed_at=datetime(2026, 6, 1, 11, 0, tzinfo=UTC),
        source_updated_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        raw_payload={
            "number": "INC001",
            "short_description": "Suspicious PowerShell activity",
            "description": "Encoded command observed on host srv-01",
        },
        journals_payload=[
            {
                "value": "Closed after containment and remediation.",
                "element": "work_notes",
            }
        ],
        expires_at=expires_at,
        content_hash=CONTENT_HASH,
    )
    if overrides:
        return ClosedTicketRecord(**{**record.__dict__, **overrides})
    return record


def _version_payload(record: ClosedTicketRecord | None = None) -> dict[str, Any]:
    record = record or _ticket_record()
    return {
        "schema_version": 1,
        "ticket_id": record.ticket_id,
        "ticket_number": record.ticket_number,
        "source_table": record.source_table,
        "source_url": record.source_url,
        "state": record.state,
        "closed_at": record.closed_at.isoformat() if record.closed_at else None,
        "source_updated_at": record.source_updated_at.isoformat()
        if record.source_updated_at
        else None,
        "content_hash": record.content_hash,
        "raw_payload": record.raw_payload,
        "journals_payload": record.journals_payload,
    }


def _manifest(record: ClosedTicketRecord | None = None) -> dict[str, Any]:
    record = record or _ticket_record()
    version_key = (
        f"closed_tickets/tickets/{record.ticket_id}/versions/{record.content_hash}/ticket.json"
    )
    return {
        "schema_version": 1,
        "ticket_id": record.ticket_id,
        "ticket_number": record.ticket_number,
        "source_table": record.source_table,
        "source_url": record.source_url,
        "state": record.state,
        "content_hash": record.content_hash,
        "version_key": version_key,
        "manifest_key": f"closed_tickets/tickets/{record.ticket_id}/manifest.json",
        "is_active": record.is_active,
        "index_status": "pending",
        "expires_at": record.expires_at.isoformat() if record.expires_at else None,
    }


class FakeBedrockClient:
    def invoke_model(self, **_kwargs: Any) -> dict[str, Any]:
        return {"body": io.BytesIO(json.dumps({"embedding": [0.01] * 1024}).encode())}


class FakeOpenSearchAdapter:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.searches: list[dict[str, Any]] = []
        self.bulks: list[dict[str, Any]] = []

    def bulk(self, **kwargs: Any) -> dict[str, bool]:
        self.bulks.append(kwargs)
        for action in kwargs.get("actions", []):
            if action.get("operation") == "index":
                doc_id = str(action["id"])
                self.documents[doc_id] = dict(action["document"])
            elif action.get("operation") == "update":
                doc_id = str(action["id"])
                if doc_id in self.documents:
                    self.documents[doc_id].update(action["document"])
        return {"errors": False}

    def search(self, **kwargs: Any) -> dict[str, Any]:
        self.searches.append(kwargs)
        hits = []
        for doc_id, document in self.documents.items():
            if not document.get("active", True):
                continue
            hits.append({"_id": doc_id, "_score": 1.0, "_source": document})
        return {"hits": {"hits": hits}}


class FakeS3Client:
    def __init__(self, *, objects: dict[str, dict[str, Any]]) -> None:
        self.objects = objects
        self.puts: list[dict[str, Any]] = []

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        key = kwargs["Key"]
        if key not in self.objects:
            raise KeyError(key)
        return {"Body": io.BytesIO(json.dumps(self.objects[key]).encode("utf-8"))}

    def put_object(self, **kwargs: Any) -> None:
        self.puts.append(kwargs)
        body = kwargs["Body"]
        if isinstance(body, bytes):
            self.objects[kwargs["Key"]] = json.loads(body.decode("utf-8"))


class FakeDynamoDbClient:
    def __init__(self, registry: dict[str, dict[str, Any]] | None = None) -> None:
        self.registry = registry or {}
        self.puts: list[dict[str, Any]] = []

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        ticket_id = kwargs["Key"]["ticket_id"]["S"]
        item = self.registry.get(ticket_id)
        return {"Item": item} if item else {}

    def scan(self, **kwargs: Any) -> dict[str, Any]:
        rows = []
        for ticket_id, item in self.registry.items():
            row = _from_ddb(item)
            if row.get("record_type") != "ticket":
                continue
            if row.get("is_active") is False:
                continue
            if row.get("index_status") not in {"pending", "failed"}:
                continue
            rows.append(item)
        return {"Items": rows[: int(kwargs.get("Limit", 100))]}

    def put_item(self, **kwargs: Any) -> None:
        self.puts.append(kwargs)
        item = kwargs["Item"]
        ticket_id = item["ticket_id"]["S"]
        self.registry[ticket_id] = item


def _from_ddb(item: dict[str, dict[str, Any]]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for key, value in item.items():
        if "S" in value:
            row[key] = value["S"]
        elif "BOOL" in value:
            row[key] = value["BOOL"]
        elif "N" in value:
            row[key] = int(value["N"])
    row.setdefault("record_type", "ticket")
    return row


def _to_ddb(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    item: dict[str, dict[str, Any]] = {}
    for key, value in row.items():
        if isinstance(value, bool):
            item[key] = {"BOOL": value}
        elif isinstance(value, int):
            item[key] = {"N": str(value)}
        else:
            item[key] = {"S": str(value)}
    return item


class ClosedTicketRenderTests(unittest.TestCase):
    def test_build_closed_ticket_chunks_is_deterministic(self) -> None:
        record = _ticket_record()
        config = _embed_config()

        first = build_closed_ticket_chunks(record, config)
        second = build_closed_ticket_chunks(record, config)

        self.assertGreaterEqual(len(first), 2)
        self.assertEqual([chunk.chunk_id for chunk in first], [chunk.chunk_id for chunk in second])
        combined = "\n".join(chunk.search_text for chunk in first)
        self.assertIn("Suspicious PowerShell activity", combined)
        self.assertTrue(any("work_notes" in chunk.search_text for chunk in first))

    def test_chunk_id_is_stable(self) -> None:
        chunk_id = build_closed_ticket_chunk_id(
            ticket_id=TICKET_SYS_ID,
            section="ticket.core",
            ordinal=0,
        )
        self.assertIn(TICKET_SYS_ID[:12], chunk_id)
        self.assertTrue(chunk_id.endswith(":0"))

    def test_fixture_ticket_payload_loads(self) -> None:
        fixture_path = FIXTURES_DIR / "closed_ticket_sample.json"
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        record = ClosedTicketRecord(
            ticket_id=str(payload["ticket_id"]),
            ticket_number=payload.get("ticket_number"),
            source_table=payload.get("source_table"),
            source_url=payload.get("source_url"),
            state=payload.get("state"),
            is_active=True,
            closed_at=datetime.fromisoformat(payload["closed_at"]),
            source_updated_at=datetime.fromisoformat(payload["source_updated_at"]),
            raw_payload=payload["raw_payload"],
            journals_payload=payload["journals_payload"],
            expires_at=datetime.fromisoformat(payload["expires_at"]),
            content_hash=payload.get("content_hash"),
        )
        chunks = build_closed_ticket_chunks(record, _embed_config())
        self.assertGreaterEqual(len(chunks), 1)


class ClosedTicketEmbedTests(unittest.TestCase):
    def test_embed_indexes_ticket_and_updates_manifest(self) -> None:
        record = _ticket_record()
        manifest = _manifest(record)
        version_key = manifest["version_key"]
        manifest_key = manifest["manifest_key"]
        s3 = FakeS3Client(objects={manifest_key: manifest, version_key: _version_payload(record)})
        adapter = FakeOpenSearchAdapter()
        dynamodb = FakeDynamoDbClient(
            registry={
                TICKET_SYS_ID: _to_ddb(
                    {
                        "ticket_id": TICKET_SYS_ID,
                        "record_type": "ticket",
                        "is_active": True,
                        "index_status": "pending",
                        "manifest_key": manifest_key,
                        "version_key": version_key,
                    }
                )
            }
        )

        result = embed_closed_ticket(
            ticket_id=TICKET_SYS_ID,
            config=_embed_config(),
            s3_client=s3,
            bedrock_client=FakeBedrockClient(),
            dynamodb_client=dynamodb,
            adapter=adapter,
        )

        self.assertEqual(result.status, "ready")
        self.assertGreater(result.chunk_count, 0)
        self.assertEqual(s3.objects[manifest_key]["index_status"], "ready")
        indexed = [doc for doc in adapter.documents.values() if doc.get("active")]
        self.assertEqual(len(indexed), result.chunk_count)
        self.assertEqual(indexed[0]["tenant_id"], "tenant-a")
        self.assertEqual(indexed[0]["corpus_id"], "closed_tickets")
        self.assertEqual(indexed[0]["ticket_id"], TICKET_SYS_ID)

    def test_replay_tombstones_orphan_chunks(self) -> None:
        adapter = FakeOpenSearchAdapter()
        adapter.documents["old-chunk"] = {
            "document_id": "old-chunk",
            "chunk_id": "old-chunk",
            "ticket_id": TICKET_SYS_ID,
            "tenant_id": "tenant-a",
            "corpus_id": "closed_tickets",
            "active": True,
            "text": "stale",
            "search_text": "stale",
            "embedding": [0.1],
        }
        documents = [
            {
                "document_id": "new-chunk",
                "chunk_id": "new-chunk",
                "ticket_id": TICKET_SYS_ID,
                "tenant_id": "tenant-a",
                "corpus_id": "closed_tickets",
                "active": True,
                "text": "fresh",
                "search_text": "fresh",
                "embedding": [0.2],
            }
        ]
        count = index_closed_ticket_chunks(
            index="closed_tickets",
            ticket_id=TICKET_SYS_ID,
            tenant_id="tenant-a",
            documents=documents,
            adapter=adapter,
        )
        self.assertEqual(count, 1)
        self.assertFalse(adapter.documents["old-chunk"]["active"])
        self.assertTrue(adapter.documents["new-chunk"]["active"])

    def test_deactivated_ticket_is_tombstoned(self) -> None:
        record = _ticket_record(is_active=False)
        manifest = _manifest(record)
        manifest["is_active"] = False
        manifest_key = manifest["manifest_key"]
        s3 = FakeS3Client(objects={manifest_key: manifest})
        adapter = FakeOpenSearchAdapter()
        adapter.documents["chunk-1"] = {
            "document_id": "chunk-1",
            "chunk_id": "chunk-1",
            "ticket_id": TICKET_SYS_ID,
            "tenant_id": "tenant-a",
            "corpus_id": "closed_tickets",
            "active": True,
            "text": "prior",
            "search_text": "prior",
            "embedding": [0.1],
        }
        dynamodb = FakeDynamoDbClient(
            registry={
                TICKET_SYS_ID: _to_ddb(
                    {
                        "ticket_id": TICKET_SYS_ID,
                        "record_type": "ticket",
                        "is_active": False,
                        "index_status": "pending",
                        "manifest_key": manifest_key,
                    }
                )
            }
        )

        result = embed_closed_ticket(
            ticket_id=TICKET_SYS_ID,
            config=_embed_config(),
            s3_client=s3,
            bedrock_client=FakeBedrockClient(),
            dynamodb_client=dynamodb,
            adapter=adapter,
        )

        self.assertEqual(result.status, "not_indexed")
        self.assertFalse(adapter.documents["chunk-1"]["active"])
        self.assertEqual(s3.objects[manifest_key]["index_status"], "not_indexed")

    def test_retrieve_closed_ticket_documents_scopes_by_tenant_and_corpus(self) -> None:
        adapter = FakeOpenSearchAdapter()
        adapter.documents["hit-1"] = {
            "document_id": "hit-1",
            "chunk_id": "hit-1",
            "ticket_id": TICKET_SYS_ID,
            "tenant_id": "tenant-a",
            "corpus_id": "closed_tickets",
            "active": True,
            "text": "historical remediation notes",
            "search_text": "historical remediation notes",
            "embedding": [0.1],
            "section": "ticket.journals",
            "source_file": "INC001",
        }
        documents = retrieve_closed_ticket_documents(
            query_text="remediation",
            config=_embed_config(),
            top_k=3,
            adapter=adapter,
        )
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].corpus_id, "closed_tickets")
        query = build_scoped_hybrid_query(
            query_text="remediation",
            query_embedding=None,
            tenant_id="tenant-a",
            corpus_id="closed_tickets",
            ticket_id=TICKET_SYS_ID,
        )
        filters = query["query"]["bool"]["filter"]
        self.assertIn({"term": {"ticket_id.keyword": TICKET_SYS_ID}}, filters)

    def test_index_pending_closed_tickets_processes_registry(self) -> None:
        record = _ticket_record()
        manifest = _manifest(record)
        version_key = manifest["version_key"]
        manifest_key = manifest["manifest_key"]
        s3 = FakeS3Client(objects={manifest_key: manifest, version_key: _version_payload(record)})
        adapter = FakeOpenSearchAdapter()
        dynamodb = FakeDynamoDbClient(
            registry={
                TICKET_SYS_ID: _to_ddb(
                    {
                        "ticket_id": TICKET_SYS_ID,
                        "record_type": "ticket",
                        "is_active": True,
                        "index_status": "pending",
                        "manifest_key": manifest_key,
                        "version_key": version_key,
                    }
                )
            }
        )

        summary = index_pending_closed_tickets(
            config=_embed_config(),
            s3_client=s3,
            bedrock_client=FakeBedrockClient(),
            dynamodb_client=dynamodb,
            adapter=adapter,
            batch_size=10,
        )

        self.assertEqual(summary["ready"], 1)
        self.assertEqual(summary["selected"], 1)


if __name__ == "__main__":
    unittest.main()
