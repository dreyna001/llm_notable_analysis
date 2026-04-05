#!/usr/bin/env python3
"""On-prem notable analysis service entry point.

Runs as a long-lived systemd service, polling INCOMING_DIR for new notables,
analyzing them via local LLM (vLLM + gpt-oss-20b), validating TTPs, and
writing markdown reports.

Supports optional bounded concurrency via ThreadPoolExecutor (disabled by default).
"""

import logging
import json
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor, Future
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Set

from .config import load_config, Config
from .logging_utils import setup_logging, get_logger, set_correlation_id
from .ttp_validator import TTPValidator
from .local_llm_client import LocalLLMClient
from .ingest import (
    discover_files,
    normalize_notable,
    get_notable_id,
    move_to_processed,
    move_to_quarantine,
)
from .sinks import write_markdown_to_file, update_splunk_notable
from .markdown_generator import generate_markdown_report
from .retention import run_retention


# Graceful shutdown flag
_shutdown_requested = False

# Exceptions that are expected to occur during daemon runtime and should not
# terminate the service loop.
_RECOVERABLE_LOOP_EXCEPTIONS = (OSError, ValueError, RuntimeError, TimeoutError)


def signal_handler(signum, frame):
    """Handle SIGTERM/SIGINT for graceful shutdown.

    Args:
        signum: Signal number received.
        frame: Current stack frame (unused).
    """
    global _shutdown_requested
    logger = get_logger(__name__)
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    _shutdown_requested = True


def process_notable(
    file_path: Path, config: Config, llm_client: LocalLLMClient, logger: logging.Logger
) -> bool:
    """Process a single notable file.

    Args:
        file_path: Path to the notable file.
        config: Service configuration.
        llm_client: LLM client instance.
        logger: Logger instance.

    Returns:
        True if processing succeeded, False otherwise.
    """
    set_correlation_id()
    logger.info(f"Processing notable: {file_path.name}")

    try:
        # Read file content
        content = file_path.read_text(encoding="utf-8")
        if not content.strip():
            logger.warning(f"Empty file: {file_path.name}")
            move_to_quarantine(file_path, config, "Empty file")
            return False

        # Determine content type
        content_type = "json" if file_path.suffix == ".json" else "text"

        # Keep the alert payload format-agnostic:
        # - valid JSON stays JSON
        # - text stays text
        alert_payload = normalize_notable(content, content_type)
        notable_id = get_notable_id(alert_payload, file_path)

        # Build alert text for LLM
        alert_text = _format_alert_for_llm(
            alert_payload,
            raw_content=content,
            content_type=content_type,
        )

        # Get current time for time window references
        alert_time = datetime.now(timezone.utc).isoformat()

        # Analyze via LLM
        logger.info("Sending to LLM for analysis...")
        llm_response = llm_client.analyze_alert(alert_text, alert_time)

        if "error" in llm_response:
            logger.error(f"LLM analysis failed: {llm_response['error']}")
            move_to_quarantine(file_path, config, f"LLM error: {llm_response['error']}")
            return False

        if llm_response.get("poc_unstructured_output"):
            logger.warning(
                "PoC fallback: markdown report includes raw LLM output (schema not validated)"
            )

        # Extract scored TTPs
        scored_ttps = llm_response.get("ttp_analysis", [])
        logger.info(f"Identified {len(scored_ttps)} valid TTPs")

        # Generate markdown report
        markdown = generate_markdown_report(alert_text, llm_response, scored_ttps)

        # Write to filesystem
        report_path = write_markdown_to_file(notable_id, markdown, config)
        logger.info(f"Wrote report: {report_path}")

        # Optional: Update Splunk notable via REST API
        if config.SPLUNK_SINK_ENABLED:
            finding_id = file_path.stem
            splunk_result = update_splunk_notable(
                notable_id, markdown, finding_id, config
            )
            logger.info(f"Splunk update result: {splunk_result.get('status')}")

        # Move to processed
        move_to_processed(file_path, config)
        logger.info(f"Successfully processed notable: {notable_id}")
        return True

    except Exception as e:
        logger.exception(f"Error processing notable {file_path.name}: {e}")
        try:
            move_to_quarantine(file_path, config, str(e))
        except Exception:
            pass
        return False


