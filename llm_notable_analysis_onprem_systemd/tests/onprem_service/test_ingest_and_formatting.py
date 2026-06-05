import unittest
from pathlib import Path
import tempfile
import os

from llm_notable_analysis_onprem_systemd.onprem_service.ingest import (
    discover_files,
    get_notable_id,
    normalize_notable,
    read_notable_text,
    NotableReadError,
)
from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.onprem_main import _format_alert_for_llm


class TestIngestAndFormatting(unittest.TestCase):
    def test_normalize_notable_json_returns_parsed_payload(self) -> None:
        content = (
            '{"summary":"Suspicious login",'
            '"risk_score":85,'
            '"source_product":"Splunk ES",'
            '"threat_category":"Credential Access",'
            '"user":"admin"}'
        )
        out = normalize_notable(content, content_type="json")

        self.assertEqual(out["summary"], "Suspicious login")
        self.assertEqual(out["risk_score"], 85)
        self.assertEqual(out["source_product"], "Splunk ES")
        self.assertEqual(out["threat_category"], "Credential Access")
        self.assertEqual(out["user"], "admin")

    def test_normalize_notable_text_returns_raw_text(self) -> None:
        out = normalize_notable("plain alert text", content_type="text")
        self.assertEqual(out, "plain alert text")

    def test_get_notable_id_prefers_filename_stem_and_sanitizes(self) -> None:
        raw_log = {"notable_id": "abc/../def:ghi"}
        notable_id = get_notable_id(raw_log, Path("fallback.json"))
        self.assertEqual(notable_id, "fallback")

    def test_format_alert_for_llm_uses_raw_json_for_json_input(self) -> None:
        raw = '{"user":"admin","nested":{"src_ip":"203.0.113.45"}}'
        payload = normalize_notable(raw, content_type="json")
        alert_text = _format_alert_for_llm(
            payload, raw_content=raw, content_type="json"
        )
        self.assertEqual(alert_text, raw)

    def test_format_alert_for_llm_uses_raw_text_for_text_input(self) -> None:
        alert_text = _format_alert_for_llm(
            "plain alert text", raw_content="plain alert text", content_type="text"
        )
        self.assertEqual(alert_text, "plain alert text")

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

    def test_read_notable_text_reads_when_at_byte_limit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "n.json"
            path.write_bytes(b"x" * 64)
            text = read_notable_text(path, max_bytes=64)
            self.assertEqual(len(text), 64)

    def test_read_notable_text_rejects_over_limit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "n.json"
            path.write_bytes(b"x" * 65)
            with self.assertRaises(NotableReadError) as ctx:
                read_notable_text(path, max_bytes=64)
            self.assertIn("exceeds MAX_INPUT_FILE_BYTES", str(ctx.exception))

    def test_discover_files_skips_symlinked_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            incoming = Path(td) / "incoming"
            incoming.mkdir(parents=True, exist_ok=True)
            target = Path(td) / "outside.json"
            target.write_text('{"secret": true}', encoding="utf-8")
            link = incoming / "linked.json"
            try:
                link.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            files = discover_files(Config(INCOMING_DIR=incoming))

        self.assertEqual(files, [])

    def test_read_notable_text_rejects_symlinked_input(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            incoming = Path(td) / "incoming"
            incoming.mkdir(parents=True, exist_ok=True)
            target = Path(td) / "outside.json"
            target.write_text('{"secret": true}', encoding="utf-8")
            link = incoming / "linked.json"
            try:
                link.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            with self.assertRaises(NotableReadError) as ctx:
                read_notable_text(link, max_bytes=1024, root=incoming)

        self.assertIn("symlink", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
