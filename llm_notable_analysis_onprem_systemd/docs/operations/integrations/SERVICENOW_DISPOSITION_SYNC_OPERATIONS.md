# ServiceNow Closed Disposition Sync Operations

**Status:** Partial v1 shipped on-prem (sync module, schema, systemd job). Portal read
API and disposition retention purge are not shipped yet. For outbound incident
draft/create, see [`SERVICENOW_OPERATIONS.md`](SERVICENOW_OPERATIONS.md).

## What This Controls

Scheduled **read-only** pull of **closed** ServiceNow security incidents into
Postgres (`notable_dispositions.servicenow_closed_incidents`). Analyst close
codes and notes become a separate record from model `verdict` on archived cases.
Optional link to a portal case when correlation IDs match.

Direction: **ServiceNow -> our database only**. No portal or analyzer writeback
to ServiceNow.

## Shipped In v1

- Postgres schema: `deploy/postgres/dispositions_schema.sql`
- Sync module: `onprem_service/servicenow_disposition_sync.py`
- CLI: `scripts/run_disposition_sync.py`
- systemd: `notable-disposition-sync.service` + `notable-disposition-sync.timer`
- Field/code map loaders and normalization via `verdicts.normalize_verdict()`

For closed-ticket historical RAG (separate schema and sync), see
[`SERVICENOW_CLOSED_TICKET_OPERATIONS.md`](SERVICENOW_CLOSED_TICKET_OPERATIONS.md).

## Not Shipped Yet

- Portal UI / read API for analyst dispositions
- Automatic purge of rows past `expires_at` (`DISPOSITION_RETENTION_DAYS`)

AWS inbound sync v1 ships in `s3_notable_pipeline` (DynamoDB + scheduled Lambda).
See [`../../../s3_notable_pipeline/docs/operations/integrations/SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md`](../../../s3_notable_pipeline/docs/operations/integrations/SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md).

## Customer Prerequisites

### ServiceNow instance

- Security Incident table available (default: **`sn_si_incident`**).
- Table API read access for a dedicated sync service account.
- HTTPS **`SERVICENOW_BASE_URL`** reachable from the sync job host.

### Closed tickets must expose these fields

Map names are configurable; defaults assume standard Security Incident columns:

| Field | Purpose |
|-------|---------|
| `sys_id` | Stable row key |
| `number` | INC/SIR display |
| `state` | Closed filter |
| `closed_at` | Backfill window |
| `sys_updated_on` | Incremental sync cursor |
| `close_code` | Analyst disposition (TP/FP/benign/etc.) |
| `close_notes` | Resolution text |
| `correlation_id` | Link to archived notable/case |

Optional: `short_description`, `correlation_display`, custom rule-name field
(example: `u_alert_rule_name`).

### Closed state values

Sync includes only rows whose `state` is in the customer field map list for
backfill. Incremental runs query by `sys_updated_on` and deactivate reopened rows.
Default closed values: `3`, `7`, `closed`, `resolved`. Confirm with the ServiceNow
owner; custom workflows often use different codes.

### Case linking (optional)

Link works only when ServiceNow **`correlation_id`** exactly matches a value
already on an archived case (`cases.correlation_id` or alert JSON
`notable_id` / `event_id` / `sid`). No fuzzy or time-based matching in v1.

Populate **`correlation_id` on the ServiceNow ticket** when analysts close
security work tied to a Splunk notable the analyzer processed.

## Customer Decisions

### Enable sync?

**Setting:** `SERVICENOW_DISPOSITION_SYNC_ENABLED` (default `false`)

Keep disabled until field map, close-code map, read token, and Postgres schema
are validated in a lab instance.

### Which table and fields?

**Settings:** `SERVICENOW_DISPOSITION_FIELD_MAP`,
`SERVICENOW_DISPOSITION_CODE_MAP`

- Field map: table name, column names, `closed_state_values`.
- Code map: map ServiceNow close codes to `likely_malicious`, `likely_benign`,
  or `unknown`.
