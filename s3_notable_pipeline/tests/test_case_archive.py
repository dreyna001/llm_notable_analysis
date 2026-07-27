"""Tests for AWS case archive envelope and CaseIndex writes."""

from __future__ import annotations

import json
import sys
import copy
import unittest
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import s3_notable_pipeline.case_archive as case_archive_module
from s3_notable_pipeline.case_archive import SourceContext, archive_case
from s3_notable_pipeline.config import Config


class ConditionalCheckFailedException(Exception):
    """Fake DynamoDB conditional failure with botocore-like response metadata."""

    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class PreconditionFailed(Exception):
    """Fake S3 IfNoneMatch conflict with botocore-like response metadata."""

    response = {"Error": {"Code": "PreconditionFailed"}}


class _FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class FakeS3Client:
    """Capture S3 put_object calls and optional object storage."""

    def __init__(self) -> None:
        self.puts: list[dict[str, Any]] = []
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, **kwargs: Any) -> None:
        self.puts.append(kwargs)
        bucket = str(kwargs["Bucket"])
        key = str(kwargs["Key"])
        body = kwargs["Body"]
        if not isinstance(body, bytes):
            body = bytes(body)
        object_key = (bucket, key)
        if kwargs.get("IfNoneMatch") == "*" and object_key in self.objects:
            raise PreconditionFailed()
        self.objects[object_key] = body

    def get_object(self, **kwargs: Any) -> dict[str, _FakeBody]:
        body = self.objects[(str(kwargs["Bucket"]), str(kwargs["Key"]))]
        return {"Body": _FakeBody(body)}


class FakeDynamoDbClient:
    """Capture DynamoDB get_item and put_item calls."""

    def __init__(self, existing_item: dict[str, dict[str, Any]] | None = None) -> None:
        self.item = existing_item
        self.puts: list[dict[str, Any]] = []
        self.gets: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        self.gets.append(kwargs)
        if self.item is None:
            return {}
        return {"Item": self.item}

    def put_item(self, **kwargs: Any) -> None:
        item = copy.deepcopy(kwargs["Item"])
        stored = {**kwargs, "Item": item}
        self.puts.append(stored)
        if self.item is not None:
            raise ConditionalCheckFailedException()
        self.item = copy.deepcopy(item)

    def update_item(self, **kwargs: Any) -> None:
        self.updates.append(kwargs)
        condition = str(kwargs.get("ConditionExpression", ""))
        if condition == "attribute_not_exists(#run)":
            return
        if "#run.#state = :claimed" in condition:
            names = kwargs["ExpressionAttributeNames"]
            values = kwargs["ExpressionAttributeValues"]
            run_attr = names["#run"]
            if self.item is None:
                raise ConditionalCheckFailedException()
            run_value = values[":run"]
            fence = values[":fence"]["S"]
            existing_run = case_archive_module._from_ddb_value(self.item[run_attr])
            if (
                not isinstance(existing_run, dict)
                or existing_run.get("state") != "claimed"
                or existing_run.get("fencing_token") != fence
            ):
                raise ConditionalCheckFailedException()
            self.item[run_attr] = run_value
            self.item["latest_run_id"] = values[":run_id"]
            self.item["latest_run_key"] = values[":run_key"]
            self.item["latest_run_at"] = values[":run_at"]
            self.item["case_envelope_key"] = values[":run_key"]


class FakeLambdaClient:
    """Capture async Lambda invoke calls."""

    def __init__(self) -> None:
        self.invocations: list[dict[str, Any]] = []

    def invoke(self, **kwargs: Any) -> dict[str, Any]:
        self.invocations.append(kwargs)
        return {"StatusCode": 202}


