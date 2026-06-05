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
        Path(__file__).resolve().parents[2] / "scripts" / "rebuild_case_chunks.py"
    )
    spec = importlib.util.spec_from_file_location("rebuild_case_chunks_script", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestRebuildCaseChunksScript(unittest.TestCase):
    def test_parse_args_requires_one_target(self) -> None:
        module = _load_script_module()

        with self.assertRaises(SystemExit):
            module._parse_args([])

    def test_main_dry_run_prints_summary_for_one_case(self) -> None:
        module = _load_script_module()
        config = Config()

        with patch.object(module, "load_config", return_value=config), patch.object(
            module,
            "dry_run_case_chunk_rebuild",
            return_value={"cases": 1, "chunks": 9, "skipped": 0},
        ) as dry_run, patch("builtins.print") as mock_print:
            exit_code = module.main(["--case-id", "case-1", "--dry-run"])

        self.assertEqual(exit_code, 0)
        dry_run.assert_called_once_with(config=config, case_id="case-1", batch_size=100)
        printed = json.loads(mock_print.call_args.args[0])
        self.assertEqual(printed, {"cases": 1, "chunks": 9, "dry_run": 1, "skipped": 0})

    def test_main_execute_rebuilds_all_cases(self) -> None:
        module = _load_script_module()
        config = Config(CASE_ARCHIVE_ENABLED=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            config_env = Path(tmpdir) / "config.env"
            config_env.write_text("CASE_ARCHIVE_ENABLED=true", encoding="utf-8")
            with patch.object(module, "load_config", return_value=config), patch.object(
                module,
                "rebuild_case_chunks",
                return_value={"cases": 2, "chunks": 18, "skipped": 0},
            ) as rebuild, patch("builtins.print") as mock_print:
                exit_code = module.main(
                    ["--all", "--batch-size", "25", "--config-env", str(config_env)]
                )

        self.assertEqual(exit_code, 0)
        rebuild.assert_called_once_with(config=config, case_id=None, batch_size=25)
        printed = json.loads(mock_print.call_args.args[0])
        self.assertEqual(printed, {"cases": 2, "chunks": 18, "dry_run": 0, "skipped": 0})

    def test_main_execute_requires_config_env(self) -> None:
        module = _load_script_module()

        with self.assertRaisesRegex(ValueError, "--config-env is required"):
            module.main(["--all"])

    def test_main_execute_requires_case_archive_enabled(self) -> None:
        module = _load_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_env = Path(tmpdir) / "config.env"
            config_env.write_text("CASE_ARCHIVE_ENABLED=false", encoding="utf-8")
            with patch.object(module, "load_config", return_value=Config()):
                with self.assertRaisesRegex(ValueError, "CASE_ARCHIVE_ENABLED"):
                    module.main(["--all", "--config-env", str(config_env)])

    def test_main_rejects_non_positive_batch_size(self) -> None:
        module = _load_script_module()

        with self.assertRaisesRegex(ValueError, "batch-size"):
            module.main(["--all", "--batch-size", "0"])

    def test_config_env_loader_preserves_existing_environment(self) -> None:
        module = _load_script_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_env = Path(tmpdir) / "config.env"
            config_env.write_text(
                "\n".join(
                    [
                        "CASE_POSTGRES_SCHEMA=from_file",
                        "export CASE_QA_MAX_TOTAL_CHUNKS=22",
                    ]
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"CASE_POSTGRES_SCHEMA": "existing"}):
                module._load_config_env(config_env)
                self.assertEqual(os.environ["CASE_POSTGRES_SCHEMA"], "existing")
                self.assertEqual(os.environ["CASE_QA_MAX_TOTAL_CHUNKS"], "22")


if __name__ == "__main__":
    unittest.main()
