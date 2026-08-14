"""Opt-in local parity path using Azurite and deterministic service substitutes.

This suite deliberately never constructs a production Azure credential. Blob and
Queue operations use only an explicit Azurite connection string; services that do
not have faithful local emulators are supplied through existing injection seams.
"""

from __future__ import annotations

import gzip
import json
import os
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import urlparse

import azure.functions as func
import pytest
from azure.core.exceptions import AzureError
from azure.cosmos import CosmosClient, PartitionKey
from azure.storage.blob import BlobServiceClient
from azure.storage.queue import QueueServiceClient

from azure_notable_pipeline import blob_handler, portal_handler
from azure_notable_pipeline.case_archive import SourceContext, archive_case
from azure_notable_pipeline.case_embed import embed_case_envelope
from azure_notable_pipeline.config import Config
from azure_notable_pipeline.cosmos_store import CosmosStore, CreateOutcome
from azure_notable_pipeline.disposition_sync_handler import invoke_disposition_sync
from azure_notable_pipeline.embed_handler import dispatch_embed_queue_message


pytestmark = pytest.mark.integration
_OPT_IN_ENV = "RUN_LOCAL_AZURE_PARITY"
_CONNECTION_ENV = "AZURITE_CONNECTION_STRING"
_FIXED_NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
_AZURITE_API_VERSION = "2023-11-03"


def _local_connection_string() -> str:
    if os.getenv(_OPT_IN_ENV, "").strip().lower() not in {"1", "true", "yes"}:
        pytest.skip(f"set {_OPT_IN_ENV}=1 to run local Azure parity")
    value = os.getenv(_CONNECTION_ENV, "").strip()
    if not value:
        pytest.skip(f"set {_CONNECTION_ENV} to an Azurite connection string")
    lowered = value.lower()
    if lowered == "usedevelopmentstorage=true":
        return value
    endpoints = [
        part.split("=", 1)[1]
        for part in value.split(";")
        if "=" in part and part.split("=", 1)[0].lower().endswith("endpoint")
    ]
    if not endpoints:
        pytest.skip(f"{_CONNECTION_ENV} must contain explicit Azurite endpoints")
    for endpoint in endpoints:
        host = (urlparse(endpoint).hostname or "").lower()
        if host not in {"127.0.0.1", "localhost", "::1", "host.docker.internal", "azurite"}:
            pytest.fail(f"refusing non-local Azure endpoint in {_CONNECTION_ENV}: {host}")
    return value


def _local_cosmos_contract() -> tuple[str, str]:
    endpoint = os.getenv("COSMOS_ENDPOINT", "").strip()
    key = os.getenv("COSMOS_EMULATOR_KEY", "").strip()
    if not endpoint or not key:
        pytest.skip("set COSMOS_ENDPOINT and COSMOS_EMULATOR_KEY for Cosmos parity")
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() not in {
        "127.0.0.1", "localhost", "::1", "host.docker.internal", "cosmos-emulator"
    }:
        pytest.fail("COSMOS_ENDPOINT must be a local Cosmos emulator URL")
    return endpoint, key


class _MemoryCosmos:
    def __init__(self) -> None:
        self.cases: dict[str, dict] = {}
        self.dispositions: dict[str, dict] = {}
        self.checkpoints: dict[str, dict] = {}

    def get_case(self, _container: str, case_id: str):
        value = self.cases.get(case_id)
        return dict(value) if value else None

    def create_case_if_absent(self, _container: str, item: dict) -> CreateOutcome:
        case_id = item["case_id"]
        if case_id in self.cases:
            return CreateOutcome(created=False)
        self.cases[case_id] = dict(item)
        return CreateOutcome(created=True, item=dict(item))

    def update_case_retrieval_status(
        self,
        _container: str,
        *,
        case_id: str,
        status: str,
        message: str,
        updated_at: str,
        max_attempts: int,
    ) -> dict:
        self.cases[case_id].update(
            retrieval_status=status,
            retrieval_message=message,
            retrieval_updated_at=updated_at,
        )
        return dict(self.cases[case_id])

    def list_cases(self, _container: str, *, limit: int, before=None, **_filters):
        return list(self.cases.values())[:limit]

    def get_disposition(self, _container: str, snow_sys_id: str):
        return self.dispositions.get(snow_sys_id)

    def upsert_disposition(self, _container: str, value: dict):
        self.dispositions[value["snow_sys_id"]] = dict(value)
        return dict(value)

    def get_sync_checkpoint(self, _container: str, job_name: str):
        return self.checkpoints.get(job_name)

    def upsert_sync_checkpoint(self, _container: str, value: dict):
        self.checkpoints[value["job_name"]] = dict(value)
        return dict(value)

    def find_cases_by_correlation(self, *_args, **_kwargs):
        return []


