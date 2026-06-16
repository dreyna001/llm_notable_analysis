"""Tests for centralized AWS client creation."""
# pylint: disable=import-error,no-name-in-module

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import s3_notable_pipeline.aws_clients as aws_clients


class AwsClientTests(unittest.TestCase):
    """Ensure AWS clients are centralized and local-emulation aware."""

    def test_client_uses_region_default_without_endpoint(self) -> None:
        """Default client config should not inject fake credentials."""
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(aws_clients.boto3, "client", return_value=object()) as mock_client,
        ):
            aws_clients.aws_client("s3")

        mock_client.assert_called_once_with(service_name="s3", region_name="us-east-1")

    def test_client_supports_localstack_endpoint(self) -> None:
        """AWS_ENDPOINT_URL should route clients to local emulation safely."""
        with (
            patch.dict(
                "os.environ",
                {"AWS_ENDPOINT_URL": "http://localhost:4566"},
                clear=True,
            ),
            patch.object(aws_clients.boto3, "client", return_value=object()) as mock_client,
        ):
            aws_clients.aws_client("dynamodb")

        mock_client.assert_called_once_with(
            service_name="dynamodb",
            region_name="us-east-1",
            endpoint_url="http://localhost:4566",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )

    def test_lambda_client_uses_central_factory(self) -> None:
        """Lambda client creation should share endpoint/region handling."""
        with patch.object(aws_clients, "aws_client", return_value=object()) as mock_client:
            aws_clients.lambda_client()

        mock_client.assert_called_once_with("lambda")


if __name__ == "__main__":
    unittest.main()
