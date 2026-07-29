"""Optional filesystem reports, portal archive, and Splunk writeback."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from .case_archive_flow import archive_case_for_portal
from .config import Config
from .html_generator import generate_html_report
from .markdown_generator import generate_markdown_report
from .sinks import update_splunk_notable, write_html_to_file, write_markdown_to_file

ArchiveFn = Callable[..., bool]


def persist_notable_outputs(
    *,
    config: Config,
    logger: logging.Logger,
    notable_id: str,
    alert_text: str,
    llm_response: dict[str, Any],
    scored_ttps: list[Any],
    finding_id: str,
    file_path: Path,
    alert_payload: Any,
    archive_case: ArchiveFn | None = None,
) -> None:
    """Write optional report artifacts and archive analysis for the portal."""
    report_path: Path | None = None
    html_report_path: Path | None = None
    markdown: str | None = None

    need_markdown = bool(config.MARKDOWN_REPORT_ENABLED) or bool(config.SPLUNK_SINK_ENABLED)
    if need_markdown:
        markdown = generate_markdown_report(alert_text, llm_response, scored_ttps)

    if config.MARKDOWN_REPORT_ENABLED:
        if markdown is None:
            raise RuntimeError("markdown report generation failed unexpectedly")
        report_path = write_markdown_to_file(notable_id, markdown, config)
        logger.info("Wrote report: %s", report_path)

    if config.HTML_REPORT_ENABLED:
        html = generate_html_report(alert_text, llm_response, scored_ttps)
        html_report_path = write_html_to_file(notable_id, html, config)
        logger.info("Wrote HTML report: %s", html_report_path)

    if config.CASE_ARCHIVE_ENABLED:
        archive_fn = archive_case or archive_case_for_portal
        archive_fn(
            config=config,
            logger=logger,
            finding_id=finding_id,
            source_filename=file_path.name,
            alert_payload=alert_payload,
            analysis=llm_response,
            report_md_path=report_path,
            report_html_path=html_report_path,
        )

    if config.SPLUNK_SINK_ENABLED:
        if markdown is None:
            raise RuntimeError("Splunk writeback requires markdown report content")
        splunk_result = update_splunk_notable(
            notable_id, markdown, finding_id, config
        )
        logger.info("Splunk update result: %s", splunk_result.get("status"))
