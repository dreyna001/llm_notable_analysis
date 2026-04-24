"""AWS Lambda wrapper that delegates notable analysis to the shared core."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Mapping, Protocol
from urllib.parse import unquote_plus

from updated_notable_analysis.core.models import AnalysisReport, NormalizedAlert
from updated_notable_analysis.core.validators import normalize_optional_string, require_non_empty_string

from .config import AwsRuntimeConfig
from .s3_io import Boto3S3JsonTransport, S3JsonTransport

_REPORT_KEY_SANITIZE_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


class CoreAnalysisRunner(Protocol):
    """Protocol for invoking the shared core analysis path."""

    def run(
        self,
        normalized_alert: NormalizedAlert,
        *,
        profile_name: str | None,
        customer_bundle_name: str | None,
    ) -> AnalysisReport:
        """Run analysis for one normalized alert and return a canonical report."""


class AwsNotableLambdaHandler:
    """Thin AWS Lambda wrapper around the shared core analysis runner."""

    def __init__(
        self,
        *,
        config: AwsRuntimeConfig,
        core_runner: CoreAnalysisRunner,
        s3_transport: S3JsonTransport,
    ) -> None:
        """Initialize the AWS wrapper dependencies."""
        self._config = config
        self._core_runner = core_runner
        self._s3_transport = s3_transport

    def handle(self, event: Mapping[str, Any], _context: Any | None = None) -> dict[str, Any]:
        """Handle one Lambda invocation and persist analysis report output."""
        payload, input_ref = _resolve_alert_payload(event, self._s3_transport)
        normalized_alert = NormalizedAlert(**payload)
        profile_name = normalize_optional_string(event.get("profile_name"), "profile_name")
        customer_bundle_name = normalize_optional_string(
            event.get("customer_bundle_name"),
            "customer_bundle_name",
        )
        report = self._core_runner.run(
            normalized_alert,
            profile_name=profile_name or self._config.default_profile_name,
            customer_bundle_name=customer_bundle_name or self._config.default_customer_bundle_name,
        )
        output_key = build_report_object_key(
            source_record_ref=normalized_alert.source_record_ref,
            received_at=normalized_alert.received_at,
            output_prefix=self._config.report_output_prefix,
        )
        report_payload = serialize_dataclass_payload(report)
        self._s3_transport.put_json_object(
            bucket=self._config.report_output_bucket,
            key=output_key,
            payload=report_payload,
        )
        return {
            "status": "ok",
            "output_bucket": self._config.report_output_bucket,
            "output_key": output_key,
            "source_record_ref": normalized_alert.source_record_ref,
            "input_ref": input_ref,
        }


def build_report_object_key(*, source_record_ref: str, received_at: datetime, output_prefix: str) -> str:
    """Build deterministic S3 object key for a rendered report output."""
    source_record_ref = require_non_empty_string(source_record_ref, "source_record_ref")
    output_prefix = require_non_empty_string(output_prefix, "output_prefix").strip("/")
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)
    else:
        received_at = received_at.astimezone(timezone.utc)
    timestamp = received_at.strftime("%Y%m%dT%H%M%SZ")
    safe_ref = _REPORT_KEY_SANITIZE_PATTERN.sub("_", source_record_ref).strip("_")
    if not safe_ref:
        safe_ref = "unknown"
    return f"{output_prefix}/{timestamp}_{safe_ref}.json"


def serialize_dataclass_payload(value: Any) -> Any:
    """Recursively convert dataclass payloads into JSON-safe structures."""
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, Mapping):
        return {str(key): serialize_dataclass_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize_dataclass_payload(item) for item in value]
    return value


def _resolve_alert_payload(
    event: Mapping[str, Any],
    s3_transport: S3JsonTransport,
) -> tuple[dict[str, Any], str]:
    """Resolve normalized-alert payload from direct invoke or S3 trigger event."""
    if not isinstance(event, Mapping):
        raise ValueError("AWS event must be a mapping.")

    direct_payload = event.get("normalized_alert")
    if direct_payload is not None:
        if not isinstance(direct_payload, Mapping):
            raise ValueError("Field 'normalized_alert' must be a mapping when present.")
        return dict(direct_payload), "event:normalized_alert"

    s3_ref = _extract_first_s3_object_ref(event)
    if s3_ref is None:
        raise ValueError(
            "AWS event must contain either 'normalized_alert' or one S3 trigger record."
        )
    bucket, key = s3_ref
    raw_payload = s3_transport.get_json_object(bucket=bucket, key=key)
    if "normalized_alert" in raw_payload:
        nested = raw_payload["normalized_alert"]
        if not isinstance(nested, Mapping):
            raise ValueError("S3 payload field 'normalized_alert' must be a mapping.")
        return dict(nested), f"s3://{bucket}/{key}"
    return dict(raw_payload), f"s3://{bucket}/{key}"


def _extract_first_s3_object_ref(event: Mapping[str, Any]) -> tuple[str, str] | None:
    """Extract one `(bucket, key)` pair from an S3 trigger event."""
    records = event.get("Records")
    if not isinstance(records, list) or not records:
        return None
    first_record = records[0]
    if not isinstance(first_record, Mapping):
        raise ValueError("S3 event record must be a mapping.")
    s3_section = first_record.get("s3")
    if not isinstance(s3_section, Mapping):
        raise ValueError("S3 event record must include an 's3' mapping.")
    bucket_section = s3_section.get("bucket")
    object_section = s3_section.get("object")
    if not isinstance(bucket_section, Mapping) or not isinstance(object_section, Mapping):
        raise ValueError("S3 event record must include 'bucket' and 'object' mappings.")
    bucket_name = require_non_empty_string(bucket_section.get("name"), "s3.bucket.name")
    object_key = require_non_empty_string(object_section.get("key"), "s3.object.key")
    return bucket_name, unquote_plus(object_key)


class _MissingCoreRunner:
    """Default core runner that fails closed until explicit wiring is provided."""

    def run(
        self,
        normalized_alert: NormalizedAlert,
        *,
        profile_name: str | None,
        customer_bundle_name: str | None,
    ) -> AnalysisReport:
        """Raise deterministic error for missing deployment-specific core wiring."""
        raise RuntimeError(
            "AWS Lambda wrapper requires an injected core runner. "
            "Call set_lambda_dependencies(core_runner=...) during startup wiring."
        )


_LAMBDA_HANDLER_SINGLETON: AwsNotableLambdaHandler | None = None


def set_lambda_dependencies(
    *,
    core_runner: CoreAnalysisRunner,
    s3_transport: S3JsonTransport | None = None,
    config: AwsRuntimeConfig | None = None,
) -> None:
    """Set Lambda dependencies explicitly for runtime wiring or tests."""
    global _LAMBDA_HANDLER_SINGLETON
    _LAMBDA_HANDLER_SINGLETON = AwsNotableLambdaHandler(
        config=config or AwsRuntimeConfig.from_env(),
        core_runner=core_runner,
        s3_transport=s3_transport or Boto3S3JsonTransport(),
    )


def build_default_lambda_handler() -> AwsNotableLambdaHandler:
    """Build default Lambda wrapper with fail-closed core-runner behavior."""
    return AwsNotableLambdaHandler(
        config=AwsRuntimeConfig.from_env(),
        core_runner=_MissingCoreRunner(),
        s3_transport=Boto3S3JsonTransport(),
    )


def lambda_handler(event: Mapping[str, Any], context: Any | None = None) -> dict[str, Any]:
    """AWS Lambda entrypoint for notable-analysis wrapper."""
    global _LAMBDA_HANDLER_SINGLETON
    if _LAMBDA_HANDLER_SINGLETON is None:
        _LAMBDA_HANDLER_SINGLETON = build_default_lambda_handler()
    return _LAMBDA_HANDLER_SINGLETON.handle(event, context)
