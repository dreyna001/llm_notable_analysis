#!/usr/bin/env python3
"""Freeform on-prem notable analysis service entry point (no onprem-llm-sdk).

Uses onprem_main_nonsdk for shared alert formatting so importing does not pull
in onprem_llm_sdk.
"""

import signal
import time
import logging
from pathlib import Path

from .config import load_config, Config
from .logging_utils import setup_logging, get_logger, set_correlation_id
from .ingest import (
    discover_files,
    normalize_notable,
    get_notable_id,
    move_to_processed,
    move_to_quarantine,
)
from .sinks import write_markdown_to_file
from .retention import run_retention
from .freeform_llm_client import FreeformLLMClient


_shutdown_requested = False

# Exceptions expected during long-running service operation that should trigger
# retry/sleep instead of terminating the daemon.
_RECOVERABLE_LOOP_EXCEPTIONS = (OSError, ValueError, RuntimeError, TimeoutError)


def signal_handler(signum, frame):
    """Handle SIGTERM/SIGINT and request a graceful shutdown.

    Args:
        signum: Signal number received.
        frame: Current stack frame (unused).
    """
    global _shutdown_requested
    logger = get_logger(__name__)
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    _shutdown_requested = True


def _format_alert_for_llm(
    normalized: dict,
    *,
    raw_content: str = "",
    content_type: str = "json",
) -> str:
    """Format normalized alert payload using the shared on-prem formatter.

    Args:
        normalized: Parsed alert payload (dict for JSON alerts or wrapper for text).
        raw_content: Original file content before normalization.
        content_type: Source type hint (`json` or `text`).

    Returns:
        Prompt-ready alert text.
    """
    # Reuse the existing formatter from onprem_main to keep inputs consistent.
    # Imported lazily to avoid circular imports.
    from .onprem_main_nonsdk import _format_alert_for_llm as _fmt

    return _fmt(normalized, raw_content=raw_content, content_type=content_type)


def process_notable_freeform(
    file_path: Path,
    config: Config,
    llm_client: FreeformLLMClient,
    logger: logging.Logger,
) -> bool:
    """Process one notable and write a freeform markdown report.

    Args:
        file_path: Path to the incoming notable file.
        config: Service configuration.
        llm_client: Freeform local LLM client.
        logger: Logger instance for lifecycle events.

    Returns:
        True when processing succeeds; otherwise False.
    """
    set_correlation_id()
    logger.info(f"Processing notable (freeform): {file_path.name}")

    try:
        content = file_path.read_text(encoding="utf-8")
        if not content.strip():
            move_to_quarantine(file_path, config, "Empty file")
            return False

        content_type = "json" if file_path.suffix == ".json" else "text"
        alert_payload = normalize_notable(content, content_type)
        notable_id = get_notable_id(alert_payload, file_path)

        alert_text = _format_alert_for_llm(
            alert_payload,
            raw_content=content,
            content_type=content_type,
        )

        logger.info("Sending to LLM for freeform analysis...")
        result = llm_client.analyze_alert_freeform(alert_text)
        if "error" in result:
            move_to_quarantine(file_path, config, f"LLM error: {result['error']}")
            return False

        analysis_text = result.get("analysis_text", "").strip()
        if not analysis_text:
            move_to_quarantine(file_path, config, "Empty LLM response")
            return False

        # Write as .md but with plain paragraphs (no headings/lists).
        report_path = write_markdown_to_file(
            f"{notable_id}_freeform", analysis_text + "\n", config
        )
        logger.info(f"Wrote freeform report: {report_path}")

        move_to_processed(file_path, config)
        logger.info(f"Successfully processed (freeform): {notable_id}")
        return True

    except Exception as e:
        logger.exception(f"Error processing notable {file_path.name} (freeform): {e}")
        try:
            move_to_quarantine(file_path, config, str(e))
        except Exception:
            pass
        return False


def run_service():
    """Run the freeform service loop until shutdown is requested."""
    global _shutdown_requested

    setup_logging()
    logger = get_logger(__name__)
    logger.info("Starting on-prem notable analysis service (freeform)")

    config = load_config()
    logger.info(f"Loaded configuration: INGEST_MODE={config.INGEST_MODE}")

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    llm_client = FreeformLLMClient(config)

    processed_count = 0
    error_count = 0
    last_retention_run = 0.0

    while not _shutdown_requested:
        try:
            now = time.time()
            if (now - last_retention_run) >= config.RETENTION_RUN_INTERVAL_SECONDS:
                stats = run_retention(config)
                logger.info(
                    f"Retention: moved={stats.moved} deleted={stats.deleted} errors={stats.errors}"
                )
                last_retention_run = now

            files = discover_files(config)
            if files:
                logger.info(f"Discovered {len(files)} file(s) to process")
                for fp in files:
                    if _shutdown_requested:
                        break
                    ok = process_notable_freeform(fp, config, llm_client, logger)
                    if ok:
                        processed_count += 1
                    else:
                        error_count += 1

            time.sleep(config.POLL_INTERVAL)
        except _RECOVERABLE_LOOP_EXCEPTIONS as exc:
            logger.error(
                "Recoverable error in main loop (freeform): %s",
                exc,
                exc_info=True,
            )
            time.sleep(config.POLL_INTERVAL)

    logger.info(
        f"Service shutting down (freeform). Processed: {processed_count}, Errors: {error_count}"
    )


def main():
    """CLI entry point for the freeform service."""
    run_service()


if __name__ == "__main__":
    main()
