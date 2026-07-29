"""Run the existing file-drop pipeline with direct Bedrock analysis in preview."""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from llm_notable_analysis_onprem_systemd.onprem_service.case_store import (
    build_case_archive_record,
    build_native_case_id,
)
from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.ingest import discover_files
from llm_notable_analysis_onprem_systemd.onprem_service.onprem_main import (
    ensure_directories,
    process_notable,
)
from preview_bedrock_llm import (
    BedrockPreviewSettings,
    _bedrock_runtime_client,
)
from preview_fake_db import PreviewCaseStore

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DATA_ROOT = _PROJECT_ROOT / "wsl-notable-data"


class PreviewBedrockAnalysisClient:
    """Adapt the shipped Bedrock analyzer to the file-drop client contract."""

    def __init__(self, analyzer: Any) -> None:
        self._analyzer = analyzer

    def analyze_alert(self, alert_text: str, alert_time: str) -> dict[str, Any]:
        """Analyze one alert through Bedrock and return its validated payload."""
        self._analyzer.analyze_ttp(alert_text, alert_time=alert_time)
        result = self._analyzer.last_llm_response
        if not isinstance(result, dict):
            raise RuntimeError("Bedrock analyzer returned no structured analysis")
        metadata = result.setdefault("metadata", {})
        if isinstance(metadata, dict):
            metadata["preview_file_drop"] = True
            metadata["preview_analysis_provider"] = "bedrock"
        return result

    def interpret_query_results(
        self,
        alert_text: str,
        analysis_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Return unchanged results because preview query execution is disabled."""
        del alert_text
        return analysis_result


def preview_file_drop_enabled(
    bedrock_settings: BedrockPreviewSettings | None,
) -> bool:
    """Return whether preview should start its Bedrock file-drop worker."""
    raw = os.environ.get("PORTAL_PREVIEW_FILE_DROP_ENABLED")
    if raw is None:
        return bedrock_settings is not None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def preview_file_drop_root() -> Path:
    """Resolve the local, gitignored preview runtime data directory."""
    configured = os.environ.get("PORTAL_PREVIEW_FILE_DROP_ROOT", "").strip()
    return Path(configured).expanduser() if configured else _DEFAULT_DATA_ROOT


def build_preview_file_drop_config(portal_config: Config) -> Config:
    """Build a local file-drop config while preserving portal case settings."""
    root = preview_file_drop_root()
    return replace(
        portal_config,
        INCOMING_DIR=root / "incoming",
        PROCESSED_DIR=root / "processed",
        QUARANTINE_DIR=root / "quarantine",
        REPORT_DIR=root / "reports",
        ARCHIVE_DIR=root / "archive",
        POLL_INTERVAL=max(
            1,
            int(os.environ.get("PORTAL_PREVIEW_FILE_DROP_POLL_INTERVAL", "2")),
        ),
        MAX_INPUT_FILE_BYTES=max(
            1,
            int(os.environ.get("PORTAL_PREVIEW_MAX_INPUT_FILE_BYTES", "4194304")),
        ),
        CASE_ARCHIVE_ENABLED=True,
        SPLUNK_SINK_ENABLED=False,
        HTML_REPORT_ENABLED=False,
        INVESTIGATION_QUERY_EXECUTION_ENABLED=False,
        QUERY_RESULT_INTERPRETATION_ENABLED=False,
        SERVICENOW_DRAFT_ENABLED=False,
        SERVICENOW_CREATE_ENABLED=False,
    )


def _default_analysis_client(
    settings: BedrockPreviewSettings,
) -> PreviewBedrockAnalysisClient:
    # Imported lazily so preview without file-drop remains usable before a
    # developer refreshes the editable packages in an existing virtualenv.
    from s3_notable_pipeline.ttp_analyzer import BedrockAnalyzer

    analyzer = BedrockAnalyzer(
        model_id=settings.model_id,
        bedrock_client=_bedrock_runtime_client(settings),
    )
    return PreviewBedrockAnalysisClient(analyzer)


class PreviewFileDropRuntime:
    """Poll local files and publish completed Bedrock analyses to preview cases."""

    def __init__(
        self,
        *,
        config: Config,
        case_store: PreviewCaseStore,
        bedrock_settings: BedrockPreviewSettings,
        analysis_client_factory: Callable[
            [BedrockPreviewSettings], PreviewBedrockAnalysisClient
        ] = _default_analysis_client,
    ) -> None:
        self.config = config
        self._case_store = case_store
        self._settings = bedrock_settings
        self._analysis_client_factory = analysis_client_factory
        self._analysis_client: PreviewBedrockAnalysisClient | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _archive_case(self, **kwargs: Any) -> bool:
        alert_payload = kwargs["alert_payload"]
        source_filename = str(kwargs["source_filename"])
        record = build_case_archive_record(
            config=self.config,
            case_id=build_native_case_id(alert_payload, source_filename),
            finding_id=str(kwargs["finding_id"]),
            source_filename=source_filename,
            alert_payload=alert_payload,
            analysis=kwargs["analysis"],
            report_md_path=kwargs.get("report_md_path"),
            report_html_path=kwargs.get("report_html_path"),
        )
        self._case_store.upsert(replace(record, retrieval_status="ready"))
        logger.info("Published preview file-drop case: %s", record.case_id)
        return True

    def process_pending_once(self) -> tuple[int, int]:
        """Process all currently queued files once."""
        files = discover_files(self.config)
        if not files:
            return 0, 0
        if self._analysis_client is None:
            self._analysis_client = self._analysis_client_factory(self._settings)
        processed = 0
        failed = 0
        for file_path in files:
            succeeded = process_notable(
                file_path,
                self.config,
                self._analysis_client,
                logger,
                archive_case=self._archive_case,
            )
            if succeeded:
                processed += 1
            else:
                failed += 1
        return processed, failed

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.process_pending_once()
            except Exception:
                logger.exception("Preview file-drop polling failed")
            self._stop_event.wait(float(self.config.POLL_INTERVAL))

    def start(self) -> None:
        """Create runtime directories and start the polling thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        ensure_directories(self.config, logger)
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="preview-bedrock-file-drop",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Preview Bedrock file drop watching %s",
            self.config.INCOMING_DIR,
        )

    def stop(self) -> None:
        """Stop the polling thread and wait briefly for it to exit."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, float(self.config.POLL_INTERVAL) + 1.0))
        self._thread = None