- Examples:
  [`deploy/servicenow/disposition_field_map.example.json`](../../../deploy/servicenow/disposition_field_map.example.json),
  [`deploy/servicenow/disposition_code_map.example.json`](../../../deploy/servicenow/disposition_code_map.example.json).

Unmapped close text falls back to the same normalization rules as model verdicts.

### Read token vs create token

**Setting:** `SERVICENOW_DISPOSITION_SYNC_TOKEN`

- Use a **read-only** Table API user for sync.
- Do **not** reuse `SERVICENOW_API_TOKEN` (incident create writeback).
- Reuse **`SERVICENOW_BASE_URL`** only.

### Backfill and retention

| Setting | Default | Purpose |
|---------|---------|---------|
| `SERVICENOW_DISPOSITION_BACKFILL_DAYS` | `90` | First-run lookback by `closed_at` |
| `DISPOSITION_RETENTION_DAYS` | `365` | Row expiry in our database |

Incremental runs use **`sys_updated_on`**, not `closed_at`.

## ServiceNow API Shape

```http
GET {SERVICENOW_BASE_URL}/api/now/table/{table}
Authorization: Bearer {SERVICENOW_DISPOSITION_SYNC_TOKEN}
```

Query (incremental):

```text
sysparm_query=sys_updated_on>{cursor}
sysparm_fields=<mapped columns>
sysparm_limit=100
sysparm_order_by=sys_updated_on
```

Backfill (no cursor yet):

```text
sysparm_query=closed_at>{backfill_start}^stateIN{closed_states}
```

Auth failure: job fails; cursor not advanced. Reopened tickets: row kept,
marked inactive in our database.

## Config Quick Reference

| Area | Primary variables |
|------|-------------------|
| Enablement | `SERVICENOW_DISPOSITION_SYNC_ENABLED` |
| Endpoint/auth | `SERVICENOW_BASE_URL`, `SERVICENOW_DISPOSITION_SYNC_TOKEN` |
| Mapping | `SERVICENOW_DISPOSITION_FIELD_MAP`, `SERVICENOW_DISPOSITION_CODE_MAP` |
| Database | `CASE_POSTGRES_DSN` (same Postgres as case archive) |
| Bounds | `SERVICENOW_DISPOSITION_BACKFILL_DAYS`, `DISPOSITION_RETENTION_DAYS` |

Postgres DDL:
[`deploy/postgres/dispositions_schema.sql`](../../../deploy/postgres/dispositions_schema.sql).

Apply via `scripts/setup_postgres_case_archive.sh` (runs disposition schema after
case archive schema).

## Validation And Rollout

1. Apply disposition schema on a lab Postgres host.
2. Deploy customer field map and close-code map from a sample closed incident.
3. Enable sync with read-only token; confirm rows in
   `notable_dispositions.servicenow_closed_incidents`.
4. Close a test incident with known `close_code` and `correlation_id`; confirm
   normalized disposition and optional `case_id` link.
5. Reopen a test incident; confirm row marked inactive.
6. Promote only after ServiceNow owner signs off state codes and field map.

Manual run:

```bash
/opt/notable-analyzer/venv/bin/python /opt/notable-analyzer/scripts/run_disposition_sync.py
```

Enable timer:

```bash
sudo systemctl enable --now notable-disposition-sync.timer
```

## Related Docs

- [`SERVICENOW_OPERATIONS.md`](SERVICENOW_OPERATIONS.md) — Outbound draft/create (shipped)
- [`../analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../analyst_portal/ANALYST_PORTAL_OPERATIONS.md) — Case archive (model verdict today)
- [`../../planning/SERVICENOW_CLOSED_DISPOSITION_SYNC_PLAN.md`](../../planning/SERVICENOW_CLOSED_DISPOSITION_SYNC_PLAN.md) — Planning source
- [`../../technical_specs/feature_enhancements_technical_spec.md`](../../technical_specs/feature_enhancements_technical_spec.md) — Outbound ServiceNow contract
