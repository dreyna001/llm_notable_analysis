from __future__ import annotations

import ast
import os
import runpy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "deploy" / "local"


def _assignment(module: ast.Module, name: str) -> ast.AST:
    for statement in module.body:
        if isinstance(statement, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == name
                for target in statement.targets
            ):
                return statement.value
    raise AssertionError(f"Missing assignment: {name}")


def test_compose_exposes_only_emulators_with_persistent_health_checked_services() -> None:
    compose = (LOCAL / "docker-compose.yml").read_text(encoding="utf-8")

    assert "mcr.microsoft.com/azure-storage/azurite:3.35.0" in compose
    assert "mcr.microsoft.com/cosmosdb/linux/azure-cosmos-emulator:vnext-latest" in compose
    assert "http://127.0.0.1:8080/ready" in compose
    assert "azurite-data:/data" in compose
    assert "cosmos-data:/data" in compose
    assert "127.0.0.1:10000:10000" in compose
    assert "127.0.0.1:8081:8081" in compose
    assert "function" not in compose.lower()


def test_local_env_matches_runtime_names_and_contains_no_remote_credentials() -> None:
    env_text = (LOCAL / "local.env.example").read_text(encoding="utf-8")

    for expected in (
        "LOCAL_EMULATION=true",
        "AZURITE_CONNECTION_STRING=UseDevelopmentStorage=true",
        "INPUT_CONTAINER_NAME=input",
        "OUTPUT_CONTAINER_NAME=output",
        "ANALYZER_QUEUE_NAME=notable-analysis-jobs",
        "CASE_EMBED_QUEUE_NAME=case-embed-invocations",
        "COSMOS_DATABASE_NAME=notable-local",
    ):
        assert expected in env_text
    assert "AZURE_CLIENT_SECRET" not in env_text
    assert "servicebus.windows.net" not in env_text


def test_bootstrap_resource_contract_matches_bicep_and_runtime_partition_keys() -> None:
    module = ast.parse((LOCAL / "bootstrap_emulators.py").read_text(encoding="utf-8"))
    storage_containers = ast.literal_eval(_assignment(module, "STORAGE_CONTAINERS"))
    storage_queues = ast.literal_eval(_assignment(module, "STORAGE_QUEUES"))
    cosmos_containers = ast.literal_eval(_assignment(module, "COSMOS_CONTAINERS"))

    assert storage_containers == ("input", "output")
    assert storage_queues == (
        "notable-analysis-jobs",
        "notable-analysis-jobs-poison",
        "case-embed-invocations",
        "case-embed-invocations-poison",
        "webjobs-blobtrigger-poison",
    )
    assert {entry[2] for entry in cosmos_containers} == {
        "/id",
        "/case_id",
        "/snow_sys_id",
        "/job_name",
        "/user_id",
        "/session_id",
    }
    assert {entry[0]: entry[3] for entry in cosmos_containers} == {
        "SIDE_EFFECT_IDEMPOTENCY_CONTAINER": -1,
        "CASE_INDEX_CONTAINER": -1,
        "DISPOSITION_CONTAINER": -1,
        "DISPOSITION_SYNC_STATE_CONTAINER": None,
        "CHAT_SESSIONS_CONTAINER": -1,
        "CHAT_MESSAGES_CONTAINER": -1,
    }


def test_bash_and_powershell_bootstraps_start_compose_then_provision() -> None:
    bash = (LOCAL / "bootstrap.sh").read_text(encoding="utf-8")
    powershell = (LOCAL / "bootstrap.ps1").read_text(encoding="utf-8")

    assert "docker compose" in bash and "bootstrap_emulators.py" in bash
    assert "docker compose" in powershell and "bootstrap_emulators.py" in powershell
    assert "--wait azurite cosmos" in bash
    assert "--wait azurite cosmos" in powershell


def test_bootstrap_env_file_overrides_inherited_values_and_rejects_remote_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap = runpy.run_path(str(LOCAL / "bootstrap_emulators.py"))
    env_file = tmp_path / "local.env"
    env_file.write_text(
        "LOCAL_EMULATION=true\n"
        "AZURITE_CONNECTION_STRING=UseDevelopmentStorage=true\n"
        "COSMOS_ENDPOINT=http://127.0.0.1:8081\n"
        "COSMOS_EMULATOR_KEY=YWJjZA==\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("COSMOS_ENDPOINT", "https://production.documents.azure.com")

    bootstrap["_load_env"](env_file)
    bootstrap["_validate_local_contract"]()

    assert os.environ["COSMOS_ENDPOINT"] == "http://127.0.0.1:8081"

    os.environ["COSMOS_ENDPOINT"] = "https://production.documents.azure.com"
    with pytest.raises(SystemExit, match="loopback"):
        bootstrap["_validate_local_contract"]()
