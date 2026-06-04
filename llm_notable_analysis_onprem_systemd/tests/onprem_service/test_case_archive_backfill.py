import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

# Tests run with PYTHONPATH pointing at the src layout and intentionally verify
# parser/config helpers on the operator script.
# pylint: disable=import-error,no-name-in-module,protected-access
from llm_notable_analysis_onprem_systemd.onprem_service.config import Config


def _load_script_module():
    script_path = (
        Path(__file__).resolve().parents[2] / "scripts" / "backfill_case_archive.py"
    )
    spec = importlib.util.spec_from_file_location("backfill_case_archive_script", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestCaseArchiveBackfill(unittest.TestCase):
    def test_build_backfill_case_id_uses_stable_prefix_rule(self) -> None:
        module = _load_script_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            report = root / "case.md"
            report.write_text("# Suspicious PowerShell\nBody", encoding="utf-8")

            case_id = module.build_backfill_case_id(
                report,
                report.read_text(encoding="utf-8"),
                root=root,
            )

        self.assertRegex(case_id, r"^backfill:[0-9a-f]{16}$")

    def test_build_legacy_case_record_marks_markdown_only(self) -> None:
        module = _load_script_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            report = root / "case.md"
            report.write_text("# Suspicious PowerShell\nBody", encoding="utf-8")

            record = module.build_legacy_case_record(
                config=Config(REPORT_DIR=root),
                report_path=report,
                root=root,
            )

        self.assertEqual(record.backfill_status, "legacy_summary")
        self.assertEqual(record.source_completeness, "markdown_only")
        self.assertEqual(record.retrieval_status, "not_indexed")
        self.assertIsNone(record.analysis)
        self.assertEqual(record.search_name, "Suspicious PowerShell")
        self.assertTrue(record.archive_metadata["legacy_markdown_only"])

    def test_dry_run_backfill_reports_importable_markdown(self) -> None:
        module = _load_script_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "case-a.md").write_text("# A\nBody", encoding="utf-8")
            (root / "case-b.txt").write_text("ignored", encoding="utf-8")

            result = module.dry_run_backfill(
                config=Config(REPORT_DIR=root),
                report_dir=root,
            )

        self.assertEqual(result["dry_run"], 1)
        self.assertEqual(result["reports_found"], 1)
        self.assertEqual(result["cases"], 1)
        self.assertEqual(len(result["case_ids"]), 1)

    def test_execute_backfill_writes_each_record(self) -> None:
        module = _load_script_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "case-a.md").write_text("# A\nBody", encoding="utf-8")
            config = Config(REPORT_DIR=root)

            with patch.object(module, "write_case_record_with_retries") as write:
                result = module.execute_backfill(config=config, report_dir=root)

        self.assertEqual(result["dry_run"], 0)
        self.assertEqual(result["cases"], 1)
        write.assert_called_once()
        record = write.call_args.kwargs["record"]
        self.assertEqual(record.backfill_status, "legacy_summary")
        self.assertIs(write.call_args.kwargs["config"], config)

    def test_main_dry_run_prints_json(self) -> None:
        module = _load_script_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "case-a.md").write_text("# A\nBody", encoding="utf-8")
            with patch.object(module, "load_config", return_value=Config(REPORT_DIR=root)), patch(
                "builtins.print"
            ) as mock_print:
                exit_code = module.main(["--dry-run", "--report-dir", str(root)])

        self.assertEqual(exit_code, 0)
        printed = json.loads(mock_print.call_args.args[0])
        self.assertEqual(printed["dry_run"], 1)
        self.assertEqual(printed["cases"], 1)

    def test_config_env_loader_preserves_existing_environment(self) -> None:
        module = _load_script_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            config_env = Path(tmpdir) / "config.env"
            config_env.write_text(
                "\n".join(
                    [
                        "CASE_POSTGRES_SCHEMA=from_file",
                        "export CASE_RETENTION_DAYS=91",
                    ]
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"CASE_POSTGRES_SCHEMA": "existing"}):
                module._load_config_env(config_env)
                self.assertEqual(os.environ["CASE_POSTGRES_SCHEMA"], "existing")
                self.assertEqual(os.environ["CASE_RETENTION_DAYS"], "91")


if __name__ == "__main__":
    unittest.main()