class _DeterministicAnalyzer:
    def __init__(self) -> None:
        self.last_llm_response = {
            "ttp_analysis": [],
            "alert_reconciliation": {
                "verdict": "likely_true_positive",
                "confidence": 0.91,
                "one_sentence_summary": "A deterministic suspicious login was analyzed.",
                "decision_drivers": ["known fixture"],
                "recommended_actions": ["review account activity"],
            },
            "ioc_extraction": {"ip_addresses": ["192.0.2.44"]},
            "evidence_vs_inference": {"evidence": ["fixture"], "inferences": []},
            "competing_hypotheses": [],
        }

    def format_alert_input(self, payload, **_kwargs) -> str:
        return json.dumps(payload, sort_keys=True)

    def analyze_ttp(
        self,
        _alert_text: str,
        advisory_context: str = "",
        historical_closed_tickets_context: str = "",
    ):
        return []


class _EmbeddingGateway:
    def __init__(self) -> None:
        self.embeddings = SimpleNamespace(create=self._create)

    @staticmethod
    def _create(*, input, **_kwargs):
        return SimpleNamespace(
            data=[
                SimpleNamespace(index=index, embedding=[float(index)] + [0.0] * 1023)
                for index, _text in enumerate(input)
            ]
        )


def _receive_one(queue):
    messages = list(queue.receive_messages(messages_per_page=1, visibility_timeout=30))
    assert messages, "expected one Azurite queue message"
    return messages[0]


def _config(input_container: str, output_container: str, analyzer_queue: str, embed_queue: str) -> Config:
    return Config(
        INPUT_CONTAINER_NAME=input_container,
        OUTPUT_CONTAINER_NAME=output_container,
        CASE_ARCHIVE_CONTAINER=output_container,
        ANALYZER_QUEUE_NAME=analyzer_queue,
        CASE_EMBED_QUEUE_NAME=embed_queue,
        CASE_ARCHIVE_ENABLED=True,
        CASE_ARCHIVE_FAILURE_MODE="fail_closed",
        CASE_INDEX_CONTAINER="case-index",
        CASE_QA_ENABLED=True,
        CASE_ARCHIVE_CHUNKS_PREFIX="case_chunks",
        CASE_QA_MAX_INDEX_CHUNKS_PER_CASE=8,
        AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT="local-deterministic",
        PORTAL_ENABLED=True,
        PORTAL_AUTH_MODE="jwt",
        PORTAL_ENTRA_REQUIRED_APP_ROLE="Case.Reader",
        PORTAL_JWT_ISSUER="https://local.invalid",
        PORTAL_JWT_AUDIENCE="local-parity",
        PORTAL_CHAT_DISTRIBUTED_QUOTA_ENABLED=False,
    )


