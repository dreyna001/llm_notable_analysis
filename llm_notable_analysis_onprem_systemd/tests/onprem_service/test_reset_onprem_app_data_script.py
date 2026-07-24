import os
from pathlib import Path
import subprocess
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "reset_onprem_app_data.sh"


class TestResetOnpremAppDataScript(unittest.TestCase):
    def _write_config(self, path: Path, data_root: Path) -> None:
        path.write_text(
            "\n".join(
                [
                    "CASE_POSTGRES_DSN=postgresql://notable_analyzer@127.0.0.1:5432/notable_rag",
                    "CASE_POSTGRES_SCHEMA=notable_cases",
                    f"INCOMING_DIR={data_root / 'incoming'}",
                    f"PROCESSED_DIR={data_root / 'processed'}",
                    f"QUARANTINE_DIR={data_root / 'quarantine'}",
                    f"REPORT_DIR={data_root / 'reports'}",
                    f"ARCHIVE_DIR={data_root / 'archive'}",
                    f"SIDE_EFFECT_IDEMPOTENCY_DIR={data_root / 'idempotency'}",
                    f"RAG_SQLITE_PATH={data_root / 'rag' / 'kb.sqlite3'}",
                    f"RAG_FAISS_PATH={data_root / 'rag' / 'kb.faiss'}",
                    "RAG_POSTGRES_SCHEMA=notable_rag",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    def test_default_mode_is_dry_run_and_preserves_rag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.env"
            data_root = root / "runtime"
            self._write_config(config_path, data_root)
            sentinel = data_root / "incoming" / "keep.json"
            sentinel.parent.mkdir(parents=True)
            sentinel.write_text("{}", encoding="utf-8")

            result = subprocess.run(
                ["bash", str(SCRIPT), "--config-env", str(config_path)],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("Mode: dry-run", result.stdout)
            self.assertIn(
                "Preserve PostgreSQL RAG schema: notable_rag", result.stdout
            )
            self.assertIn("Preserve RAG_SQLITE_PATH", result.stdout)
            self.assertIn("Preserve RAG_FAISS_PATH", result.stdout)
            self.assertTrue(sentinel.exists())

    def test_rejects_broad_reset_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.env"
            self._write_config(config_path, root / "runtime")
            with config_path.open("a", encoding="utf-8") as config_file:
                config_file.write("INCOMING_DIR=/var/notables\n")

            result = subprocess.run(
                ["bash", str(SCRIPT), "--config-env", str(config_path)],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("too broad to reset safely", result.stderr)

    def test_rejects_reset_directory_that_contains_rag_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.env"
            data_root = root / "runtime"
            self._write_config(config_path, data_root)
            with config_path.open("a", encoding="utf-8") as config_file:
                config_file.write(
                    f"RAG_SQLITE_PATH={data_root / 'archive' / 'kb.sqlite3'}\n"
                )

            result = subprocess.run(
                ["bash", str(SCRIPT), "--config-env", str(config_path)],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("protected RAG path overlaps", result.stderr)

    def test_dry_run_resolves_approved_incoming_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.env"
            data_root = root / "runtime"
            approved_target = root / "sftp" / "incoming"
            approved_target.mkdir(parents=True)
            self._write_config(config_path, data_root)
            incoming_link = data_root / "incoming"
            incoming_link.parent.mkdir(parents=True)
            incoming_link.symlink_to(approved_target, target_is_directory=True)

            result = subprocess.run(
                ["bash", str(SCRIPT), "--config-env", str(config_path)],
                check=False,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "EXPECTED_INCOMING_SYMLINK_TARGET": str(approved_target),
                },
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn(
                f"Clear INCOMING_DIR contents: {approved_target}",
                result.stdout,
            )

    def test_rejects_unapproved_incoming_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.env"
            data_root = root / "runtime"
            unexpected_target = root / "unexpected" / "incoming"
            unexpected_target.mkdir(parents=True)
            self._write_config(config_path, data_root)
            incoming_link = data_root / "incoming"
            incoming_link.parent.mkdir(parents=True)
            incoming_link.symlink_to(unexpected_target, target_is_directory=True)

            result = subprocess.run(
                ["bash", str(SCRIPT), "--config-env", str(config_path)],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "symlink target does not match the approved target",
                result.stderr,
            )

    def test_yes_requires_execute(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.env"
            self._write_config(config_path, root / "runtime")

            result = subprocess.run(
                [
                    "bash",
                    str(SCRIPT),
                    "--config-env",
                    str(config_path),
                    "--yes",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--yes requires --execute", result.stderr)

    def test_reset_preserves_runtime_directory_trees(self) -> None:
        script = SCRIPT.read_text(encoding="utf-8")

        self.assertIn(
            'find "$reset_dir" -xdev -mindepth 1 ! -type d -delete',
            script,
        )
        self.assertNotIn(
            'find "$reset_dir" -xdev -depth -mindepth 1 -delete',
            script,
        )


if __name__ == "__main__":
    unittest.main()
