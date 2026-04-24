"""AWS runtime configuration models for the thin deployment wrapper."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from updated_notable_analysis.core.validators import normalize_optional_string, require_non_empty_string

DEFAULT_REPORT_OUTPUT_PREFIX = "updated-notable-analysis/reports"


@dataclass(slots=True)
class AwsRuntimeConfig:
    """Normalized runtime config contract for the AWS wrapper.

    Attributes:
        report_output_bucket: S3 bucket for report output objects.
        report_output_prefix: S3 key prefix for report output objects.
        default_profile_name: Optional default capability profile.
        default_customer_bundle_name: Optional default customer bundle.
    """

    report_output_bucket: str
    report_output_prefix: str = DEFAULT_REPORT_OUTPUT_PREFIX
    default_profile_name: str | None = None
    default_customer_bundle_name: str | None = None

    def __post_init__(self) -> None:
        """Validate and normalize AWS wrapper config fields."""
        self.report_output_bucket = require_non_empty_string(
            self.report_output_bucket,
            "report_output_bucket",
        )
        normalized_prefix = require_non_empty_string(
            self.report_output_prefix,
            "report_output_prefix",
        ).strip("/")
        self.report_output_prefix = require_non_empty_string(
            normalized_prefix,
            "report_output_prefix",
        )
        self.default_profile_name = normalize_optional_string(
            self.default_profile_name,
            "default_profile_name",
        )
        self.default_customer_bundle_name = normalize_optional_string(
            self.default_customer_bundle_name,
            "default_customer_bundle_name",
        )

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "AwsRuntimeConfig":
        """Build config from environment variables.

        Args:
            environ: Optional mapping for deterministic tests. Defaults to `os.environ`.

        Returns:
            AwsRuntimeConfig: Validated configuration.
        """

        env = os.environ if environ is None else environ
        return cls(
            report_output_bucket=env.get("UPDATED_NOTABLE_AWS_REPORT_OUTPUT_BUCKET", ""),
            report_output_prefix=env.get(
                "UPDATED_NOTABLE_AWS_REPORT_OUTPUT_PREFIX",
                DEFAULT_REPORT_OUTPUT_PREFIX,
            ),
            default_profile_name=env.get("UPDATED_NOTABLE_AWS_DEFAULT_PROFILE_NAME"),
            default_customer_bundle_name=env.get(
                "UPDATED_NOTABLE_AWS_DEFAULT_CUSTOMER_BUNDLE_NAME",
            ),
        )
