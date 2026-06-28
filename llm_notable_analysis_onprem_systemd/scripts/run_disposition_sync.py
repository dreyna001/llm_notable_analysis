#!/usr/bin/env python3
"""Run one ServiceNow closed disposition sync cycle."""

from __future__ import annotations

import logging
import sys

from llm_notable_analysis_onprem_systemd.onprem_service.config import load_config
from llm_notable_analysis_onprem_systemd.onprem_service.servicenow_disposition_sync import (
    run_disposition_sync,
)


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    config = load_config()
    summary = run_disposition_sync(config)
    if summary.skipped and not summary.enabled:
        logging.info("ServiceNow disposition sync disabled; exiting")
        return 0
    if summary.errors:
        for error in summary.errors:
            logging.error("ServiceNow disposition sync error: %s", error)
        return 1
    logging.info(
        "ServiceNow disposition sync complete fetched=%s upserted=%s skipped_noop=%s "
        "deactivated=%s linked=%s malformed=%s cursor_advanced=%s",
        summary.fetched,
        summary.upserted,
        summary.skipped_noop,
        summary.deactivated,
        summary.linked,
        summary.malformed,
        summary.cursor_advanced,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
