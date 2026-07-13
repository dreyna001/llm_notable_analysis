"""Phase 0 Azure-native boundary and packaging checks."""

from __future__ import annotations

import ast
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "azure_notable_pipeline"


def test_production_source_does_not_import_boto3() -> None:
    for source_path in PACKAGE_ROOT.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        imported = {
            node.names[0].name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import) and node.names
        }
        imported.update(
            str(node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        assert "boto3" not in imported, source_path


def test_required_native_boundaries_exist() -> None:
    required = {
        "azure_clients.py",
        "blob_store.py",
        "secret_provider.py",
        "queue_publisher.py",
        "azure_openai_gateway.py",
        "azure_search_retrieval.py",
        "cosmos_store.py",
        "blob_handler.py",
        "function_app.py",
    }
    assert required <= {path.name for path in PACKAGE_ROOT.glob("*.py")}


def test_host_queue_settings_preserve_one_message_per_instance() -> None:
    host = json.loads((PROJECT_ROOT / "host.json").read_text(encoding="utf-8"))
    queue_settings = host["extensions"]["queues"]
    assert queue_settings["batchSize"] == 1
    assert queue_settings["newBatchThreshold"] == 0
    assert queue_settings["maxDequeueCount"] == 5


def test_frontend_chat_timeout_is_azure_safe() -> None:
    client = (
        PROJECT_ROOT / "frontend" / "analyst-portal" / "src" / "api" / "client.ts"
    ).read_text(encoding="utf-8")
    assert "const CHAT_TIMEOUT_MS = 220_000;" in client
