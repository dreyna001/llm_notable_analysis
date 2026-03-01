import unittest
from pathlib import Path
import tempfile
import os

from llm_notable_analysis_onprem.onprem_service.ingest import (
    discover_files,
    get_notable_id,
    normalize_notable,
)
from llm_notable_analysis_onprem.onprem_service.config import Config
from llm_notable_analysis_onprem.onprem_service.onprem_main import _format_alert_for_llm


class TestIngestAndFormatting(unittest.TestCase):
    def test_normalize_notable_json_extracts_risk_fields(self) -> None:
        content = (
            '{"summary":"Suspicious login",'
            '"risk_score":85,'
            '"source_product":"Splunk ES",'
            '"threat_category":"Credential Access",'
            '"user":"admin"}'
        )
        out = normalize_notable(content, content_type="json")

        self.assertEqual(out["summary"], "Suspicious login")
        self.assertEqual(out["risk_index"]["risk_score"], 85)
        self.assertEqual(out["risk_index"]["source_product"], "Splunk ES")
        self.assertEqual(out["risk_index"]["threat_category"], "Credential Access")
        self.assertEqual(out["raw_log"]["user"], "admin")

    def test_normalize_notable_text_uses_raw_event(self) -> None:
        out = normalize_notable("plain alert text", content_type="text")
        self.assertEqual(out["summary"], "plain alert text")
        self.assertEqual(out["raw_log"], {"raw_event": "plain alert text"})
        self.assertEqual(out["risk_index"]["source_product"], "OnPrem_Pipeline")

    def test_get_notable_id_prefers_notable_id_and_sanitizes(self) -> None:
        raw_log = {"notable_id": "abc/../def:ghi"}
        notable_id = get_notable_id(raw_log, Path("fallback.json"))
        self.assertEqual(notable_id, "abc____def_ghi")

    def test_format_alert_for_llm_includes_primitives_and_lists_only(self) -> None:
        normalized = {
            "summary": "Suspicious auth event",
            "risk_index": {
                "risk_score": 72,
                "source_product": "Splunk ES",
                "threat_category": "Credential Access",
            },
            "raw_log": {
                "user": "admin",
                "src_ip": "203.0.113.45",
                "flags": ["a", "b"],
                "nested": {"ignored": True},
            },
        }
        alert_text = _format_alert_for_llm(normalized)
        self.assertIn("**Summary:** Suspicious auth event", alert_text)
        self.assertIn("**Risk Score:** 72", alert_text)
        self.assertIn("**user:** admin", alert_text)
        self.assertIn("**flags:** a, b", alert_text)
        self.assertNotIn("ignored", alert_text)

    def test_discover_files_returns_fifo_order(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            incoming = Path(td) / "incoming"
            incoming.mkdir(parents=True, exist_ok=True)
            older = incoming / "a.json"
            newer = incoming / "b.txt"
            older.write_text("{}", encoding="utf-8")
            newer.write_text("{}", encoding="utf-8")
            # Ensure deterministic mtime ordering
            os.utime(older, (1000, 1000))
            os.utime(newer, (2000, 2000))

            config = Config(INCOMING_DIR=incoming)
            files = discover_files(config)

            self.assertEqual([f.name for f in files], ["a.json", "b.txt"])


if __name__ == "__main__":
    unittest.main()
