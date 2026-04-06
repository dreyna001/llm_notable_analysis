import unittest

from llm_notable_analysis_onprem_systemd.soar_playbook.phantom_notable_index_to_analyzer import (
    build_notable_query,
    extract_query_rows,
    normalize_notable_row,
    safe_filename,
)


class TestPhantomNotableIndexToAnalyzer(unittest.TestCase):
    def test_build_notable_query_includes_index_status_and_limit(self) -> None:
        query = build_notable_query(
            lookback_minutes=15,
            statuses=("new", "open"),
            max_notables=25,
            query_fields=("summary", "event_id", "_time"),
        )

        self.assertIn("search index=notable earliest=-15m latest=now", query)
        self.assertIn('status="new"', query)
        self.assertIn('status="open"', query)
        self.assertIn("| fields summary, event_id, _time", query)
        self.assertIn("| head 25", query)

    def test_extract_query_rows_supports_data_and_action_results_shapes(self) -> None:
        results = [
            {"data": [{"finding_id": "a-1"}]},
            {"action_results": [{"data": [{"finding_id": "b-2"}]}]},
        ]

        rows = extract_query_rows(results)

        self.assertEqual(rows, [{"finding_id": "a-1"}, {"finding_id": "b-2"}])

    def test_normalize_notable_row_preserves_known_fields_and_unknowns(self) -> None:
        row = {
            "finding_id": "abc-123",
            "summary": "Suspicious Authentication Pattern",
            "search_name": "Auth Rule",
            "severity": "high",
            "status": "new",
            "_time": "2026-01-01T00:00:00Z",
        }

        payload = normalize_notable_row(row)

        self.assertEqual(payload["finding_id"], "abc-123")
        self.assertEqual(payload["summary"], "Suspicious Authentication Pattern")
        self.assertEqual(payload["search_name"], "Auth Rule")
        self.assertEqual(payload["severity"], "high")
        self.assertEqual(payload["status"], "new")
        self.assertEqual(payload["alert_time"], "2026-01-01T00:00:00Z")
        self.assertEqual(payload["threat_category"], "unknown")
        self.assertEqual(payload["risk_score"], "unknown")
        self.assertEqual(payload["ingest_source"], "splunk_soar_phantom_notable_index")

    def test_safe_filename_sanitizes_identifier(self) -> None:
        self.assertEqual(safe_filename("abc/../123:foo"), "abc____123_foo")


if __name__ == "__main__":
    unittest.main()
