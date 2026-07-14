"""Portable sync-policy tests using native Azure persistence objects."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from azure_notable_pipeline.config import Config
from azure_notable_pipeline.servicenow_disposition_sync import (
    DispositionSyncAuthError,
    JOB_NAME,
    SyncCursor,
    _iter_table_api_pages,
    _process_row,
    load_code_map,
    load_field_map,
    run_disposition_sync,
)


class MemoryStore:
    def __init__(self) -> None:
        self.dispositions: dict[str, dict[str, Any]] = {}
        self.checkpoints: dict[str, dict[str, Any]] = {}
        self.fail_disposition_writes = False

    def get_disposition(self, _container: str, snow_sys_id: str):
        value = self.dispositions.get(snow_sys_id)
        return dict(value) if value else None

    def upsert_disposition(self, _container: str, disposition: dict[str, Any]):
        if self.fail_disposition_writes:
            raise RuntimeError("Cosmos disposition upsert failed")
        self.dispositions[disposition["snow_sys_id"]] = dict(disposition)
        return disposition

    def get_sync_checkpoint(self, _container: str, job_name: str):
        value = self.checkpoints.get(job_name)
        return dict(value) if value else None

    def upsert_sync_checkpoint(self, _container: str, checkpoint: dict[str, Any]):
        self.checkpoints[checkpoint["job_name"]] = dict(checkpoint)
        return checkpoint

    def find_cases_by_correlation(self, *_args: Any, **_kwargs: Any):
        return []

    def list_cases(self, *_args: Any, **_kwargs: Any):
        return []


class FakeResponse:
    status_code = 200
    content = b"{}"

    def json(self):
        return {"result": []}

    def raise_for_status(self):
        return None


def _config(tmp_path: Path) -> Config:
    field_map = tmp_path / "fields.json"
    field_map.write_text(
        json.dumps(
            {
                "table": "sn_si_incident",
                "fields": {
                    "sys_id": "sys_id",
                    "number": "number",
                    "state": "incident_state",
                    "closed_at": "closed_at",
                    "sys_updated_on": "sys_updated_on",
                    "close_code": "close_code",
                    "close_notes": "close_notes",
                    "correlation_id": "correlation_id",
                },
                "closed_state_values": ["3", "7"],
            }
        ),
        encoding="utf-8",
    )
    code_map = tmp_path / "codes.json"
    code_map.write_text(
        json.dumps(
            {
                "likely_malicious": ["true positive"],
                "likely_benign": ["false positive"],
                "unknown": ["inconclusive"],
            }
        ),
        encoding="utf-8",
    )
    return Config(
        SERVICENOW_DISPOSITION_SYNC_ENABLED=True,
        SERVICENOW_BASE_URL="https://example.service-now.com",
        SERVICENOW_DISPOSITION_SYNC_TOKEN="read-token",
        SERVICENOW_DISPOSITION_FIELD_MAP=str(field_map),
        SERVICENOW_DISPOSITION_CODE_MAP=str(code_map),
        DISPOSITION_CONTAINER="dispositions",
        DISPOSITION_SYNC_STATE_CONTAINER="sync-state",
    )


def _row(*, state: str = "3") -> dict[str, str]:
    return {
        "sys_id": "snow-1",
        "number": "SIR001",
        "incident_state": state,
        "closed_at": "2026-01-01 09:00:00",
        "sys_updated_on": "2026-01-01 10:00:00",
        "close_code": "true positive",
        "close_notes": "confirmed malicious",
        "correlation_id": "",
    }


def test_duplicate_payload_is_idempotently_skipped(tmp_path, monkeypatch) -> None:
    config = _config(tmp_path)
    store = MemoryStore()
    monkeypatch.setattr(
        "azure_notable_pipeline.servicenow_disposition_sync._iter_table_api_pages",
        lambda **_kwargs: iter([[_row()]]),
    )

    first = run_disposition_sync(config=config, cosmos_store=store)
    second = run_disposition_sync(config=config, cosmos_store=store)

    assert first["upserted"] == 1
    assert second["skipped"] == 1
    assert len(store.dispositions) == 1


def test_reopened_incident_is_deactivated(tmp_path) -> None:
    config = _config(tmp_path)
    store = MemoryStore()
    store.dispositions["snow-1"] = {
        "snow_sys_id": "snow-1",
        "is_active": True,
        "payload_hash": "old",
    }
    field_map = load_field_map(config.SERVICENOW_DISPOSITION_FIELD_MAP)
    outcome = _process_row(
        raw_row=_row(state="2"),
        field_map=field_map,
        code_map=load_code_map(config.SERVICENOW_DISPOSITION_CODE_MAP),
        closed_states=field_map["closed_state_values"],
        config=config,
        cosmos_store=store,  # type: ignore[arg-type]
        blob_service=None,
        run_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    assert outcome["action"] == "deactivated"
    assert store.dispositions["snow-1"]["is_active"] is False


def test_auth_and_cosmos_write_failures_do_not_advance_checkpoint(tmp_path, monkeypatch) -> None:
    config = _config(tmp_path)
    store = MemoryStore()
    monkeypatch.setattr(
        "azure_notable_pipeline.servicenow_disposition_sync._iter_table_api_pages",
        lambda **_kwargs: (_ for _ in ()).throw(DispositionSyncAuthError("auth failed")),
    )
    auth_result = run_disposition_sync(config=config, cosmos_store=store)
    assert auth_result["status"] == "error"
    assert auth_result["cursor_advanced"] is False
    assert store.checkpoints == {}

    store.fail_disposition_writes = True
    monkeypatch.setattr(
        "azure_notable_pipeline.servicenow_disposition_sync._iter_table_api_pages",
        lambda **_kwargs: iter([[_row()]]),
    )
    write_result = run_disposition_sync(config=config, cosmos_store=store)
    assert write_result["status"] == "error"
    assert write_result["cursor_advanced"] is False
    assert JOB_NAME not in store.checkpoints


def test_backfill_and_incremental_queries_preserve_state_policy(tmp_path, monkeypatch) -> None:
    config = _config(tmp_path)
    field_map = load_field_map(config.SERVICENOW_DISPOSITION_FIELD_MAP)
    calls: list[dict[str, Any]] = []

    def request(**kwargs: Any):
        calls.append(kwargs)
        return FakeResponse()

    monkeypatch.setattr(
        "azure_notable_pipeline.servicenow_disposition_sync._request_with_retry",
        request,
    )
    common = {
        "base_url": config.SERVICENOW_BASE_URL,
        "table_name": field_map["table"],
        "api_fields": list(field_map["fields"].values()),
        "closed_states": field_map["closed_state_values"],
        "field_map": field_map,
        "backfill_days": 90,
        "run_at": datetime(2026, 1, 2, tzinfo=UTC),
        "token": "token",
        "session": object(),
        "timeout_seconds": 15,
    }
    list(_iter_table_api_pages(cursor=None, **common))
    list(_iter_table_api_pages(cursor=datetime(2026, 1, 1, tzinfo=UTC), **common))

    assert "^incident_stateIN3,7" in calls[0]["params"]["sysparm_query"]
    assert "sys_updated_on>" in calls[1]["params"]["sysparm_query"]
    assert "^NQsys_updated_on=" in calls[1]["params"]["sysparm_query"]
    assert "^sys_id>" in calls[1]["params"]["sysparm_query"]
    assert calls[1]["params"]["sysparm_query"].endswith(
        "^ORDERBYsys_updated_on^ORDERBYsys_id"
    )
    assert "incident_stateIN" not in calls[1]["params"]["sysparm_query"]


def test_compound_cursor_drains_more_than_run_limit_at_same_timestamp(
    tmp_path, monkeypatch
) -> None:
    config = _config(tmp_path)
    store = MemoryStore()
    rows = [
        {**_row(), "sys_id": f"snow-{index:04d}", "number": f"SIR{index:04d}"}
        for index in range(501)
    ]
    observed_cursors = []

    def pages(**kwargs):
        cursor = kwargs["cursor"]
        observed_cursors.append(cursor)
        if cursor is None:
            return iter([rows[:500]])
        assert cursor == SyncCursor(
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC), "snow-0499"
        )
        return iter([[rows[500]]])

    monkeypatch.setattr(
        "azure_notable_pipeline.servicenow_disposition_sync._iter_table_api_pages",
        pages,
    )

    first = run_disposition_sync(config=config, cosmos_store=store)
    second = run_disposition_sync(config=config, cosmos_store=store)

    assert first["fetched"] == 500
    assert second["fetched"] == 1
    assert len(store.dispositions) == 501
    assert observed_cursors[0] is None
    assert store.checkpoints[JOB_NAME]["cursor_value"] == "2026-01-01T10:00:00Z"
    assert store.checkpoints[JOB_NAME]["cursor_sys_id"] == "snow-0500"


def test_timestamp_only_checkpoint_replays_boundary_for_backward_compatibility(
    tmp_path, monkeypatch
) -> None:
    config = _config(tmp_path)
    store = MemoryStore()
    store.checkpoints[JOB_NAME] = {
        "job_name": JOB_NAME,
        "cursor_value": "2026-01-01T10:00:00Z",
    }
    observed = {}

    def pages(**kwargs):
        observed["cursor"] = kwargs["cursor"]
        return iter([])

    monkeypatch.setattr(
        "azure_notable_pipeline.servicenow_disposition_sync._iter_table_api_pages",
        pages,
    )

    result = run_disposition_sync(config=config, cosmos_store=store)

    assert result["status"] == "success"
    assert observed["cursor"] == SyncCursor(
        datetime(2026, 1, 1, 10, 0, tzinfo=UTC), ""
    )


def test_key_vault_token_uses_native_secret_name(tmp_path, monkeypatch) -> None:
    config = _config(tmp_path)
    config.SERVICENOW_DISPOSITION_SYNC_TOKEN = ""
    config.SERVICENOW_DISPOSITION_SYNC_TOKEN_SECRET_NAME = "servicenow-sync-token"
    observed: dict[str, Any] = {}
    monkeypatch.setattr(
        "azure_notable_pipeline.servicenow_disposition_sync.resolve_secret_string",
        lambda **kwargs: observed.update(kwargs) or "resolved-token",
    )
    monkeypatch.setattr(
        "azure_notable_pipeline.servicenow_disposition_sync._iter_table_api_pages",
        lambda **kwargs: observed.update(api_token=kwargs["token"]) or iter([]),
    )

    result = run_disposition_sync(config=config, cosmos_store=MemoryStore())

    assert result["status"] == "success"
    assert observed["secret_name"] == "servicenow-sync-token"
    assert observed["api_token"] == "resolved-token"
    assert "secret_arn" not in observed
