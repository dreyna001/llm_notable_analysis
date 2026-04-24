"""AWS deployment wrapper for the updated notable-analysis core."""

from .config import AwsRuntimeConfig
from .handler import (
    AwsNotableLambdaHandler,
    CoreAnalysisRunner,
    build_default_lambda_handler,
    lambda_handler,
    set_lambda_dependencies,
)
from .s3_io import Boto3S3JsonTransport, S3JsonTransport

__all__ = [
    "AwsNotableLambdaHandler",
    "AwsRuntimeConfig",
    "Boto3S3JsonTransport",
    "CoreAnalysisRunner",
    "S3JsonTransport",
    "build_default_lambda_handler",
    "lambda_handler",
    "set_lambda_dependencies",
]
