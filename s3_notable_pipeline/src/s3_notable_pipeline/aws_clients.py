"""Centralized AWS client creation for the S3 notable pipeline."""
# pylint: disable=import-error

from __future__ import annotations

import os
from typing import Any

import boto3


def aws_client(service_name: str, **overrides: Any) -> Any:
    """Create a boto3 client with optional LocalStack-compatible settings."""

    endpoint_url = os.getenv("AWS_ENDPOINT_URL")
    kwargs: dict[str, Any] = {
        "service_name": service_name,
        "region_name": os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or "us-east-1",
    }

    if endpoint_url:
        kwargs.update(
            {
                "endpoint_url": endpoint_url,
                "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID", "test"),
                "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
            }
        )

    kwargs.update(overrides)
    return boto3.client(**kwargs)


def aws_session() -> Any:
    """Return a region-aware boto3 session for request signing."""

    return boto3.Session(
        region_name=os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or "us-east-1"
    )


def aws_credentials() -> Any:
    """Return the current session credentials for SigV4 adapters."""

    return aws_session().get_credentials()


def s3_client() -> Any:
    """Return an S3 client."""

    return aws_client("s3")


def secretsmanager_client() -> Any:
    """Return a Secrets Manager client."""

    return aws_client("secretsmanager")


def bedrock_runtime_client() -> Any:
    """Return a Bedrock Runtime client."""

    return aws_client("bedrock-runtime")


def bedrock_agent_runtime_client() -> Any:
    """Return a Bedrock Agent Runtime client for Knowledge Base retrieval."""

    return aws_client("bedrock-agent-runtime")


def dynamodb_client() -> Any:
    """Return a DynamoDB client."""

    return aws_client("dynamodb")


def lambda_client() -> Any:
    """Return an AWS Lambda client."""

    return aws_client("lambda")


def sqs_client() -> Any:
    """Return an SQS client."""

    return aws_client("sqs")


def textract_client() -> Any:
    """Return a Textract client for closed-ticket attachment extraction."""

    return aws_client("textract")