def _format_alert_for_llm(
    alert_payload: Any,
    *,
    raw_content: Optional[str] = None,
    content_type: Optional[str] = None,
) -> str:
    """Format the alert payload for LLM input.

    Args:
        alert_payload: Parsed JSON payload or raw text.
        raw_content: Original file contents, used to preserve JSON as submitted.
        content_type: Optional source type hint ('json' or 'text').

    Returns:
        Formatted alert text string.
    """
    if isinstance(alert_payload, str):
        return alert_payload

    if content_type == "json" and (raw_content or "").strip():
        return raw_content.strip()

    try:
        return json.dumps(alert_payload, ensure_ascii=True, separators=(",", ":"))
    except TypeError:
        return str(alert_payload)


def ensure_directories(config: Config, logger: logging.Logger):
    """Ensure all required directories exist.

    Args:
        config: Service configuration.
        logger: Logger instance.
    """
    for d in [
        config.INCOMING_DIR,
        config.PROCESSED_DIR,
        config.QUARANTINE_DIR,
        config.REPORT_DIR,
        config.ARCHIVE_DIR / "processed",
        config.ARCHIVE_DIR / "quarantine",
        config.ARCHIVE_DIR / "reports",
    ]:
        d.mkdir(parents=True, exist_ok=True)
        logger.info(f"Ensured directory exists: {d}")


def _run_sequential(config: Config, llm_client: LocalLLMClient, logger: logging.Logger):
    """Run the main loop in sequential mode (one notable at a time).

    Args:
        config: Service configuration.
        llm_client: LLM client instance.
        logger: Logger instance.

    Returns:
        Tuple of (processed_count, error_count).
    """
    global _shutdown_requested

    processed_count = 0
    error_count = 0
    last_retention_run = 0.0

    while not _shutdown_requested:
        try:
            # Retention housekeeping
            now = time.time()
            if (now - last_retention_run) >= config.RETENTION_RUN_INTERVAL_SECONDS:
                stats = run_retention(config)
                logger.info(
                    f"Retention: moved={stats.moved} deleted={stats.deleted} errors={stats.errors}"
                )
                last_retention_run = now

            # Discover new files
            files = discover_files(config)

            if files:
                logger.info(f"Discovered {len(files)} file(s) to process")

                for file_path in files:
                    if _shutdown_requested:
                        logger.info("Shutdown requested, stopping processing")
                        break

                    success = process_notable(file_path, config, llm_client, logger)
                    if success:
                        processed_count += 1
                    else:
                        error_count += 1

            time.sleep(config.POLL_INTERVAL)

        except _RECOVERABLE_LOOP_EXCEPTIONS as exc:
            logger.error("Recoverable error in main loop: %s", exc, exc_info=True)
            time.sleep(config.POLL_INTERVAL)

    return processed_count, error_count