def test_gzip_intake_queue_analysis_archive_embed_chat_and_disposition_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_string = _local_connection_string()
    suffix = uuid.uuid4().hex[:12]
    input_container = f"parityin{suffix}"
    output_container = f"parityout{suffix}"
    analyzer_queue_name = f"parity-analyzer-{suffix}"
    embed_queue_name = f"parity-embed-{suffix}"
    try:
        blobs = BlobServiceClient.from_connection_string(
            connection_string, api_version=_AZURITE_API_VERSION
        )
        queues = QueueServiceClient.from_connection_string(
            connection_string, api_version=_AZURITE_API_VERSION
        )
        blobs.get_service_properties(timeout=3)
        queues.get_service_properties(timeout=3)
    except (AzureError, OSError) as exc:
        pytest.skip(f"Azurite is unavailable: {exc}")

    input_client = blobs.create_container(input_container)
    blobs.create_container(output_container)
    analyzer_queue = queues.create_queue(analyzer_queue_name)
    embed_queue = queues.create_queue(embed_queue_name)
    config = _config(input_container, output_container, analyzer_queue_name, embed_queue_name)
    cosmos = _MemoryCosmos()
    notable = {
        "finding_id": "finding-local-001",
        "search_name": "Suspicious Login",
        "user": "alice",
        "src_ip": "192.0.2.44",
    }
    body = gzip.compress(json.dumps(notable).encode())
    blob_name = "incoming/finding-local-001.json.gz"
    try:
        input_client.upload_blob(blob_name, body, overwrite=True)
        properties = input_client.get_blob_client(blob_name).get_blob_properties()
        job = blob_handler.publish_blob_trigger_input(
            SimpleNamespace(
                name=f"{input_container}/{blob_name}",
                length=len(body),
                etag=properties.etag,
                last_modified=properties.last_modified,
            ),
            config=config,
            publisher=analyzer_queue,
        )
        analyzer_message = _receive_one(analyzer_queue)
        queued = blob_handler.normalize_analyzer_queue_message(analyzer_message.content)
        assert queued.etag == job["etag"]

        def archive_workflow(**kwargs):
            result = archive_case(
                analysis_result=kwargs["analysis_result"],
                config=config,
                source=SourceContext(
                    input_bucket=queued.container_name,
                    input_key=queued.blob_name,
                    source_filename="finding-local-001.json.gz",
                    content_type=kwargs["decoded_notable"].content_type,
                    was_compressed=True,
                ),
                sink_result=kwargs["sink_result"],
                blob_store=blobs,
                cosmos=cosmos,
                processed_at=_FIXED_NOW,
            )
            if not result.case_envelope_key:
                return None
            return blob_handler.CaseEnvelopeReference(output_container, result.case_envelope_key)

        result = blob_handler.process_blob_created(
            queued,
            config=config,
            store=blobs,
            analyzer=_DeterministicAnalyzer(),
            case_archive_workflow=archive_workflow,
            embed_publisher=embed_queue,
        )
        analyzer_queue.delete_message(analyzer_message.id, analyzer_message.pop_receipt)
        assert result["status"] == "success"
        assert result["case_embed_queued"] is True
        assert blobs.get_blob_client(output_container, "reports/finding-local-001.md").exists()
        assert blobs.get_blob_client(output_container, "reports/finding-local-001.json").exists()
        assert len(cosmos.cases) == 1
        case_id, case_item = next(iter(cosmos.cases.items()))

        embed_message = _receive_one(embed_queue)
        embed_result = dispatch_embed_queue_message(
            embed_message.content,
            workflow=lambda embed_job: embed_case_envelope(
                container_name=embed_job.case_envelope_container,
                blob_name=embed_job.case_envelope_blob_name,
                config=config,
                blob_store=blobs,
                cosmos=cosmos,
                embedding_gateway=_EmbeddingGateway(),
            ),
        )
        embed_queue.delete_message(embed_message.id, embed_message.pop_receipt)
        assert embed_result.status == "ready"
        assert cosmos.cases[case_id]["retrieval_status"] == "ready"
        chunks = list(
            blobs.get_container_client(output_container).list_blobs(
                name_starts_with=f"case_chunks/{case_id}/"
            )
        )
        assert chunks

        # Replay is idempotent at the case-index boundary; no second case appears.
        replay = blob_handler.process_blob_created(
            queued,
            config=config,
            store=blobs,
            analyzer=_DeterministicAnalyzer(),
            case_archive_workflow=archive_workflow,
            embed_publisher=embed_queue,
        )
        assert replay["status"] == "success"
        assert len(cosmos.cases) == 1

        # Updating the source makes the queued ETag terminally superseded.
        input_client.upload_blob(blob_name, body + b" ", overwrite=True)
        stale = blob_handler.process_blob_created(
            queued, config=config, store=blobs, analyzer=_DeterministicAnalyzer()
        )
        assert stale == {"blob_name": blob_name, "status": "superseded", "reason": "stale_etag"}

        with pytest.raises(ValueError, match="valid JSON"):
            blob_handler.normalize_analyzer_queue_message(b"poison")

        # Portal auth and chat use the native HTTP route with deterministic auth/service seams.
        monkeypatch.setattr(portal_handler, "load_config", lambda: config)
        monkeypatch.setattr(portal_handler, "_cosmos_store", lambda _config: cosmos)
        monkeypatch.setattr(portal_handler, "_blob_service", lambda _config: blobs)
        monkeypatch.setattr(
            portal_handler,
            "validate_portal_jwt",
            lambda token, **_kwargs: {
                "sub": "local-analyst",
                "roles": ["Case.Reader"],
            }
            if token == "good-token"
            else None,
        )
        chat_body = json.dumps(
            {"mode": "selected_case", "selected_case_id": case_id, "question": "What happened?"}
        ).encode()
        denied = func.HttpRequest(
            method="POST", url="http://localhost/api/chat", headers={"Authorization": "Bearer bad-token"},
            params={}, route_params={"path": "api/chat"}, body=chat_body,
        )
        allowed = func.HttpRequest(
            method="POST", url="http://localhost/api/chat", headers={"Authorization": "Bearer good-token"},
            params={}, route_params={"path": "api/chat"}, body=chat_body,
        )
        assert portal_handler.handle_request(denied, chat_service=lambda **_kwargs: None).status_code == 401
        response = portal_handler.handle_request(
            allowed,
            chat_service=lambda **kwargs: SimpleNamespace(
                answer=f"Case {kwargs['selected_case_id']} contains a suspicious login.",
                answer_status="answered",
                context_usage=None,
            ),
        )
        assert response.status_code == 200
        assert json.loads(response.get_body())["answer_status"] == "answered"

        before_dispositions = dict(cosmos.dispositions)
        before_checkpoints = dict(cosmos.checkpoints)

        def disposition_workflow(**kwargs):
            store = kwargs["cosmos_store"]
            store.upsert_disposition("dispositions", {"snow_sys_id": "snow-local-1"})
            store.upsert_sync_checkpoint("sync-state", {"job_name": "closed-cases"})
            return {"status": "success", "cursor_advanced": True}

        dry_run = invoke_disposition_sync(
            dry_run=True,
            config=Config(SERVICENOW_DISPOSITION_SYNC_ENABLED=True),
            cosmos_store=cosmos,
            blob_service=blobs,
            workflow=disposition_workflow,
        )
        assert dry_run["dry_run"] is True
        assert dry_run["would_advance_cursor"] is True
        assert cosmos.dispositions == before_dispositions
        assert cosmos.checkpoints == before_checkpoints
        assert case_item["case_envelope_key"]
    finally:
        for queue_name in (analyzer_queue_name, embed_queue_name):
            try:
                queues.delete_queue(queue_name)
            except AzureError:
                pass
        for container_name in (input_container, output_container):
            try:
                blobs.delete_container(container_name)
            except AzureError:
                pass


