import logging
import unittest
from unittest.mock import patch

# Tests run with PYTHONPATH pointing at the src layout.
# pylint: disable=import-error,no-name-in-module

from llm_notable_analysis_onprem_systemd.onprem_service.case_archive_flow import (
    archive_case_for_portal,
)
from llm_notable_analysis_onprem_systemd.onprem_service.case_search import (
    CaseChunkWriteError,
)
from llm_notable_analysis_onprem_systemd.onprem_service.case_store import (
    CaseArchiveConflictError,
    CaseArchiveWriteError,
)
from llm_notable_analysis_onprem_systemd.onprem_service.config import Config


class TestCaseArchiveFlow(unittest.TestCase):
    def test_archive_write_failure_is_deferred_without_indexing(self) -> None:
        config = Config()
        logger = logging.getLogger("test_archive_write_failure")

        with patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.case_archive_flow.write_case_archive_record",
            side_effect=CaseArchiveWriteError("postgres unavailable"),
        ) as write_case, patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.case_archive_flow.store_case_chunks"
        ) as store_chunks:
            archived = archive_case_for_portal(
                config=config,
                logger=logger,
                source_filename="transport-a.json",
                finding_id="transport-a",
                alert_payload={"notable_id": "abc-123", "summary": "alert"},
                analysis={"alert_reconciliation": {}},
                report_md_path="/reports/transport-a.md",
                report_html_path=None,
            )

        self.assertFalse(archived)
        write_case.assert_called_once()
        self.assertEqual(write_case.call_args.kwargs["case_id"], "abc-123")
        store_chunks.assert_not_called()

    def test_chunk_failure_marks_retrieval_failed_and_defers_indexing(self) -> None:
        config = Config()
        logger = logging.getLogger("test_chunk_failure")

        with patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.case_archive_flow.write_case_archive_record",
            return_value="case-record",
        ) as write_case, patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.case_archive_flow.store_case_chunks",
            side_effect=CaseChunkWriteError("embedding failed"),
        ) as store_chunks, patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.case_archive_flow.mark_case_retrieval_status"
        ) as mark_status:
            archived = archive_case_for_portal(
                config=config,
                logger=logger,
                source_filename="transport-b.json",
                finding_id="transport-b",
                alert_payload={"notable_id": "abc-123", "summary": "alert"},
                analysis={"alert_reconciliation": {}},
                report_md_path="/reports/transport-b.md",
                report_html_path=None,
            )

        self.assertFalse(archived)
        write_case.assert_called_once()
        store_chunks.assert_called_once_with(record="case-record", config=config)
        mark_status.assert_called_once_with(
            config=config,
            case_id="abc-123",
            status="failed",
        )

    def test_identity_conflict_is_deferred_without_quarantining_ingest(self) -> None:
        config = Config()
        logger = logging.getLogger("test_archive_conflict")

        with patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.case_archive_flow.write_case_archive_record",
            side_effect=CaseArchiveConflictError("case collision"),
        ) as write_case, patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.case_archive_flow.store_case_chunks"
        ) as store_chunks:
            archived = archive_case_for_portal(
                config=config,
                logger=logger,
                source_filename="transport-c.json",
                finding_id="transport-c",
                alert_payload={"notable_id": "abc-123", "summary": "alert"},
                analysis={"alert_reconciliation": {}},
                report_md_path="/reports/transport-c.md",
                report_html_path=None,
            )

        self.assertFalse(archived)
        write_case.assert_called_once()
        store_chunks.assert_not_called()


if __name__ == "__main__":
    unittest.main()
