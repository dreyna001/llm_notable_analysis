import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "migrate_embedding_dimensions.py"


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("migrate_embedding_dimensions", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load migration module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


migration = _load_migration_module()


class _FakeExecute:
    def __init__(self, inspections: dict[tuple[str, str, str], migration.TableInspection]):
        self.inspections = inspections
        self.executed: list[tuple[str, str]] = []
        self.fail_on_execute = False

    def __call__(self, dsn: str, sql: str) -> tuple[int, str, str]:
        if "information_schema.tables" in sql:
            for (known_dsn, schema, table), inspection in self.inspections.items():
                if known_dsn == dsn and schema in sql and table in sql:
                    exists = "t" if inspection.exists else "f"
                    type_text = inspection.type_text or ""
                    return 0, f"{exists}|{type_text}\n", ""
            return 0, "f|\n", ""
        self.executed.append((dsn, sql))
        if self.fail_on_execute:
            return 1, "", "migration failed"
        return 0, "", ""


def _write_config(tmpdir: Path, **values: str) -> Path:
    path = tmpdir / "config.env"
    lines = [f"{key}={value}" for key, value in values.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class TestMigrateEmbeddingDimensions(unittest.TestCase):
    def test_build_table_migration_sql_is_transactional_and_clears_chunks_only(self) -> None:
        spec = migration.ChunkTableSpec(
            label="case_chunks",
            dsn="postgresql://example",
            schema="notable_cases",
            table="case_chunks",
            vector_index_names=("case_chunks_embedding_hnsw_idx",),
            post_alter_sql=(
                "UPDATE \"notable_cases\".cases SET retrieval_status = 'pending' "
                "WHERE retrieval_status = 'ready';",
            ),
        )
        sql = migration.build_table_migration_sql(spec, 768)
        self.assertIn("BEGIN;", sql)
        self.assertIn("DELETE FROM \"notable_cases\".\"case_chunks\";", sql)
        self.assertIn('ALTER COLUMN embedding TYPE vector(768);', sql)
        self.assertIn("CREATE INDEX IF NOT EXISTS", sql)
        self.assertIn("retrieval_status = 'pending'", sql)
        self.assertIn("COMMIT;", sql)
        self.assertNotIn("DROP TABLE", sql)

    def test_plan_skips_absent_and_already_migrated_tables(self) -> None:
        execute = _FakeExecute(
            {
                (
                    "postgresql://rag",
                    "notable_rag",
                    "kb_chunks",
                ): migration.TableInspection(exists=False, type_text=None),
                (
                    "postgresql://rag",
                    "notable_rag",
                    "spl_query_chunks",
                ): migration.TableInspection(exists=True, type_text="vector(768)"),
                (
                    "postgresql://cases",
                    "notable_cases",
                    "case_chunks",
                ): migration.TableInspection(exists=True, type_text="vector(1024)"),
            }
        )
        specs = [
            migration.ChunkTableSpec(
                label="general_kb",
                dsn="postgresql://rag",
                schema="notable_rag",
                table="kb_chunks",
                vector_index_names=("idx_kb",),
            ),
            migration.ChunkTableSpec(
                label="spl_query",
                dsn="postgresql://rag",
                schema="notable_rag",
                table="spl_query_chunks",
                vector_index_names=("idx_spl",),
            ),
            migration.ChunkTableSpec(
                label="case_chunks",
                dsn="postgresql://cases",
                schema="notable_cases",
                table="case_chunks",
                vector_index_names=("case_chunks_embedding_hnsw_idx",),
            ),
        ]
        actions = migration.plan_migration(specs, target_dim=768, execute=execute)
        self.assertEqual(actions[0].skip_reason, "table absent")
        self.assertEqual(actions[1].skip_reason, "already vector(768)")
        self.assertFalse(actions[2].skipped)

    def test_invalid_target_dimension_fails_fast(self) -> None:
        execute = _FakeExecute({})
        with self.assertRaisesRegex(ValueError, "Unsupported --target-dim"):
            migration.plan_migration([], target_dim=1024, execute=execute)

    def test_run_migration_dry_run_does_not_execute_alter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_env = _write_config(
                Path(tmpdir),
                RAG_POSTGRES_DSN="postgresql://rag",
                CASE_POSTGRES_DSN="postgresql://cases",
            )
            execute = _FakeExecute(
                {
                    (
                        "postgresql://cases",
                        "notable_cases",
                        "case_chunks",
                    ): migration.TableInspection(exists=True, type_text="vector(1024)"),
                }
            )
            migration.run_migration(
                config_env=config_env,
                portal_env=None,
                target_dim=768,
                dry_run=True,
                execute=execute,
            )
            self.assertEqual(execute.executed, [])

    def test_run_migration_executes_for_pending_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_env = _write_config(
                Path(tmpdir),
                RAG_POSTGRES_DSN="postgresql://rag",
                CASE_POSTGRES_DSN="postgresql://cases",
            )
            execute = _FakeExecute(
                {
                    (
                        "postgresql://cases",
                        "notable_cases",
                        "case_chunks",
                    ): migration.TableInspection(exists=True, type_text="vector(1024)"),
                }
            )
            migration.run_migration(
                config_env=config_env,
                portal_env=None,
                target_dim=768,
                dry_run=False,
                execute=execute,
            )
            self.assertEqual(len(execute.executed), 1)
            self.assertIn("ALTER COLUMN embedding TYPE vector(768);", execute.executed[0][1])

    def test_run_migration_surfaces_execute_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_env = _write_config(
                Path(tmpdir),
                RAG_POSTGRES_DSN="postgresql://rag",
                CASE_POSTGRES_DSN="postgresql://cases",
            )
            execute = _FakeExecute(
                {
                    (
                        "postgresql://cases",
                        "notable_cases",
                        "case_chunks",
                    ): migration.TableInspection(exists=True, type_text="vector(1024)"),
                }
            )
            execute.fail_on_execute = True
            with self.assertRaisesRegex(RuntimeError, "Migration failed"):
                migration.run_migration(
                    config_env=config_env,
                    portal_env=None,
                    target_dim=768,
                    dry_run=False,
                    execute=execute,
                )

    def test_main_defaults_to_granite_target_when_config_still_mixedbread(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_env = _write_config(
                Path(tmpdir),
                RAG_VECTOR_DIMENSIONS="1024",
                RAG_POSTGRES_DSN="postgresql://rag",
                CASE_POSTGRES_DSN="postgresql://cases",
            )
            execute = _FakeExecute(
                {
                    (
                        "postgresql://cases",
                        "notable_cases",
                        "case_chunks",
                    ): migration.TableInspection(exists=True, type_text="vector(1024)"),
                }
            )
            original_execute = migration.default_execute
            migration.default_execute = execute  # type: ignore[method-assign]
            try:
                result = migration.main(
                    [
                        "--config-env",
                        str(config_env),
                        "--dry-run",
                    ]
                )
            finally:
                migration.default_execute = original_execute  # type: ignore[method-assign]
            self.assertEqual(result, 0)
            self.assertEqual(execute.executed, [])

    def test_parse_config_env_rejects_unsafe_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.env"
            path.write_text("bad-key=1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid key"):
                migration.parse_config_env(path)

    def test_build_chunk_table_specs_uses_distinct_dsns(self) -> None:
        specs = migration.build_chunk_table_specs(
            {
                "RAG_POSTGRES_DSN": "postgresql://rag",
                "CASE_POSTGRES_DSN": "postgresql://cases",
            }
        )
        case_spec = next(spec for spec in specs if spec.label == "case_chunks")
        kb_spec = next(spec for spec in specs if spec.label == "general_kb")
        self.assertEqual(case_spec.dsn, "postgresql://cases")
        self.assertEqual(kb_spec.dsn, "postgresql://rag")


if __name__ == "__main__":
    unittest.main()
