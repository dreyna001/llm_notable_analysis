#!/usr/bin/env python3
"""Freeform on-prem notable analysis service entry point.

This variant writes a plain-paragraph report (no strict JSON schema) to reduce
failure modes when models drift from structured output contracts.
"""

import signal
import time
import logging
from pathlib import Path

from .config import load_config, Config
from .logging_utils import setup_logging, get_logger, set_correlation_id
from .ingest import discover_files, normalize_notable, get_notable_id, move_to_processed, move_to_quarantine
from .sinks import write_markdown_to_file
from .retention import run_retention
from .freeform_llm_client import FreeformLLMClient


_shutdown_requested = False


def signal_handler(signum, frame):
    global _shutdown_requested
    logger = get_logger(__name__)
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    _shutdown_requested = True


def _format_alert_for_llm(normalized: dict) -> str:
    # Reuse the existing formatter from onprem_main to keep inputs consistent.
    # Imported lazily to avoid circular imports.
    from .onprem_main import _format_alert_for_llm as _fmt
    return _fmt(normalized)


def process_notable_freeform(file_path: Path, config: Config, llm_client: FreeformLLMClient, logger: logging.Logger) -> bool:
    set_correlation_id()
    logger.info(f"Processing notable (freeform): {file_path.name}")

    try:
        content = file_path.read_text(encoding="utf-8")
        if not content.strip():
            move_to_quarantine(file_path, config, "Empty file")
            return False

        content_type = "json" if file_path.suffix == ".json" else "text"
        normalized = normalize_notable(content, content_type)
        notable_id = get_notable_id(normalized.get("raw_log", {}), file_path)

        alert_text = _format_alert_for_llm(normalized)

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
        report_path = write_markdown_to_file(f"{notable_id}_freeform", analysis_text + "\n", config)
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
                logger.info(f"Retention: moved={stats.moved} deleted={stats.deleted} errors={stats.errors}")
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
        except Exception as e:
            logger.exception(f"Error in main loop (freeform): {e}")
            time.sleep(config.POLL_INTERVAL)

    logger.info(f"Service shutting down (freeform). Processed: {processed_count}, Errors: {error_count}")


def main():
    run_service()


if __name__ == "__main__":
    main()

