"""Tests for ServiceNow closed disposition sync (AWS)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.config import Config
from s3_notable_pipeline.servicenow_disposition_sync import (
    JOB_NAME,
    load_code_map,
    load_field_map,
    normalize_disposition,
    payload_hash,
    run_disposition_sync,
    _iter_table_api_pages,
    _process_row,
    _prepare_ddb_attributes,
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _field_map_file(tmp: Path) -> Path:
    path = tmp / "field_map.json"
    _write_json(
        path,
        {
            "table": "sn_si_incident",
            "fields": {
                "sys_id": "sys_id",
                "number": "number",
                "state": "state",
                "closed_at": "closed_at",
                "sys_updated_on": "sys_updated_on",
                "close_code": "close_code",
                "close_notes": "close_notes",
                "correlation_id": "correlation_id",
                "short_description": "short_description",
                "correlation_display": "correlation_display",
                "search_name": "u_alert_rule_name",
            },
            "closed_state_values": ["3", "7", "closed", "resolved"],
        },
    )
    return path


def _code_map_file(tmp: Path) -> Path:
    path = tmp / "code_map.json"
    _write_json(
        path,
        {
            "likely_malicious": ["true positive"],
            "likely_benign": ["false positive"],
            "unknown": ["inconclusive"],
        },
    )
    return path


def _sync_config(tmp: Path, **overrides: Any) -> Config:
    values = {
        "SERVICENOW_DISPOSITION_SYNC_ENABLED": True,
        "SERVICENOW_BASE_URL": "https://example.service-now.com",
        "SERVICENOW_DISPOSITION_SYNC_TOKEN": "read-token",
        "SERVICENOW_DISPOSITION_FIELD_MAP": str(_field_map_file(tmp)),
        "SERVICENOW_DISPOSITION_CODE_MAP": str(_code_map_file(tmp)),
        "DISPOSITION_TABLE": "dispositions",
        "DISPOSITION_SYNC_STATE_TABLE": "disposition-sync-state",
        "CASE_INDEX_TABLE": "case-index",
        "CASE_ARCHIVE_BUCKET": "case-bucket",
        "CASE_ARCHIVE_PREFIX": "cases",
    }
    values.update(overrides)
    return Config(**values)


class FakeResponse:
    def __init__(self, *, status_code: int = 200, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.content = b"{}"

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttpSession:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        return FakeResponse(payload={"result": self.rows})


class FakeDynamoDbClient:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        self.puts: list[dict[str, Any]] = []
        self.queries: list[dict[str, Any]] = []

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        table = kwargs["TableName"]
        key = kwargs["Key"]
        pk_name, pk_value = next(iter(key.items()))
        pk = pk_value.get("S") or pk_value.get("N") or str(pk_value)
        item = self.items.get((table, pk))
        return {"Item": item} if item else {}

    def put_item(self, **kwargs: Any) -> None:
        self.puts.append(kwargs)
        table = kwargs["TableName"]
        item = kwargs["Item"]
        if "snow_sys_id" in item:
            pk = item["snow_sys_id"]["S"]
            self.items[(table, pk)] = item
        elif "job_name" in item:
            pk = item["job_name"]["S"]
            self.items[(table, pk)] = item

    def query(self, **kwargs: Any) -> dict[str, Any]:
        self.queries.append(kwargs)
        return {
            "Items": [
                {
                    "case_id": {"S": "case-abc"},
                    "processed_at": {"S": "2024-06-01T10:00:00Z"},
                    "processed_at_case_id": {"S": "2024-06-01T10:00:00Z#case-abc"},
                    "correlation_id": {"S": "corr-1"},
                }
            ]
        }


class FakeS3Client:
    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        body = json.dumps(
            {
                "alert_payload": {
                    "notable_id": "corr-1",
                    "event_id": "evt-1",
                }
            }
        ).encode("utf-8")
        return {"Body": MagicMock(read=lambda: body)}


class ServiceNowDispositionSyncTests(unittest.TestCase):
    def test_load_maps_validate_required_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            field_map = load_field_map(str(_field_map_file(tmp)))
            code_map = load_code_map(str(_code_map_file(tmp)))
        self.assertEqual(field_map["table"], "sn_si_incident")
        self.assertIn("likely_malicious", code_map)

    def test_normalize_disposition_uses_code_map_then_verdict_fallback(self) -> None:
        code_map = {
            "likely_malicious": ["true positive"],
            "likely_benign": [],
            "unknown": [],
        }
        normalized, raw = normalize_disposition("true positive", code_map)
        self.assertEqual(normalized, "likely_malicious")
        self.assertEqual(raw, "true positive")

        fallback, raw_fallback = normalize_disposition("confirmed malicious activity", code_map)
        self.assertEqual(fallback, "likely_malicious")
        self.assertEqual(raw_fallback, "confirmed malicious activity")

    def test_payload_hash_is_stable(self) -> None:
        mapped = {"sys_id": "abc", "state": "3", "close_code": "false positive"}
        self.assertEqual(payload_hash(mapped), payload_hash(dict(mapped)))

    def test_run_sync_disabled_exits_without_calls(self) -> None:
        config = Config(SERVICENOW_DISPOSITION_SYNC_ENABLED=False)
        dynamodb = FakeDynamoDbClient()
        result = run_disposition_sync(
            config=config,
            dynamodb_client=dynamodb,
            s3_client=FakeS3Client(),
        )
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(dynamodb.puts, [])

    @patch("s3_notable_pipeline.servicenow_disposition_sync._iter_table_api_pages")
    def test_run_sync_upserts_closed_incident_and_advances_cursor(
        self,
        mock_pages: MagicMock,
    ) -> None:
        mock_pages.return_value = iter(
            [
                [
                    {
                        "sys_id": "snow-1",
                        "number": "SIR001",
                        "state": "3",
                        "closed_at": "2024-06-01 09:00:00",
                        "sys_updated_on": "2024-06-01 10:00:00",
                        "close_code": "true positive",
                        "close_notes": "confirmed malicious",
                        "correlation_id": "corr-1",
                    }
                ]
            ]
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _sync_config(Path(tmpdir))
            dynamodb = FakeDynamoDbClient()
            result = run_disposition_sync(
                config=config,
                dynamodb_client=dynamodb,
                s3_client=FakeS3Client(),
                http_session=FakeHttpSession([]),
                now=datetime(2024, 6, 2, tzinfo=UTC),
            )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["upserted"], 1)
        self.assertTrue(result["cursor_advanced"])
        cursor_item = dynamodb.items.get((config.DISPOSITION_SYNC_STATE_TABLE, JOB_NAME))
        self.assertIsNotNone(cursor_item)
        disposition_item = dynamodb.items.get((config.DISPOSITION_TABLE, "snow-1"))
        self.assertIsNotNone(disposition_item)
        self.assertEqual(disposition_item["disposition_normalized"]["S"], "likely_malicious")
        self.assertEqual(disposition_item["case_id"]["S"], "case-abc")

    @patch("s3_notable_pipeline.servicenow_disposition_sync._iter_table_api_pages")
    def test_run_sync_skips_duplicate_payload_hash(
        self,
        mock_pages: MagicMock,
    ) -> None:
        row = {
            "sys_id": "snow-1",
            "number": "SIR001",
            "state": "3",
            "closed_at": "2024-06-01 09:00:00",
            "sys_updated_on": "2024-06-01 10:00:00",
            "close_code": "true positive",
            "close_notes": "confirmed malicious",
            "correlation_id": "",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _sync_config(Path(tmpdir))
            dynamodb = FakeDynamoDbClient()
            mock_pages.return_value = iter([[row]])
            first = run_disposition_sync(
                config=config,
                dynamodb_client=dynamodb,
                s3_client=FakeS3Client(),
                http_session=FakeHttpSession([]),
                now=datetime(2024, 6, 2, tzinfo=UTC),
            )
            mock_pages.return_value = iter([[row]])
            second = run_disposition_sync(
                config=config,
                dynamodb_client=dynamodb,
                s3_client=FakeS3Client(),
                http_session=FakeHttpSession([]),
                now=datetime(2024, 6, 3, tzinfo=UTC),
            )
        self.assertEqual(first["upserted"], 1)
        self.assertEqual(second["skipped"], 1)
        disposition_puts = [
            put for put in dynamodb.puts if put["TableName"] == config.DISPOSITION_TABLE
        ]
        self.assertEqual(len(disposition_puts), 1)

    def test_process_row_marks_reopened_incident_inactive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            config = _sync_config(tmp)
            dynamodb = FakeDynamoDbClient()
            dynamodb.put_item(
                TableName=config.DISPOSITION_TABLE,
                Item={
                    "snow_sys_id": {"S": "snow-1"},
                    "is_active": {"BOOL": True},
                    "payload_hash": {"S": "old-hash"},
                    "sys_updated_on": {"S": "2024-06-01T10:00:00Z"},
                },
            )
            field_map = load_field_map(config.SERVICENOW_DISPOSITION_FIELD_MAP)
            code_map = load_code_map(config.SERVICENOW_DISPOSITION_CODE_MAP)
            outcome = _process_row(
                raw_row={
                    "sys_id": "snow-1",
                    "number": "SIR001",
                    "state": "2",
                    "closed_at": "2024-06-01 09:00:00",
                    "sys_updated_on": "2024-06-02 10:00:00",
                    "close_code": "true positive",
                    "close_notes": "",
                    "correlation_id": "",
                },
                field_map=field_map,
                code_map=code_map,
                closed_states=field_map["closed_state_values"],
                config=config,
                dynamodb_client=dynamodb,
                s3_client=None,
                run_at=datetime(2024, 6, 3, tzinfo=UTC),
            )
        self.assertEqual(outcome["action"], "deactivated")
        item = dynamodb.items[(config.DISPOSITION_TABLE, "snow-1")]
        self.assertFalse(item["is_active"]["BOOL"])

    @patch("s3_notable_pipeline.servicenow_disposition_sync._iter_table_api_pages")
    def test_auth_failure_does_not_advance_cursor(self, mock_pages: MagicMock) -> None:
        from s3_notable_pipeline.servicenow_disposition_sync import DispositionSyncAuthError

        mock_pages.side_effect = DispositionSyncAuthError("auth failed")
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _sync_config(Path(tmpdir))
            dynamodb = FakeDynamoDbClient()
            result = run_disposition_sync(
                config=config,
                dynamodb_client=dynamodb,
                s3_client=FakeS3Client(),
                http_session=FakeHttpSession([]),
            )
        self.assertEqual(result["status"], "error")
        self.assertFalse(result["cursor_advanced"])
        self.assertIsNone(dynamodb.items.get((config.DISPOSITION_SYNC_STATE_TABLE, JOB_NAME)))

    def test_prepare_ddb_attributes_omits_empty_gsi_keys(self) -> None:
        prepared = _prepare_ddb_attributes(
            {
                "snow_sys_id": "snow-1",
                "correlation_id": "",
                "case_id": "",
                "state": "3",
            }
        )
        self.assertNotIn("correlation_id", prepared)
        self.assertNotIn("case_id", prepared)
        self.assertEqual(prepared["snow_sys_id"], "snow-1")

    def test_process_row_upsert_omits_empty_correlation_id_from_put(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            config = _sync_config(tmp)
            dynamodb = FakeDynamoDbClient()
            field_map = load_field_map(config.SERVICENOW_DISPOSITION_FIELD_MAP)
            code_map = load_code_map(config.SERVICENOW_DISPOSITION_CODE_MAP)
            outcome = _process_row(
                raw_row={
                    "sys_id": "snow-empty-corr",
                    "number": "SIR002",
                    "state": "3",
                    "closed_at": "2024-06-01 09:00:00",
                    "sys_updated_on": "2024-06-01 10:00:00",
                    "close_code": "true positive",
                    "close_notes": "notes",
                    "correlation_id": "",
                },
                field_map=field_map,
                code_map=code_map,
                closed_states=field_map["closed_state_values"],
                config=config,
                dynamodb_client=dynamodb,
                s3_client=None,
                run_at=datetime(2024, 6, 2, tzinfo=UTC),
            )
        self.assertEqual(outcome["action"], "upserted")
        put_item = next(
            put for put in dynamodb.puts if put["TableName"] == config.DISPOSITION_TABLE
        )
        self.assertNotIn("correlation_id", put_item["Item"])
        self.assertNotIn("case_id", put_item["Item"])

    @patch("s3_notable_pipeline.servicenow_disposition_sync._request_with_retry")
    def test_iter_table_api_pages_incremental_query_has_no_state_filter(
        self,
        request_mock: MagicMock,
    ) -> None:
        request_mock.return_value = FakeResponse(payload={"result": []})
        with tempfile.TemporaryDirectory() as tmpdir:
            field_map = load_field_map(str(_field_map_file(Path(tmpdir))))
        cursor = datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC)
        session = MagicMock()
        list(
            _iter_table_api_pages(
                base_url="https://example.service-now.com",
                table_name=field_map["table"],
                api_fields=list(field_map["fields"].values()),
                closed_states=field_map["closed_state_values"],
                field_map=field_map,
                cursor=cursor,
                backfill_days=90,
                run_at=datetime(2024, 6, 2, tzinfo=UTC),
                token="token",
                session=session,
                timeout_seconds=15,
            )
        )
        params = request_mock.call_args.kwargs["params"]
        self.assertIn("sys_updated_on>", params["sysparm_query"])
        self.assertNotIn("stateIN", params["sysparm_query"])

    @patch("s3_notable_pipeline.servicenow_disposition_sync._request_with_retry")
    def test_iter_table_api_pages_backfill_uses_field_map_state_column(
        self,
        request_mock: MagicMock,
    ) -> None:
        request_mock.return_value = FakeResponse(payload={"result": []})
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            path = tmp / "field_map.json"
            _write_json(
                path,
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
                    "closed_state_values": ["3"],
                },
            )
            field_map = load_field_map(str(path))
        session = MagicMock()
        list(
            _iter_table_api_pages(
                base_url="https://example.service-now.com",
                table_name=field_map["table"],
                api_fields=list(field_map["fields"].values()),
                closed_states=field_map["closed_state_values"],
                field_map=field_map,
                cursor=None,
                backfill_days=90,
                run_at=datetime(2024, 6, 2, tzinfo=UTC),
                token="token",
                session=session,
                timeout_seconds=15,
            )
        )
        params = request_mock.call_args.kwargs["params"]
        self.assertIn("incident_stateIN", params["sysparm_query"])
        self.assertNotIn("^stateIN", params["sysparm_query"])

    @patch("s3_notable_pipeline.servicenow_disposition_sync._iter_table_api_pages")
    def test_run_sync_does_not_advance_cursor_on_storage_failure(
        self,
        mock_pages: MagicMock,
    ) -> None:
        mock_pages.return_value = iter(
            [
                [
                    {
                        "sys_id": "snow-fail",
                        "number": "SIR003",
                        "state": "3",
                        "closed_at": "2024-06-01 09:00:00",
                        "sys_updated_on": "2024-06-01 10:00:00",
                        "close_code": "true positive",
                        "close_notes": "notes",
                        "correlation_id": "corr-1",
                    }
                ]
            ]
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _sync_config(Path(tmpdir))
            dynamodb = FakeDynamoDbClient()
            real_put = dynamodb.put_item

            def failing_put(**kwargs: Any) -> None:
                if kwargs.get("TableName") == config.DISPOSITION_TABLE:
                    raise RuntimeError("dynamodb put failed")
                real_put(**kwargs)

            dynamodb.put_item = failing_put  # type: ignore[method-assign]

            result = run_disposition_sync(
                config=config,
                dynamodb_client=dynamodb,
                s3_client=FakeS3Client(),
                http_session=FakeHttpSession([]),
                now=datetime(2024, 6, 2, tzinfo=UTC),
            )
        self.assertEqual(result["status"], "error")
        self.assertFalse(result["cursor_advanced"])
        self.assertIsNone(dynamodb.items.get((config.DISPOSITION_SYNC_STATE_TABLE, JOB_NAME)))


if __name__ == "__main__":
    unittest.main()
