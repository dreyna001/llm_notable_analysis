import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.servicenow_disposition_sync import (
    FieldMap,
    fetch_closed_incidents,
    link_case_ids,
    load_code_map,
    load_field_map,
    map_incident_row,
    normalize_disposition,
    run_disposition_sync,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "servicenow_disposition"
EXAMPLE_CODE_MAP = (
    Path(__file__).resolve().parents[2]
    / "deploy"
    / "servicenow"
    / "disposition_code_map.example.json"
)


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


class TestServiceNowDispositionSync(unittest.TestCase):
    def test_load_field_map_validates_required_fields(self) -> None:
        field_map = load_field_map(FIXTURES_DIR / "field_map_minimal.json")
        self.assertEqual(field_map.table, "sn_si_incident")
        self.assertEqual(field_map.fields["close_code"], "close_code")
        self.assertIn("3", field_map.closed_state_values)

    def test_load_field_map_rejects_missing_required_field(self) -> None:
        invalid = {
            "table": "sn_si_incident",
            "fields": {"sys_id": "sys_id"},
            "closed_state_values": ["3"],
        }
        path = self._write_temp_json(invalid)
        try:
            with self.assertRaisesRegex(ValueError, "fields.number"):
                load_field_map(path)
        finally:
            path.unlink(missing_ok=True)

    def test_load_code_map_requires_buckets(self) -> None:
        code_map = load_code_map(EXAMPLE_CODE_MAP)
        self.assertIn("true positive", code_map.likely_malicious)

    def test_normalize_disposition_uses_code_map_then_verdict_fallback(self) -> None:
        code_map = load_code_map(EXAMPLE_CODE_MAP)
        self.assertEqual(normalize_disposition("S1", code_map), "likely_malicious")
        self.assertEqual(normalize_disposition("S2", code_map), "likely_benign")
        self.assertEqual(normalize_disposition("confirmed malicious", code_map), "likely_malicious")

    def test_map_incident_row_closed_true_positive(self) -> None:
        field_map = load_field_map(FIXTURES_DIR / "field_map_minimal.json")
        code_map = load_code_map(EXAMPLE_CODE_MAP)
        row = _load_fixture("closed_true_positive.json")
        incident = map_incident_row(row, field_map=field_map, code_map=code_map)
        self.assertEqual(incident.snow_sys_id, "abc123closedtp0001")
        self.assertEqual(incident.disposition_normalized, "likely_malicious")
        self.assertTrue(incident.is_active)
        self.assertEqual(incident.correlation_id, "notable-corr-001")
        self.assertTrue(incident.payload_hash)

    def test_map_incident_row_reopened_is_inactive(self) -> None:
        field_map = load_field_map(FIXTURES_DIR / "field_map_minimal.json")
        code_map = load_code_map(EXAMPLE_CODE_MAP)
        row = _load_fixture("reopened_incident.json")
        incident = map_incident_row(row, field_map=field_map, code_map=code_map)
        self.assertFalse(incident.is_active)
        self.assertEqual(incident.state, "2")

    def test_fetch_closed_incidents_backfill_query(self) -> None:
        config = Config(
            SERVICENOW_BASE_URL="https://example.service-now.com",
            SERVICENOW_DISPOSITION_SYNC_TOKEN="token",
        )
        field_map = load_field_map(FIXTURES_DIR / "field_map_minimal.json")
        backfill_start = datetime(2026, 3, 1, tzinfo=timezone.utc)
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"result": [_load_fixture("closed_true_positive.json")]}
        response.raise_for_status = MagicMock()

        with patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_disposition_sync._request_with_retry",
            return_value=response,
        ) as request_mock:
            rows = list(
                fetch_closed_incidents(
                    config,
                    field_map=field_map,
                    cursor=None,
                    backfill_start=backfill_start,
                )
            )

        self.assertEqual(len(rows), 1)
        params = request_mock.call_args.kwargs["params"]
        self.assertIn("closed_at>", params["sysparm_query"])
        self.assertIn("stateIN", params["sysparm_query"])

    def test_fetch_closed_incidents_backfill_uses_field_map_state_column(self) -> None:
        config = Config(
            SERVICENOW_BASE_URL="https://example.service-now.com",
            SERVICENOW_DISPOSITION_SYNC_TOKEN="token",
        )
        field_map = FieldMap(
            table="sn_si_incident",
            fields={
                "sys_id": "sys_id",
                "number": "number",
                "state": "incident_state",
                "closed_at": "closed_at",
                "sys_updated_on": "sys_updated_on",
                "close_code": "close_code",
                "close_notes": "close_notes",
            },
            closed_state_values=("3",),
        )
        backfill_start = datetime(2026, 3, 1, tzinfo=timezone.utc)
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"result": []}
        response.raise_for_status = MagicMock()

        with patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_disposition_sync._request_with_retry",
            return_value=response,
        ) as request_mock:
            list(
                fetch_closed_incidents(
                    config,
                    field_map=field_map,
                    cursor=None,
                    backfill_start=backfill_start,
                )
            )

        params = request_mock.call_args.kwargs["params"]
        self.assertIn("incident_stateIN", params["sysparm_query"])
        self.assertNotIn("^stateIN", params["sysparm_query"])

    def test_fetch_closed_incidents_incremental_query(self) -> None:
        config = Config(
            SERVICENOW_BASE_URL="https://example.service-now.com",
            SERVICENOW_DISPOSITION_SYNC_TOKEN="token",
        )
        field_map = load_field_map(FIXTURES_DIR / "field_map_minimal.json")
        cursor = datetime(2026, 6, 1, tzinfo=timezone.utc)
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"result": []}
        response.raise_for_status = MagicMock()

        with patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_disposition_sync._request_with_retry",
            return_value=response,
        ) as request_mock:
            list(
                fetch_closed_incidents(
                    config,
                    field_map=field_map,
                    cursor=cursor,
                    backfill_start=cursor,
                )
            )

        params = request_mock.call_args.kwargs["params"]
        self.assertIn("sys_updated_on>", params["sysparm_query"])
        self.assertNotIn("stateIN", params["sysparm_query"])

    def test_fetch_closed_incidents_auth_failure(self) -> None:
        config = Config(
            SERVICENOW_BASE_URL="https://example.service-now.com",
            SERVICENOW_DISPOSITION_SYNC_TOKEN="token",
        )
        field_map = load_field_map(FIXTURES_DIR / "field_map_minimal.json")
        response = MagicMock()
        response.status_code = 401
        response.raise_for_status.side_effect = requests.HTTPError("401 Client Error")

        with patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_disposition_sync._request_with_retry",
            side_effect=requests.HTTPError("401 Client Error"),
        ):
            with self.assertRaises(requests.HTTPError):
                list(
                    fetch_closed_incidents(
                        config,
                        field_map=field_map,
                        cursor=datetime(2026, 6, 1, tzinfo=timezone.utc),
                        backfill_start=datetime(2026, 3, 1, tzinfo=timezone.utc),
                    )
                )

    def test_link_case_ids_priority_and_tie_break(self) -> None:
        conn = MagicMock()
        conn.execute.return_value = MagicMock(
            fetchone=MagicMock(return_value=("case-latest",))
        )
        links = link_case_ids(
            conn,
            case_schema="notable_cases",
            correlation_ids=["corr-1"],
        )
        self.assertEqual(links["corr-1"], "case-latest")
        sql = conn.execute.call_args.args[0]
        self.assertIn("ORDER BY processed_at DESC", sql)

    def test_run_disposition_sync_disabled(self) -> None:
        config = Config(SERVICENOW_DISPOSITION_SYNC_ENABLED=False)
        summary = run_disposition_sync(config, connect=MagicMock())
        self.assertTrue(summary.skipped)
        self.assertFalse(summary.enabled)

    def test_run_disposition_sync_upserts_and_links(self) -> None:
        field_map_path = FIXTURES_DIR / "field_map_minimal.json"
        config = Config(
            SERVICENOW_DISPOSITION_SYNC_ENABLED=True,
            SERVICENOW_DISPOSITION_SYNC_TOKEN="token",
            SERVICENOW_BASE_URL="https://example.service-now.com",
            SERVICENOW_DISPOSITION_FIELD_MAP=field_map_path,
            SERVICENOW_DISPOSITION_CODE_MAP=EXAMPLE_CODE_MAP,
            CASE_POSTGRES_DSN="postgresql://test@127.0.0.1:5432/test",
        )
        conn = MagicMock()
        cursor_reads = iter(
            [
                MagicMock(fetchone=MagicMock(return_value=None)),
                MagicMock(fetchone=MagicMock(return_value=None)),
            ]
        )
        conn.execute.side_effect = lambda *args, **kwargs: next(cursor_reads, MagicMock(rowcount=1))

        with patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_disposition_sync.fetch_closed_incidents",
            return_value=[_load_fixture("closed_true_positive.json")],
        ):
            summary = run_disposition_sync(config, connect=lambda _dsn: conn)

        self.assertEqual(summary.fetched, 1)
        self.assertEqual(summary.upserted, 1)
        self.assertTrue(summary.cursor_advanced)
        conn.commit.assert_called_once()

    def test_run_disposition_sync_skips_noop_hash(self) -> None:
        field_map_path = FIXTURES_DIR / "field_map_minimal.json"
        config = Config(
            SERVICENOW_DISPOSITION_SYNC_ENABLED=True,
            SERVICENOW_DISPOSITION_SYNC_TOKEN="token",
            SERVICENOW_BASE_URL="https://example.service-now.com",
            SERVICENOW_DISPOSITION_FIELD_MAP=field_map_path,
            SERVICENOW_DISPOSITION_CODE_MAP=EXAMPLE_CODE_MAP,
            CASE_POSTGRES_DSN="postgresql://test@127.0.0.1:5432/test",
        )
        field_map = load_field_map(field_map_path)
        code_map = load_code_map(EXAMPLE_CODE_MAP)
        incident = map_incident_row(
            _load_fixture("closed_true_positive.json"),
            field_map=field_map,
            code_map=code_map,
        )
        conn = MagicMock()

        def execute_side_effect(*args, **kwargs):
            sql = args[0] if args else ""
            if "FROM notable_dispositions.sync_state" in sql:
                return MagicMock(fetchone=MagicMock(return_value=None))
            if "SELECT payload_hash" in sql:
                return MagicMock(fetchone=MagicMock(return_value=(incident.payload_hash,)))
            if "INSERT INTO notable_dispositions.servicenow_closed_incidents" in sql:
                raise AssertionError("upsert should be skipped for unchanged payload hash")
            return MagicMock(fetchone=MagicMock(return_value=None), rowcount=0)

        conn.execute.side_effect = execute_side_effect

        with patch(
            "llm_notable_analysis_onprem_systemd.onprem_service.servicenow_disposition_sync.fetch_closed_incidents",
            return_value=[_load_fixture("closed_true_positive.json")],
        ):
            summary = run_disposition_sync(config, connect=lambda _dsn: conn)

        self.assertEqual(summary.skipped_noop, 1)
        self.assertEqual(summary.upserted, 0)

    def _write_temp_json(self, payload: dict) -> Path:
        path = FIXTURES_DIR / "_temp_invalid_field_map.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