class FakeSqsClient:
    """Capture durable case-embedding messages."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def send_message(self, **kwargs: Any) -> dict[str, str]:
        self.messages.append(kwargs)
        return {"MessageId": "embed-1"}


def archive_config(**overrides: Any) -> Config:
    """Build a valid archive-enabled config for tests."""

    values = {
        "CASE_ARCHIVE_ENABLED": True,
        "CASE_ARCHIVE_BUCKET": "case-bucket",
        "CASE_INDEX_TABLE": "case-index",
    }
    values.update(overrides)
    return Config(**values)


def source_context() -> SourceContext:
    """Return a representative S3 source context."""

    return SourceContext(
        input_bucket="input-bucket",
        input_key="incoming/example.json",
        source_filename="example.json",
        content_type="json",
        was_compressed=False,
    )


def analysis_result(**overrides: Any) -> dict[str, Any]:
    """Return a representative analysis result."""

    result = {
        "markdown": "# Report should not be archived",
        "html": "<html>report should not be archived</html>",
        "alert_payload": {
            "finding_id": "abc-123",
            "correlation_id": "corr-1",
            "search_name": "Suspicious Login",
            "risk_score": 42,
        },
        "llm_response": {
            "alert_reconciliation": {
                "verdict": "likely_true_positive",
                "confidence": 0.91,
            },
            "evidence_vs_inference": {"direct_evidence": []},
        },
    }
    result.update(overrides)
    return result


def sink_result() -> dict[str, Any]:
    """Return a successful S3 sink result."""

    return {
        "status": "success",
        "bucket": "output-bucket",
        "markdown_key": "reports/example.md",
        "json_key": "reports/example.json",
        "html_key": "reports/example.html",
    }


def ddb_item(**overrides: str) -> dict[str, dict[str, Any]]:
    """Return a low-level DynamoDB CaseIndex item."""

    item = {
        "case_id": {"S": "abc-123-existing"},
        "finding_id": {"S": "abc-123"},
        "source_filename": {"S": "example.json"},
        "source_key": {"S": "incoming/example.json"},
        "correlation_id": {"S": "corr-1"},
        "case_envelope_key": {"S": "cases/2026/06/15/abc-123-existing.json"},
        "retrieval_status": {"S": "pending"},
        "source_completeness": {"S": "complete"},
    }
    for key, value in overrides.items():
        item[key] = {"S": value}
    return item


class CaseArchiveTests(unittest.TestCase):
    """Behavior tests for case archive writes."""

    def test_archive_is_skipped_when_disabled(self) -> None:
        s3 = FakeS3Client()
        dynamodb = FakeDynamoDbClient()

        result = archive_case(
            analysis_result=analysis_result(),
            config=Config(),
            source=source_context(),
            sink_result=sink_result(),
            s3_client=s3,
            dynamodb_client=dynamodb,
            processed_at="2026-06-15T10:30:00Z",
        )

        self.assertEqual(result.status, "skipped")
        self.assertEqual(s3.puts, [])
        self.assertEqual(dynamodb.puts, [])

    def test_archive_writes_bounded_envelope_and_case_index(self) -> None:
        s3 = FakeS3Client()
        dynamodb = FakeDynamoDbClient()
        lambda_client = FakeLambdaClient()

        result = archive_case(
            analysis_result=analysis_result(),
            config=archive_config(
                PORTAL_ENABLED=True,
                CASE_QA_ENABLED=True,
                CASE_EMBED_LAMBDA_NAME="notable-case-embed",
                PORTAL_JWT_ISSUER="https://issuer.example.test",
                PORTAL_JWT_AUDIENCE="portal",
            ),
            source=source_context(),
            sink_result=sink_result(),
            s3_client=s3,
            dynamodb_client=dynamodb,
            lambda_client=lambda_client,
            processed_at="2026-06-15T10:30:00Z",
        )

        self.assertEqual(result.status, "success")
        self.assertTrue(result.case_id.startswith("abc-123-"))
        self.assertEqual(result.retrieval_status, "pending")
        self.assertEqual(result.source_completeness, "complete")
        self.assertEqual(len(s3.puts), 1)
        self.assertEqual(s3.puts[0]["Bucket"], "case-bucket")
        self.assertTrue(s3.puts[0]["Key"].startswith("cases/2026/06/15/abc-123-"))
        envelope = json.loads(s3.puts[0]["Body"].decode("utf-8"))
        self.assertEqual(envelope["alert_payload"]["finding_id"], "abc-123")
        self.assertEqual(envelope["analysis"]["alert_reconciliation"]["verdict"], "likely_malicious")
        self.assertEqual(envelope["artifacts"]["report_markdown_key"], "reports/example.md")
        self.assertNotIn("markdown", envelope)
        self.assertNotIn("html", envelope)
        self.assertEqual(len(dynamodb.puts), 1)
        self.assertEqual(dynamodb.puts[0]["TableName"], "case-index")
        self.assertEqual(
            dynamodb.puts[0]["ConditionExpression"],
            "attribute_not_exists(case_id)",
        )
        item = dynamodb.puts[0]["Item"]
        self.assertEqual(item["archive_partition"]["S"], "default")
        self.assertEqual(item["retrieval_status"]["S"], "pending")
        self.assertEqual(item["verdict"]["S"], "likely_malicious")
        self.assertEqual(len(lambda_client.invocations), 1)
        self.assertEqual(
            lambda_client.invocations[0]["FunctionName"],
            "notable-case-embed",
        )
        self.assertEqual(lambda_client.invocations[0]["InvocationType"], "Event")
        self.assertEqual(len(dynamodb.updates), 1)
        self.assertIn("latest_run_id", dynamodb.updates[0]["UpdateExpression"])

    def test_archive_publishes_case_embedding_to_configured_queue(self) -> None:
        s3 = FakeS3Client()
        dynamodb = FakeDynamoDbClient()
        sqs = FakeSqsClient()

        result = archive_case(
            analysis_result=analysis_result(),
            config=archive_config(
                PORTAL_ENABLED=True,
                CASE_QA_ENABLED=True,
                CASE_EMBED_QUEUE_URL="https://sqs.us-gov-east-1.amazonaws.com/123/embed",
                PORTAL_JWT_ISSUER="https://issuer.example.test",
                PORTAL_JWT_AUDIENCE="portal",
            ),
            source=source_context(),
            sink_result=sink_result(),
            s3_client=s3,
            dynamodb_client=dynamodb,
            sqs_client=sqs,
            processed_at="2026-06-15T10:30:00Z",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(len(sqs.messages), 1)
        self.assertEqual(
            sqs.messages[0]["QueueUrl"],
            "https://sqs.us-gov-east-1.amazonaws.com/123/embed",
        )
        payload = json.loads(sqs.messages[0]["MessageBody"])
        self.assertEqual(payload["case_id"], result.case_id)
        self.assertEqual(payload["case_envelope_bucket"], "case-bucket")
        self.assertEqual(payload["case_envelope_key"], result.case_envelope_key)

    def test_versioned_processing_claim_uses_immutable_run_key(self) -> None:
        s3 = FakeS3Client()
        dynamodb = FakeDynamoDbClient()

        result = archive_case(
            analysis_result=analysis_result(),
            config=archive_config(),
            source=SourceContext(
                **{**source_context().__dict__, "processing_id": "processing-v1", "source_version_id": "v1"}
            ),
            sink_result=sink_result(),
            s3_client=s3,
            dynamodb_client=dynamodb,
            processed_at="2026-06-15T10:30:00Z",
        )

        self.assertEqual(result.status, "success")
        self.assertIn("/run-", result.case_envelope_key)
        self.assertEqual(s3.puts[0]["IfNoneMatch"], "*")
        item = dynamodb.puts[0]["Item"]
        run_attributes = [key for key in item if key.startswith("run_")]
        self.assertEqual(len(run_attributes), 1)
        self.assertNotIn("case_envelope_key", item)

    def test_concurrent_run_claim_cannot_write_second_envelope(self) -> None:
        source = SourceContext(
            **{**source_context().__dict__, "processing_id": "processing-v1", "source_version_id": "v1"}
        )
        run_id = case_archive_module._build_run_id("abc-123", "processing-v1")
        run_attribute = case_archive_module._run_attribute_name(run_id)

        class ClaimRaceDynamo(FakeDynamoDbClient):
            def update_item(self, **kwargs: Any) -> None:
                self.updates.append(kwargs)
                if kwargs.get("ConditionExpression") == "attribute_not_exists(#run)":
                    self.item[run_attribute] = {
                        "M": {
                            key: case_archive_module._to_ddb_value(value)
                            for key, value in {
                                "run_id": run_id,
                                "state": "claimed",
                                "fencing_token": "winner-fence",
                                "envelope_key": "cases/winner.json",
                            }.items()
                        }
                    }
                    raise ConditionalCheckFailedException()

        s3 = FakeS3Client()
        dynamodb = ClaimRaceDynamo(existing_item=ddb_item())

        result = archive_case(
            analysis_result=analysis_result(),
            config=archive_config(),
            source=source,
            sink_result=sink_result(),
            s3_client=s3,
            dynamodb_client=dynamodb,
            processed_at="2026-06-15T10:30:00Z",
        )

        self.assertEqual(result.status, "skipped")
        self.assertIn("claim", result.message)
        self.assertEqual(s3.puts, [])

    def test_oversized_payload_marks_source_completeness_without_truncating(self) -> None:
        s3 = FakeS3Client()
        dynamodb = FakeDynamoDbClient()

        result = archive_case(
            analysis_result=analysis_result(alert_payload={"finding_id": "abc-123", "large": "x" * 200}),
            config=archive_config(CASE_ARCHIVE_MAX_ALERT_BYTES=50),
            source=source_context(),
            sink_result=sink_result(),
            s3_client=s3,
            dynamodb_client=dynamodb,
            processed_at="2026-06-15T10:30:00Z",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.source_completeness, "missing_alert")
        envelope = json.loads(s3.puts[0]["Body"].decode("utf-8"))
        self.assertIsNone(envelope["alert_payload"])
        self.assertEqual(
            envelope["archive_metadata"]["source_completeness"],
            "missing_alert",
        )

    def test_replayed_case_with_matching_identity_is_idempotent(self) -> None:
        s3 = FakeS3Client()
        dynamodb = FakeDynamoDbClient(existing_item=ddb_item())

        result = archive_case(
            analysis_result=analysis_result(),
            config=archive_config(),
            source=source_context(),
            sink_result=sink_result(),
            s3_client=s3,
            dynamodb_client=dynamodb,
            processed_at="2026-06-15T10:30:00Z",
        )

        self.assertEqual(result.status, "success")
        self.assertIn("replay", result.message)
        self.assertEqual(s3.puts, [])
        self.assertEqual(dynamodb.puts, [])

    def test_completed_run_replay_repairs_pending_embed_handoff(self) -> None:
        source = SourceContext(
            **{**source_context().__dict__, "processing_id": "processing-v1", "source_version_id": "v1"}
        )
        run_id = case_archive_module._build_run_id("abc-123", "processing-v1")
        run_attribute = case_archive_module._run_attribute_name(run_id)
        existing = ddb_item(case_id="abc-123-existing")
        existing[run_attribute] = case_archive_module._to_ddb_value(
            {
                "run_id": run_id,
                "state": "completed",
                "envelope_key": "cases/2026/06/15/abc-123-existing/run.json",
            }
        )
        sqs = FakeSqsClient()

        result = archive_case(
            analysis_result=analysis_result(),
            config=archive_config(
                PORTAL_ENABLED=True,
                CASE_QA_ENABLED=True,
                CASE_EMBED_QUEUE_URL="https://sqs.us-gov-east-1.amazonaws.com/123/embed",
                PORTAL_JWT_ISSUER="https://issuer.example.test",
                PORTAL_JWT_AUDIENCE="portal",
            ),
            source=source,
            sink_result=sink_result(),
            s3_client=FakeS3Client(),
            dynamodb_client=FakeDynamoDbClient(existing_item=existing),
            sqs_client=sqs,
            processed_at="2026-06-15T10:30:00Z",
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(len(sqs.messages), 1)
        payload = json.loads(sqs.messages[0]["MessageBody"])
        self.assertEqual(payload["case_id"], "abc-123-existing")
        self.assertEqual(payload["case_envelope_key"], result.case_envelope_key)

    def test_claimed_run_replay_reconciles_envelope_and_finalizes(self) -> None:
        source = SourceContext(
            **{**source_context().__dict__, "processing_id": "processing-v1", "source_version_id": "v1"}
        )
        run_id = case_archive_module._build_run_id("abc-123", "processing-v1")
        run_attribute = case_archive_module._run_attribute_name(run_id)
        case_id = case_archive_module._build_case_id("abc-123")
        processed_at = "2026-06-15T10:30:00Z"
        envelope_key = case_archive_module._build_envelope_key(
            archive_config(),
            case_archive_module._coerce_utc_datetime(processed_at),
            case_id,
            run_id,
            True,
        )
        existing = ddb_item(case_id=case_id)
        existing[run_attribute] = case_archive_module._to_ddb_value(
            {
                "run_id": run_id,
                "state": "claimed",
                "fencing_token": "fence-replay",
                "envelope_key": envelope_key,
                "processing_id": "processing-v1",
            }
        )
        s3 = FakeS3Client()
        dynamodb = FakeDynamoDbClient(existing_item=existing)
        sqs = FakeSqsClient()

        result = archive_case(
            analysis_result=analysis_result(),
            config=archive_config(
                PORTAL_ENABLED=True,
                CASE_QA_ENABLED=True,
                CASE_EMBED_QUEUE_URL="https://sqs.us-gov-east-1.amazonaws.com/123/embed",
                PORTAL_JWT_ISSUER="https://issuer.example.test",
                PORTAL_JWT_AUDIENCE="portal",
            ),
            source=source,
            sink_result=sink_result(),
            s3_client=s3,
            dynamodb_client=dynamodb,
            sqs_client=sqs,
            processed_at=processed_at,
        )

        self.assertEqual(result.status, "success")
        self.assertIn("reconciled", result.message)
        self.assertEqual(result.case_envelope_key, envelope_key)
        self.assertEqual(len(s3.puts), 1)
        self.assertEqual(len(sqs.messages), 1)
        completed_run = case_archive_module._from_ddb_value(dynamodb.item[run_attribute])
        self.assertEqual(completed_run["state"], "completed")

    def test_claimed_run_envelope_mismatch_fails_closed(self) -> None:
        source = SourceContext(
            **{**source_context().__dict__, "processing_id": "processing-v1", "source_version_id": "v1"}
        )
        run_id = case_archive_module._build_run_id("abc-123", "processing-v1")
        run_attribute = case_archive_module._run_attribute_name(run_id)
        case_id = case_archive_module._build_case_id("abc-123")
        envelope_key = case_archive_module._build_envelope_key(
            archive_config(),
            case_archive_module._coerce_utc_datetime("2026-06-15T10:30:00Z"),
            case_id,
            run_id,
            True,
        )
        s3 = FakeS3Client()
        s3.objects[("case-bucket", envelope_key)] = b'{"unexpected": true}'
        existing = ddb_item(case_id=case_id)
        existing[run_attribute] = case_archive_module._to_ddb_value(
            {
                "run_id": run_id,
                "state": "claimed",
                "fencing_token": "fence-1",
                "envelope_key": envelope_key,
            }
        )

        with self.assertRaises(case_archive_module.CaseEnvelopeMismatchError):
            archive_case(
                analysis_result=analysis_result(),
                config=archive_config(),
                source=source,
                sink_result=sink_result(),
                s3_client=s3,
                dynamodb_client=FakeDynamoDbClient(existing_item=existing),
                processed_at="2026-06-15T10:30:00Z",
            )

    def test_case_identity_collision_suppresses_archive_write(self) -> None:
        s3 = FakeS3Client()
        dynamodb = FakeDynamoDbClient(
            existing_item=ddb_item(
                finding_id="other-finding",
                source_filename="other.json",
                correlation_id="other-correlation",
            )
        )

        result = archive_case(
            analysis_result=analysis_result(),
            config=archive_config(),
            source=source_context(),
            sink_result=sink_result(),
            s3_client=s3,
            dynamodb_client=dynamodb,
            processed_at="2026-06-15T10:30:00Z",
        )

        self.assertEqual(result.status, "skipped")
        self.assertIn("collision", result.message)
        self.assertEqual(s3.puts, [])
        self.assertEqual(dynamodb.puts, [])


if __name__ == "__main__":
    unittest.main()