def _run_concurrent(config: Config, llm_client: LocalLLMClient, logger: logging.Logger):
    """Run the main loop with bounded concurrency via ThreadPoolExecutor.

    Implements backpressure: if in-flight jobs reach MAX_QUEUE_DEPTH, new files
    are skipped until capacity frees up on next poll cycle.

    Args:
        config: Service configuration.
        llm_client: LLM client instance.
        logger: Logger instance.

    Returns:
        Tuple of (processed_count, error_count).
    """
    global _shutdown_requested

    processed_count = 0
    error_count = 0
    last_retention_run = 0.0

    # Track in-flight work
    in_flight: Set[Path] = set()
    futures: List[Future] = []

    def job_done_callback(future: Future, file_path: Path):
        """Handle job completion.

        Args:
            future: Completed Future object.
            file_path: Path of the processed file.
        """
        nonlocal processed_count, error_count
        in_flight.discard(file_path)
        try:
            success = future.result()
            if success:
                processed_count += 1
            else:
                error_count += 1
        except Exception as e:
            error_count += 1
            logger.exception(f"Unhandled exception in worker for {file_path.name}: {e}")

    with ThreadPoolExecutor(
        max_workers=config.MAX_WORKERS, thread_name_prefix="notable-worker"
    ) as executor:
        logger.info(
            f"Concurrency enabled: max_workers={config.MAX_WORKERS}, max_queue={config.MAX_QUEUE_DEPTH}"
        )

        while not _shutdown_requested:
            try:
                # Retention housekeeping
                now = time.time()
                if (now - last_retention_run) >= config.RETENTION_RUN_INTERVAL_SECONDS:
                    stats = run_retention(config)
                    logger.info(
                        f"Retention: moved={stats.moved} deleted={stats.deleted} errors={stats.errors}"
                    )
                    last_retention_run = now

                # Prune completed futures
                futures = [f for f in futures if not f.done()]

                # Discover new files
                files = discover_files(config)

                if files:
                    # Apply backpressure
                    available_slots = config.MAX_QUEUE_DEPTH - len(in_flight)
                    if available_slots <= 0:
                        logger.warning(
                            f"Backpressure: queue full ({len(in_flight)} in-flight), "
                            f"skipping {len(files)} new file(s) until next cycle"
                        )
                    else:
                        to_process = [f for f in files if f not in in_flight][
                            :available_slots
                        ]
                        if to_process:
                            logger.info(
                                f"Submitting {len(to_process)} file(s) to worker pool"
                            )

                        for file_path in to_process:
                            in_flight.add(file_path)
                            future = executor.submit(
                                process_notable, file_path, config, llm_client, logger
                            )
                            future.add_done_callback(
                                lambda f, fp=file_path: job_done_callback(f, fp)
                            )
                            futures.append(future)

                time.sleep(config.POLL_INTERVAL)

            except _RECOVERABLE_LOOP_EXCEPTIONS as exc:
                logger.error(
                    "Recoverable error in concurrent main loop: %s",
                    exc,
                    exc_info=True,
                )
                time.sleep(config.POLL_INTERVAL)

        # Graceful shutdown: wait for in-flight jobs
        logger.info(
            f"Shutdown requested, waiting for {len(in_flight)} in-flight job(s)..."
        )
        executor.shutdown(wait=True)

    return processed_count, error_count


def run_service():
    """Main service loop."""
    global _shutdown_requested

    # Setup
    setup_logging()
    logger = get_logger(__name__)
    logger.info("Starting on-prem notable analysis service")

    # Load config
    config = load_config()
    logger.info(f"Loaded configuration: INGEST_MODE={config.INGEST_MODE}")

    # Setup signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Ensure directories
    ensure_directories(config, logger)

    # Initialize TTP validator
    logger.info(f"Loading TTP validator from {config.MITRE_IDS_PATH}")
    try:
        ttp_validator = TTPValidator(config.MITRE_IDS_PATH)
        logger.info(f"Loaded {ttp_validator.get_ttp_count()} valid TTPs")
    except Exception as e:
        logger.error(f"Failed to load TTP validator: {e}")
        sys.exit(1)

    # Initialize LLM client
    llm_client = LocalLLMClient(config, ttp_validator)
    logger.info(
        f"LLM client initialized: {config.LLM_API_URL} (model: {config.LLM_MODEL_NAME})"
    )

    # Main loop
    logger.info(f"Starting main loop (poll_interval={config.POLL_INTERVAL}s)")

    if config.CONCURRENCY_ENABLED:
        processed_count, error_count = _run_concurrent(config, llm_client, logger)
    else:
        processed_count, error_count = _run_sequential(config, llm_client, logger)

    logger.info(
        f"Service shutting down. Processed: {processed_count}, Errors: {error_count}"
    )


def main():
    """CLI entry point."""
    run_service()


if __name__ == "__main__":
    main()
