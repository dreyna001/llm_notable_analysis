#!/usr/bin/env python3
"""Run one ServiceNow closed ticket raw sync cycle."""

from __future__ import annotations

import logging
import sys

from llm_notable_analysis_onprem_systemd.onprem_service.config import load_config
from llm_notable_analysis_onprem_systemd.onprem_service.servicenow_closed_ticket_sync import (
    run_closed_ticket_sync,
)


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    config = load_config()
    summary = run_closed_ticket_sync(config)
    if summary.skipped and not summary.enabled:
        logging.info("ServiceNow closed ticket sync disabled; exiting")
        return 0
    if summary.errors:
        for error in summary.errors:
            logging.error("ServiceNow closed ticket sync error: %s", error)
        return 1
    if summary.index_errors:
        for error in summary.index_errors:
            logging.error("ServiceNow closed ticket index error: %s", error)
        return 1
    logging.info(
        "ServiceNow closed ticket sync complete fetched=%s persisted=%s skipped_noop=%s "
        "deactivated=%s journals_fetched=%s attachments_fetched=%s attachments_downloaded=%s "
        "malformed=%s reconciled=%s reconcile_incomplete=%s cursor_advanced=%s "
        "retention_tickets_deleted=%s retention_files_deleted=%s "
        "journal_fetches_truncated=%s attachment_metadata_truncated=%s "
        "index_selected=%s index_ready=%s index_failed=%s index_skipped=%s",
        summary.fetched,
        summary.persisted,
        summary.skipped_noop,
        summary.deactivated,
        summary.journals_fetched,
        summary.attachments_fetched,
        summary.attachments_downloaded,
        summary.malformed,
        summary.reconciled,
        summary.reconcile_incomplete,
        summary.cursor_advanced,
        summary.retention_tickets_deleted,
        summary.retention_files_deleted,
        summary.journal_fetches_truncated,
        summary.attachment_metadata_truncated,
        summary.index_selected,
        summary.index_ready,
        summary.index_failed,
        summary.index_skipped,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
