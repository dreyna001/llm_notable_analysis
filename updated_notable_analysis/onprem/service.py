"""On-prem local file-ingest wrapper that delegates notable analysis to the shared core."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import logging
from pathlib import Path
import re
from typing import Any, Mapping, Protocol

from updated_notable_analysis.core.models import AnalysisReport, NormalizedAlert
from updated_notable_analysis.core.validators import normalize_optional_string, require_non_empty_string

from .config import OnPremRuntimeConfig
from .file_io import LocalJsonFileTransport, StdlibLocalJsonFileTransport

LOGGER = logging.getLogger(__name__)
_SAFE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


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


class OnPremNotableProcessor:
    """Thin on-prem wrapper around the shared core analysis runner."""

    def __init__(
        self,
        *,
        config: OnPremRuntimeConfig,
        core_runner: CoreAnalysisRunner,
        file_transport: LocalJsonFileTransport,
    ) -> None:
        """Initialize the on-prem wrapper dependencies."""
        self._config = config
        self._core_runner = core_runner
        self._file_transport = file_transport
        self._ensure_runtime_directories()

    def process_next_available(self) -> dict[str, Any] | None:
        """Process the next available input file if one exists."""
        candidates = self._file_transport.list_json_files(self._config.incoming_dir)
        if not candidates:
            return None
        return self.process_file(candidates[0])

    def process_file(self, input_path: str | Path) -> dict[str, Any]:
        """Process one local JSON input file into a report or quarantine result."""
        source_path = Path(input_path)
        try:
            raw_payload = self._file_transport.read_json_file(source_path)
            payload, profile_name, customer_bundle_name = _resolve_input_payload(raw_payload)
            normalized_alert = NormalizedAlert(**payload)
            report = self._core_runner.run(
                normalized_alert,
                profile_name=profile_name or self._config.default_profile_name,
                customer_bundle_name=customer_bundle_name
                or self._config.default_customer_bundle_name,
            )
            report_path = build_report_output_path(
                report_output_dir=self._config.report_output_dir,
                source_record_ref=normalized_alert.source_record_ref,
                received_at=normalized_alert.received_at,
            )
            self._file_transport.write_json_file(
                report_path,
                serialize_dataclass_payload(report),
            )
            processed_path = move_to_archive_directory(
                source_path=source_path,
                target_directory=self._config.processed_dir,
                file_transport=self._file_transport,
            )
            LOGGER.info(
                "Processed on-prem notable input file.",
                extra={
                    "input_path": str(source_path),
                    "processed_path": str(processed_path),
                    "report_path": str(report_path),
                },
            )
            return {
                "status": "ok",
                "input_path": str(source_path),
                "processed_path": str(processed_path),
                "report_path": str(report_path),
                "source_record_ref": normalized_alert.source_record_ref,
            }
        except Exception as exc:
            if not source_path.exists():
                raise
            quarantine_path = move_to_archive_directory(
                source_path=source_path,
                target_directory=self._config.quarantine_dir,
                file_transport=self._file_transport,
            )
            error_path = write_quarantine_error(
                quarantine_path=quarantine_path,
                message=str(exc),
                file_transport=self._file_transport,
            )
            LOGGER.warning(
                "Quarantined on-prem notable input file.",
                extra={
                    "input_path": str(source_path),
                    "quarantine_path": str(quarantine_path),
                    "error_path": str(error_path),
                    "error_message": str(exc),
                },
            )
            return {
                "status": "quarantined",
                "input_path": str(source_path),
                "quarantine_path": str(quarantine_path),
                "error_path": str(error_path),
                "message": str(exc),
            }

    def _ensure_runtime_directories(self) -> None:
        """Create runtime directories if they do not already exist."""
        for path in (
            self._config.incoming_dir,
            self._config.processed_dir,
            self._config.quarantine_dir,
            self._config.report_output_dir,
        ):
            Path(path).mkdir(parents=True, exist_ok=True)


def build_report_output_path(
    *,
    report_output_dir: str,
    source_record_ref: str,
    received_at: datetime,
) -> Path:
    """Build deterministic local report path for a rendered report output."""
    report_output_dir = require_non_empty_string(report_output_dir, "report_output_dir")
    source_record_ref = require_non_empty_string(source_record_ref, "source_record_ref")
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)
    else:
        received_at = received_at.astimezone(timezone.utc)
    timestamp = received_at.strftime("%Y%m%dT%H%M%SZ")
    safe_ref = _SAFE_NAME_PATTERN.sub("_", source_record_ref).strip("_")
    if not safe_ref:
        safe_ref = "unknown"
    return Path(report_output_dir) / f"{timestamp}_{safe_ref}.json"


def move_to_archive_directory(
    *,
    source_path: Path,
    target_directory: str,
    file_transport: LocalJsonFileTransport,
) -> Path:
    """Move one source file into an archive directory without clobbering collisions."""
    destination_dir = Path(target_directory)
    candidate = destination_dir / source_path.name
    counter = 1
    while candidate.exists():
        candidate = destination_dir / f"{source_path.stem}_{counter}{source_path.suffix}"
        counter += 1
    return file_transport.move_file(source_path, candidate)


def write_quarantine_error(
    *,
    quarantine_path: Path,
    message: str,
    file_transport: LocalJsonFileTransport,
) -> Path:
    """Write a small sidecar JSON file explaining why an input was quarantined."""
    error_path = quarantine_path.with_suffix(quarantine_path.suffix + ".error.json")
    file_transport.write_json_file(
        error_path,
        {"status": "quarantined", "message": require_non_empty_string(message, "message")},
    )
    return error_path


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


def _resolve_input_payload(
    raw_payload: Mapping[str, Any],
) -> tuple[dict[str, Any], str | None, str | None]:
    """Resolve one normalized-alert payload and optional runtime overrides."""
    profile_name = normalize_optional_string(raw_payload.get("profile_name"), "profile_name")
    customer_bundle_name = normalize_optional_string(
        raw_payload.get("customer_bundle_name"),
        "customer_bundle_name",
    )
    direct_payload = raw_payload.get("normalized_alert")
    if direct_payload is not None:
        if not isinstance(direct_payload, Mapping):
            raise ValueError("Field 'normalized_alert' must be a mapping when present.")
        return dict(direct_payload), profile_name, customer_bundle_name
    return dict(raw_payload), profile_name, customer_bundle_name


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
            "On-prem wrapper requires an injected core runner. "
            "Use build_default_processor(core_runner=...) or construct OnPremNotableProcessor directly."
        )


def build_default_processor(
    *,
    core_runner: CoreAnalysisRunner | None = None,
    config: OnPremRuntimeConfig | None = None,
    file_transport: LocalJsonFileTransport | None = None,
) -> OnPremNotableProcessor:
    """Build default on-prem processor with explicit dependency seams."""
    return OnPremNotableProcessor(
        config=config or OnPremRuntimeConfig.from_env(),
        core_runner=core_runner or _MissingCoreRunner(),
        file_transport=file_transport or StdlibLocalJsonFileTransport(),
    )
