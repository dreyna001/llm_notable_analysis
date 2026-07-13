"""Offline tests for the native disposition-sync runtime entrypoint."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from azure_notable_pipeline.config import Config
from azure_notable_pipeline.disposition_sync_handler import (
    DispositionSyncInvocationError,
    handle_timer,
    invoke_disposition_sync,
    main,
)


class FakeStore:
    def __init__(self) -> None:
        self.dispositions: dict[str, dict[str, Any]] = {}
        self.checkpoints: dict[str, dict[str, Any]] = {}

    def get_disposition(self, _container: str, snow_sys_id: str):
        return self.dispositions.get(snow_sys_id)

    def upsert_disposition(self, _container: str, disposition: dict[str, Any]):
        self.dispositions[disposition["snow_sys_id"]] = dict(disposition)
        return disposition

    def get_sync_checkpoint(self, _container: str, job_name: str):
        return self.checkpoints.get(job_name)

    def upsert_sync_checkpoint(self, _container: str, checkpoint: dict[str, Any]):
        self.checkpoints[checkpoint["job_name"]] = dict(checkpoint)
        return checkpoint

    def find_cases_by_correlation(self, *_args: Any, **_kwargs: Any):
        return []

    def list_cases(self, *_args: Any, **_kwargs: Any):
        return []


def _config() -> Config:
    return Config(
        SERVICENOW_DISPOSITION_SYNC_ENABLED=True,
        OUTPUT_STORAGE_ACCOUNT_URL="https://storage.blob.core.windows.net",
        DISPOSITION_CONTAINER="dispositions",
        DISPOSITION_SYNC_STATE_CONTAINER="sync-state",
    )


def test_manual_invoke_builds_only_native_azure_dependencies(monkeypatch) -> None:
    config = _config()
    store = FakeStore()
    blob_service = object()
    observed: dict[str, Any] = {}

    monkeypatch.setattr(
        "azure_notable_pipeline.disposition_sync_handler.CosmosStore.from_config",
        lambda selected: store if selected is config else None,
    )
    monkeypatch.setattr(
        "azure_notable_pipeline.disposition_sync_handler.blob_service_client",
        lambda account_url: blob_service
        if account_url == "https://storage.blob.core.windows.net"
        else None,
    )

    def workflow(**kwargs: Any) -> dict[str, Any]:
        observed.update(kwargs)
        return {"status": "success", "cursor_advanced": False}

    result = invoke_disposition_sync(config=config, workflow=workflow)

    assert result == {"status": "success", "cursor_advanced": False}
    assert observed["cosmos_store"] is store
    assert observed["blob_service"] is blob_service
    assert "event" not in observed
    assert "context" not in observed


def test_disabled_manual_invoke_skips_without_constructing_cloud_clients(monkeypatch) -> None:
    monkeypatch.setattr(
        "azure_notable_pipeline.disposition_sync_handler.CosmosStore.from_config",
        lambda _config: pytest.fail("disabled sync must not construct Cosmos"),
    )
    monkeypatch.setattr(
        "azure_notable_pipeline.disposition_sync_handler.blob_service_client",
        lambda _url: pytest.fail("disabled sync must not construct Blob Storage"),
    )

    result = invoke_disposition_sync(
        config=Config(SERVICENOW_DISPOSITION_SYNC_ENABLED=False)
    )

    assert result["status"] == "skipped"
    assert result["message"] == "disposition sync disabled"


def test_dry_run_simulates_writes_without_mutating_cosmos() -> None:
    store = FakeStore()

    def workflow(**kwargs: Any) -> dict[str, Any]:
        persistence = kwargs["cosmos_store"]
        persistence.upsert_disposition(
            "dispositions",
            {"snow_sys_id": "snow-1", "payload_hash": "hash-1"},
        )
        assert persistence.get_disposition("dispositions", "snow-1")["payload_hash"] == "hash-1"
        persistence.upsert_sync_checkpoint(
            "sync-state",
            {"job_name": "servicenow_closed", "cursor_value": "2026-01-01T00:00:00Z"},
        )
        return {"status": "success", "cursor_advanced": True, "message": ""}

    result = invoke_disposition_sync(
        config=_config(),
        cosmos_store=store,  # type: ignore[arg-type]
        blob_service=object(),
        dry_run=True,
        workflow=workflow,
    )

    assert store.dispositions == {}
    assert store.checkpoints == {}
    assert result == {
        "status": "success",
        "cursor_advanced": False,
        "would_advance_cursor": True,
        "dry_run": True,
        "message": "dry run; no Cosmos writes or checkpoint advancement performed",
    }


def test_timer_failure_raises_so_azure_records_failed_invocation(monkeypatch) -> None:
    monkeypatch.setattr(
        "azure_notable_pipeline.disposition_sync_handler.invoke_disposition_sync",
        lambda: {"status": "error", "message": "ServiceNow auth failed"},
    )

    with pytest.raises(DispositionSyncInvocationError, match="ServiceNow auth failed"):
        handle_timer(SimpleNamespace(past_due=False))


def test_manual_cli_dry_run_returns_structured_result(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "azure_notable_pipeline.disposition_sync_handler.invoke_disposition_sync",
        lambda *, dry_run: {
            "status": "success",
            "dry_run": dry_run,
            "cursor_advanced": False,
        },
    )

    assert main(["--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "success",
        "dry_run": True,
        "cursor_advanced": False,
    }
