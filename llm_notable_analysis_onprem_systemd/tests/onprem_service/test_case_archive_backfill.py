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
    def _archive_config(self, root: Path) -> Config:
        return Config(CASE_ARCHIVE_ENABLED=True, REPORT_DIR=root)

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
                config=self._archive_config(root),
                report_path=report,
                root=root,
            )

        self.assertEqual(record.backfill_status, "legacy_summary")
        self.assertEqual(record.source_completeness, "markdown_only")
        self.assertEqual(record.retrieval_status, "not_indexed")
        self.assertIsNone(record.analysis)
        self.assertEqual(record.search_name, "Suspicious PowerShell")
        self.assertTrue(record.archive_metadata["legacy_markdown_only"])
        self.assertIn("content_sha256", record.archive_metadata)
        self.assertIn("source_size_bytes", record.archive_metadata)
        self.assertEqual(record.alert_payload["text_excerpt"], "# Suspicious PowerShell\nBody")
        self.assertFalse(record.alert_payload["text_truncated"])

    def test_dry_run_backfill_reports_importable_markdown(self) -> None:
        module = _load_script_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "case-a.md").write_text("# A\nBody", encoding="utf-8")
            (root / "case-b.txt").write_text("ignored", encoding="utf-8")

            result = module.dry_run_backfill(
                config=self._archive_config(root),
                report_dir=root,
            )

        self.assertEqual(result["dry_run"], 1)
        self.assertEqual(result["reports_found"], 1)
        self.assertEqual(result["cases"], 1)
        self.assertEqual(len(result["case_ids"]), 1)
        self.assertEqual(result["skipped"], [])

    def test_dry_run_reports_missing_directory_without_writes(self) -> None:
        module = _load_script_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "missing"

            result = module.dry_run_backfill(
                config=Config(REPORT_DIR=root),
                report_dir=root,
            )

        self.assertEqual(result["dry_run"], 1)
        self.assertEqual(result["cases"], 0)
        self.assertEqual(result["skipped"][0]["reason"], "report_dir_missing")

    def test_dry_run_respects_batch_size_and_file_size_limits(self) -> None:
        module = _load_script_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "aaa-large.md").write_text("# Large\nToo large", encoding="utf-8")
            (root / "case-a.md").write_text("# A\nBody", encoding="utf-8")
            (root / "case-b.md").write_text("# B\nBody", encoding="utf-8")

            result = module.dry_run_backfill(
                config=self._archive_config(root),
                report_dir=root,
                batch_size=1,
                max_file_bytes=12,
            )

        self.assertEqual(result["reports_found"], 1)
        self.assertEqual(result["cases"], 1)
        self.assertIn("max file size", result["skipped"][0]["reason"])
        self.assertEqual(result["skipped"][1]["reason"], "batch_size_limit_reached")

    def test_dry_run_skips_symlinked_markdown(self) -> None:
        module = _load_script_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "target.md"
            target.write_text("# Target\nBody", encoding="utf-8")
            link = root / "linked.md"
            try:
                link.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            result = module.dry_run_backfill(
                config=self._archive_config(root),
                report_dir=root,
            )

        self.assertEqual(result["reports_found"], 1)
        self.assertEqual(result["cases"], 1)
        self.assertEqual(result["skipped"][0]["path"], str(link))
        self.assertIn("symlink", result["skipped"][0]["reason"])

    def test_execute_backfill_writes_each_record(self) -> None:
        module = _load_script_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "case-a.md").write_text("# A\nBody", encoding="utf-8")
            config = self._archive_config(root)

            with patch.object(module, "write_case_record_with_retries") as write:
                result = module.execute_backfill(config=config, report_dir=root)

        self.assertEqual(result["dry_run"], 0)
        self.assertEqual(result["reports_found"], 1)
        self.assertEqual(result["cases"], 1)
        self.assertEqual(result["failures"], [])
        write.assert_called_once()
        record = write.call_args.kwargs["record"]
        self.assertEqual(record.backfill_status, "legacy_summary")
        self.assertIs(write.call_args.kwargs["config"], config)

    def test_execute_backfill_requires_case_archive_enabled(self) -> None:
        module = _load_script_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "case-a.md").write_text("# A\nBody", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "CASE_ARCHIVE_ENABLED"):
                module.execute_backfill(config=Config(REPORT_DIR=root), report_dir=root)

    def test_execute_backfill_reports_partial_write_failures(self) -> None:
        module = _load_script_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "case-a.md").write_text("# A\nBody", encoding="utf-8")
            (root / "case-b.md").write_text("# B\nBody", encoding="utf-8")
            config = self._archive_config(root)

            with patch.object(
                module,
                "write_case_record_with_retries",
                side_effect=[None, OSError("database unavailable")],
            ):
                result = module.execute_backfill(config=config, report_dir=root)

        self.assertEqual(result["reports_found"], 2)
        self.assertEqual(result["cases"], 1)
        self.assertEqual(len(result["case_ids"]), 1)
        self.assertEqual(len(result["failures"]), 1)
        self.assertIn("database unavailable", result["failures"][0]["reason"])

    def test_main_dry_run_prints_json(self) -> None:
        module = _load_script_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "case-a.md").write_text("# A\nBody", encoding="utf-8")
            with patch.object(
                module,
                "load_config",
                return_value=Config(REPORT_DIR=root),
            ), patch("builtins.print") as mock_print:
                exit_code = module.main(["--dry-run", "--report-dir", str(root)])

        self.assertEqual(exit_code, 0)
        printed = json.loads(mock_print.call_args.args[0])
        self.assertEqual(printed["dry_run"], 1)
        self.assertEqual(printed["cases"], 1)

    def test_main_execute_requires_config_env(self) -> None:
        module = _load_script_module()

        with self.assertRaisesRegex(ValueError, "--config-env is required"):
            module.main([])

    def test_main_execute_returns_nonzero_for_partial_failures(self) -> None:
        module = _load_script_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_env = root / "config.env"
            config_env.write_text("CASE_ARCHIVE_ENABLED=true", encoding="utf-8")
            (root / "case-a.md").write_text("# A\nBody", encoding="utf-8")

            with patch.object(
                module,
                "load_config",
                return_value=self._archive_config(root),
            ), patch.object(
                module,
                "write_case_record_with_retries",
                side_effect=OSError("database unavailable"),
            ), patch("builtins.print") as mock_print:
                exit_code = module.main(
                    [
                        "--report-dir",
                        str(root),
                        "--config-env",
                        str(config_env),
                    ]
                )

        self.assertEqual(exit_code, 1)
        printed = json.loads(mock_print.call_args.args[0])
        self.assertEqual(len(printed["failures"]), 1)

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
