"""LocalStack integration smoke tests for AWS plumbing.

These tests are skipped by default. Run with LocalStack and
RUN_LOCALSTACK_INTEGRATION=true to exercise local AWS SDK integration without
real AWS credentials.
"""
# pylint: disable=import-error,no-name-in-module

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.config import Config
from s3_notable_pipeline.aws_clients import validate_local_aws_endpoint
from s3_notable_pipeline.idempotency import begin_side_effect, complete_side_effect_success
from s3_notable_pipeline.lambda_handler import write_to_s3_sink
from s3_notable_pipeline.runtime_security import resolve_secret_string

pytestmark = pytest.mark.integration


def _localstack_endpoint() -> str:
    endpoint = os.getenv("AWS_ENDPOINT_URL", "").strip()
    if os.getenv("RUN_LOCALSTACK_INTEGRATION", "").lower() != "true":
        pytest.skip("Set RUN_LOCALSTACK_INTEGRATION=true to run LocalStack tests")
    if not endpoint:
        pytest.skip("Set AWS_ENDPOINT_URL to the LocalStack edge endpoint")
    try:
        return validate_local_aws_endpoint(endpoint)
    except ValueError as exc:
        pytest.skip(f"Refusing unsafe LocalStack endpoint: {exc}")


def _client(service_name: str, endpoint_url: str):
    return boto3.client(
        service_name,
        endpoint_url=endpoint_url,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )


def _delete_bucket(s3, bucket_name: str) -> None:
    try:
        response = s3.list_objects_v2(Bucket=bucket_name)
        for item in response.get("Contents", []):
            s3.delete_object(Bucket=bucket_name, Key=item["Key"])
        s3.delete_bucket(Bucket=bucket_name)
    except ClientError:
        pass


def test_localstack_s3_secret_and_idempotency_flow(monkeypatch) -> None:
    """Exercise local S3 output, Secrets Manager, and DynamoDB idempotency."""

    endpoint = _localstack_endpoint()
    suffix = uuid.uuid4().hex[:12]
    output_bucket = f"notable-local-output-{suffix}"
    table_name = f"notable-local-idem-{suffix}"
    secret_name = f"local/splunk/api-token-{suffix}"

    monkeypatch.setenv("AWS_ENDPOINT_URL", endpoint)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    s3 = _client("s3", endpoint)
    secretsmanager = _client("secretsmanager", endpoint)
    dynamodb = _client("dynamodb", endpoint)

    s3.create_bucket(Bucket=output_bucket)
    dynamodb.create_table(
        TableName=table_name,
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
    )
    dynamodb.get_waiter("table_exists").wait(TableName=table_name)
    secret = secretsmanager.create_secret(
        Name=secret_name,
        SecretString='{"token":"local-token"}',
    )

    try:
        token = resolve_secret_string(
            secret_arn=secret["ARN"],
            setting_name="local Splunk token",
            secret_field="token",
            client=secretsmanager,
        )
        assert token == "local-token"

        config = Config(
            OUTPUT_BUCKET_NAME=output_bucket,
            OUTPUT_PREFIX="reports",
            SIDE_EFFECT_IDEMPOTENCY_ENABLED=True,
            SIDE_EFFECT_IDEMPOTENCY_TABLE=table_name,
        )
        # Use the LocalStack client directly so this test is independent of
        # module import order in the wider pytest process.
        import s3_notable_pipeline.lambda_handler as lambda_handler

        monkeypatch.setattr(lambda_handler, "s3_client", s3)
        sink_result = write_to_s3_sink(
            "incoming/local-notable.json",
            "# Local Report",
            {"markdown": "# Local Report", "meta": {"source": "localstack"}},
            config,
        )
        assert sink_result["status"] == "success"
        markdown = s3.get_object(Bucket=output_bucket, Key="reports/local-notable.md")
        assert markdown["Body"].read().decode("utf-8") == "# Local Report"

        reservation = begin_side_effect(
            config,
            operation="splunk_notable_update",
            key="local-finding-1",
            client=dynamodb,
        )
        assert reservation.should_execute
        complete_side_effect_success(
            reservation,
            metadata={"finding_id": "local-finding-1"},
        )
        duplicate = begin_side_effect(
            config,
            operation="splunk_notable_update",
            key="local-finding-1",
            client=dynamodb,
        )
        assert not duplicate.should_execute
        assert duplicate.existing_marker
        assert duplicate.existing_marker["status"] == "completed"
    finally:
        _delete_bucket(s3, output_bucket)
        try:
            dynamodb.delete_table(TableName=table_name)
        except ClientError:
            pass
        try:
            secretsmanager.delete_secret(SecretId=secret_name, ForceDeleteWithoutRecovery=True)
        except ClientError:
            pass