def test_cosmos_emulator_duplicate_etag_and_partition_ownership() -> None:
    """Exercise native Cosmos semantics only when its emulator is explicitly configured."""

    if os.getenv(_OPT_IN_ENV, "").strip().lower() not in {"1", "true", "yes"}:
        pytest.skip(f"set {_OPT_IN_ENV}=1 to run local Azure parity")
    endpoint, key = _local_cosmos_contract()
    database_name = f"parity-{uuid.uuid4().hex[:12]}"
    try:
        client = CosmosClient(
            endpoint,
            credential=key,
            connection_verify=False,
            connection_timeout=3,
            request_timeout=5,
        )
        database = client.create_database(database_name)
        database.create_container("case-index", partition_key=PartitionKey(path="/case_id"))
        database.create_container("chat-sessions", partition_key=PartitionKey(path="/user_id"))
    except Exception as exc:  # Emulator startup and TLS failures are environment prerequisites.
        pytest.skip(f"Cosmos emulator is unavailable: {exc}")

    try:
        store = CosmosStore(database)
        created = store.create_case_if_absent(
            "case-index", {"case_id": "case-local-1", "retrieval_status": "pending"}
        )
        duplicate = store.create_case_if_absent(
            "case-index", {"case_id": "case-local-1", "retrieval_status": "pending"}
        )
        assert created.created is True
        assert duplicate.created is False

        current = store.get_case("case-index", "case-local-1")
        assert current and current["_etag"]
        replacement = {**current, "retrieval_status": "ready"}
        stale = store.replace_if_match(
            "case-index", replacement, expected_etag='"definitely-stale"'
        )
        applied = store.replace_if_match(
            "case-index", replacement, expected_etag=current["_etag"]
        )
        assert stale.outcome == "precondition_failed"
        assert applied.applied is True

        session = {
            "session_id": "session-local-1",
            "user_id": "analyst-a",
            "mode": "selected_case",
        }
        assert store.create_chat_session("chat-sessions", session).created is True
        assert store.get_chat_session(
            "chat-sessions", session_id="session-local-1", user_id="analyst-a"
        ) is not None
        assert store.get_chat_session(
            "chat-sessions", session_id="session-local-1", user_id="analyst-b"
        ) is None
    finally:
        try:
            client.delete_database(database_name)
        except Exception:
            pass
