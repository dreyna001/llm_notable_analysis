# ServiceNow Closed Disposition Sync Plan

## Status

Planning on branch `feature/servicenow-closed-disposition-sync`. Branch is current with
`origin/main` (merged). Not implemented.

Planning artifacts in repo:

- `deploy/postgres/dispositions_schema.sql` — DDL sketch
- `deploy/servicenow/disposition_field_map.example.json` — default field map for `sn_si_incident`
- `deploy/servicenow/disposition_code_map.example.json` — customer close-code overrides

## Problem

The case archive stores **model** outcomes (`cases.verdict` from
`analysis.alert_reconciliation`). Analyst **closed dispositions** (true positive,
false positive, benign, inconclusive, close notes) usually live in ServiceNow
after triage, not in the analyzer pipeline.

We cannot today:

- ingest historical closed security incidents from ServiceNow
- incrementally sync new closures
- compare model verdict vs analyst disposition
- reuse past dispositions for retrieval, tuning, or eval (future)

Existing RAG chunk tables (`kb_chunks`, `spl_query_chunks`,
`elasticsearch_query_chunks`) are for **document corpora**, not structured
disposition records. `notable_cases.cases` is for **analyzer-processed** alerts
with retention and schema tied to file-drop ingest.

## Goal

Pull **closed** security incident dispositions from ServiceNow into Postgres on a
schedule, keep them current, and optionally link rows to archived `case_id` when
correlation keys match.

V1 is **read-only sync** (ServiceNow -> our DB). No portal writes back to
ServiceNow.

## Assumptions (locked for planning)

| Topic | Assumption |
|-------|------------|
| Source of truth | ServiceNow holds analyst dispositions for closed security work |
| Table | Default **`sn_si_incident`**; overridable via field map JSON |
| Scope of sync | **Closed / resolved** records only (not open/active queue) |
| Direction | Inbound sync only in v1 |
| Credentials | Read-only ServiceNow API user via **separate token** from draft/create |
| Identity | Stable external key = ServiceNow `sys_id` (plus `number` for display) |
| Link to archive | Deterministic correlation match only (no fuzzy v1) |
| Database | Same Postgres instance as case archive (`CASE_POSTGRES_DSN`) |

## Locked Decisions

These replace the earlier open questions for v1 implementation.

| Topic | Decision |
|-------|----------|
| Schema | **`notable_dispositions`** — separate from `notable_cases` and RAG schemas |
| Primary table | **`notable_dispositions.servicenow_closed_incidents`** (see DDL) |
| Sync cursor | **`notable_dispositions.sync_state`** row keyed by `job_name='servicenow_closed'` |
| Cursor field | **`sys_updated_on`** (not `closed_at`) so reopen/update events are captured |
| Enable gate | **`SERVICENOW_DISPOSITION_SYNC_ENABLED=false`** env flag only (no new capability profile in v1) |
| Auth token | **`SERVICENOW_DISPOSITION_SYNC_TOKEN`** required when enabled; do **not** reuse write `SERVICENOW_API_TOKEN` |
| Base URL | Reuse **`SERVICENOW_BASE_URL`** |
| Job wiring | Dedicated **`notable-disposition-sync.service`** + **`.timer`** (not retention hook) |
| Disposition enum | **`likely_malicious`**, **`likely_benign`**, **`unknown`** — same as `verdicts.py` |
| Normalization | Customer **`disposition_code_map.json`** first; fallback to **`normalize_verdict()`** on raw close code text |
| Case link | Ordered rules below; **no** search_name + time fuzzy match in v1 |
| Reopened tickets | Row kept; set **`is_active=false`** when state is no longer closed; do not delete |
| Retention | **`DISPOSITION_RETENTION_DAYS`** (default 365); **`expires_at`** column; purge in slice 2 or retention extension |
| Payload bounds | **`source_payload`** JSON max 32 KiB; **`close_notes`** max 4000 chars (match outbound SN helpers) |
| Run bounds | Max **500** records per run; page size **100**; initial backfill capped by **`SERVICENOW_DISPOSITION_BACKFILL_DAYS`** (default 90) |

### Customer-specific (still TBD at deploy time)

- Actual ServiceNow field names for close code / correlation (edit field map JSON)
- Close code values in **`disposition_code_map.json`** (start from example; tune per tenant)
- Whether `closed_state_values` in field map need customer-specific state codes

## Current Behavior

| Area | Today |
|------|--------|
| ServiceNow integration | Outbound **draft/create** only (`servicenow.py`, `ticket_draft` / `action_gated`) |
| Case archive | `notable_cases.cases` + `case_chunks`; model `verdict` column |
| Correlation keys in archive | `correlation_id`, `notable_id`, `event_id`, `sid` (`case_store.py`) |
| Verdict normalization | `verdicts.normalize_verdict()` |
| Disposition feedback | Roadmap only (`FUTURE_ENHANCEMENTS_ROADMAP.md`, Tier 4 in `NOTABLE_ANALYSIS_END_STATE.md`) |
| RAG | SOC / SPL / Elastic **document** chunks; not disposition history |

## Target Behavior

1. **Scheduled sync job** queries ServiceNow Table API for incidents updated since last cursor.
2. **Filter** to closed state using configured `closed_state_values`.
3. **Upsert** into `servicenow_closed_incidents` by `snow_sys_id`.
4. **Normalize** disposition via code map + `normalize_verdict()`.
5. **Link** `case_id` when deterministic correlation rules match one archived case.
6. **Mark inactive** rows that leave closed state (reopen).
7. **Advance cursor** only after successful commit of all pages in the run.

Portal read API and UI are **out of v1** unless trivial follow-on.

## Data Model

DDL: [`deploy/postgres/dispositions_schema.sql`](../../deploy/postgres/dispositions_schema.sql).

Key columns beyond the earlier sketch:

| Column | Purpose |
|--------|---------|
| `snow_table` | Source table name from field map |
| `is_active` | `false` when incident reopened or no longer in closed state |
| `sys_updated_on` | ServiceNow update timestamp; drives incremental cursor |
| `correlation_display` | Human-readable correlation if present |
| `expires_at` | Set from `DISPOSITION_RETENTION_DAYS` on upsert |

**Indexes:** see DDL (`closed_at`, `sys_updated_on`, `disposition_normalized`,
`correlation_id`, `case_id`, `snow_number`, `expires_at`).

**Do not** store disposition rows in `kb_chunks` unless a later phase explicitly
builds a **derived** retrieval corpus from this table.

**Do not** overwrite `notable_cases.cases.verdict` from sync — model and analyst
dispositions remain separate facts.

## Field Map Contract

File path: **`SERVICENOW_DISPOSITION_FIELD_MAP`**
(default `/etc/notable-analyzer/servicenow/disposition_field_map.json`).

Example: [`deploy/servicenow/disposition_field_map.example.json`](../../deploy/servicenow/disposition_field_map.example.json).

Required JSON shape:

```json
{
  "table": "sn_si_incident",
  "fields": {
    "sys_id": "<sn column>",
    "number": "<sn column>",
    "state": "<sn column>",
    "closed_at": "<sn column>",
    "sys_updated_on": "<sn column>",
    "close_code": "<sn column>",
    "close_notes": "<sn column>",
    "correlation_id": "<sn column>",
    "short_description": "<optional>",
    "correlation_display": "<optional>",
    "search_name": "<optional u_* rule name>"
  },
  "closed_state_values": ["3", "7", "closed", "resolved"]
}
```

Validation at job start:

- All required `fields.*` keys present and non-empty strings
- `table` matches `[a-z0-9_]+`
- `closed_state_values` is a non-empty array

Disposition code map path: **`SERVICENOW_DISPOSITION_CODE_MAP`**
(default `/etc/notable-analyzer/servicenow/disposition_code_map.json`).

Example: [`deploy/servicenow/disposition_code_map.example.json`](../../deploy/servicenow/disposition_code_map.example.json).

Shape: object with keys `likely_malicious`, `likely_benign`, `unknown`; each value
is an array of strings matched case-insensitively against raw close code text before
`normalize_verdict()` fallback.

## ServiceNow Table API Query (v1)

Base: `{SERVICENOW_BASE_URL}/api/now/table/{table}`

Incremental query (after first run):

```text
sysparm_query=sys_updated_on>{cursor_iso}^stateIN{closed_state_csv}
sysparm_fields={comma-separated mapped field columns + sys_id}
sysparm_display_value=false
sysparm_exclude_reference_link=true
sysparm_limit=100
sysparm_offset={page * 100}
sysparm_order_by=sys_updated_on
```

Initial backfill (no cursor row yet):

```text
sysparm_query=closed_at>{backfill_start_iso}^stateIN{closed_state_csv}
```

Where `backfill_start_iso = now() - SERVICENOW_DISPOSITION_BACKFILL_DAYS`.

Auth: `Authorization: Bearer {SERVICENOW_DISPOSITION_SYNC_TOKEN}`.

On **401/403**: fail run, do not advance cursor, log structured error.

On **429/5xx**: retry with bounded backoff (reuse existing HTTP retry patterns in
`servicenow.py` where applicable); fail run if exhausted.

## Disposition Normalization

For each row:

1. Read raw value from mapped `close_code` field (stringify; empty -> `unknown`).
2. If raw value matches an entry in **`disposition_code_map.json`**, use that bucket.
3. Else call **`normalize_verdict(raw)`** from `verdicts.py`.
4. Store **`disposition_raw`** = original text; **`disposition_normalized`** = enum.

## Case Linking (v1, deterministic)

Run after upsert, before cursor advance. Query `notable_cases.cases` in the same DB.

When SN `correlation_id` is non-empty, match **exactly** against (first hit wins):

| Priority | Case field | Notes |
|----------|------------|-------|
| 1 | `cases.correlation_id` | Populated at ingest from first of `correlation_id`, `notable_id`, `event_id`, `sid` in alert payload |
| 2 | `alert_payload->>'notable_id'` | JSON path fallback when column empty |
| 3 | `alert_payload->>'event_id'` | Same |
| 4 | `alert_payload->>'sid'` | Same |

Tie-break when multiple cases match: choose case with **latest `processed_at`**.

If SN `correlation_id` is empty or no case matches: leave **`case_id` NULL** (valid state).

Never link on `search_name`, `short_description`, `snow_number`, or time proximity in v1.
(ServiceNow ticket number is not stored on case rows today.)

## Sync Job Flow

```text
notable-disposition-sync.timer
  -> notable-disposition-sync.service
  -> load config + validate field map + code map
  -> if not SERVICENOW_DISPOSITION_SYNC_ENABLED: exit 0
  -> read cursor from notable_dispositions.sync_state
  -> paginate Table API (max 500 records/run)
  -> for each row: map fields, validate, normalize, hash payload
  -> upsert servicenow_closed_incidents ON CONFLICT (snow_sys_id)
  -> for rows in batch with non-closed state: set is_active=false
  -> link case_id per rules
  -> commit transaction
  -> update sync_state.cursor_value = max(sys_updated_on) seen in successful batch
  -> emit structured summary log (fetched, upserted, skipped, linked, errors)
```

**Cursor rule:** advance to the maximum **`sys_updated_on`** among successfully
processed rows only. On hard failure mid-run, cursor unchanged.

**Idempotency:** `payload_hash` = SHA-256 of canonical JSON of mapped fields; skip
no-op updates when hash unchanged (still refresh `synced_at` optional — implementer
choice: skip entirely vs touch `synced_at` only when hash changes).

## Configuration (planned env vars)

| Variable | Default | Purpose |
|----------|---------|---------|
| `SERVICENOW_DISPOSITION_SYNC_ENABLED` | `false` | Master enable |
| `SERVICENOW_BASE_URL` | (existing) | Table API host |
| `SERVICENOW_DISPOSITION_SYNC_TOKEN` | (required if enabled) | Read-only bearer token |
| `SERVICENOW_DISPOSITION_FIELD_MAP` | path to example JSON | Field mapping |
| `SERVICENOW_DISPOSITION_CODE_MAP` | path to example JSON | Close code buckets |
| `CASE_POSTGRES_DSN` | (existing) | Same DB as case archive |
| `SERVICENOW_DISPOSITION_BACKFILL_DAYS` | `90` | First-run lookback |
| `DISPOSITION_RETENTION_DAYS` | `365` | Sets `expires_at` on upsert |

Add entries to `config.env.example` in slice 4.

## Scope Contract

### In scope (first implementation block)

- Schema DDL + setup hook (extend `setup_postgres_case_archive.sh` or sibling script)
- Field map + code map loaders with schema validation
- Read-only Table API client module (`servicenow_disposition_sync.py`)
- Upsert + cursor + case linking
- Unit tests with mocked HTTP + fixture SN payloads
- systemd unit + timer
- Operator checklist in `SERVICENOW_OPERATIONS.md` (inbound sync section)

### Out of scope (v1)

- Portal UI for dispositions
- Writing dispositions back to ServiceNow from portal
- Automatic RAG chunk ingest from dispositions
- Model retraining or verdict override at analysis time
- AWS parity (follow-on after on-prem proves mapping)
- Splunk-as-source disposition pull
- Fuzzy / ML-based case matching

## Hard Stops (do not implement until resolved)

1. Customer confirms **`sn_si_incident`** (or documents alternate table + field map).
2. Read-only ServiceNow user provisioned; token stored as **`SERVICENOW_DISPOSITION_SYNC_TOKEN`**.
3. Postgres **`notable_dispositions`** schema applied on target host.
4. Sample closed incident JSON captured for fixture tests (redacted).

## Acceptance Criteria (v1)

1. With sync enabled and mocked ServiceNow, job upserts at least one closed incident
   with correct `disposition_normalized` and `snow_sys_id`.
2. Re-running the same payload does not duplicate rows; `payload_hash` prevents churn
   or documents intentional `synced_at` behavior.
3. Incremental run with cursor only fetches rows with `sys_updated_on` after cursor.
4. Reopened incident (state not in `closed_state_values`) sets `is_active=false`.
5. Case with matching `correlation_id` gets `case_id` set; non-match stays NULL.
6. Auth failure does not advance cursor.
7. Malformed SN row is skipped with counted warning; run completes if under error threshold
   (define: skip row, continue; fail run if >10% of page malformed — implementer constant).

## Test Fixtures (planned)

Under `tests/fixtures/servicenow_disposition/`:

- `closed_true_positive.json` — single Table API result row
- `closed_false_positive.json`
- `reopened_incident.json` — state transition for `is_active` test
- `field_map_minimal.json` — valid map for tests

Mock `requests` responses; use in-memory or test Postgres for upsert + link tests.

## Proposed Work Slices

1. **Schema + config contract** — apply DDL; example JSON files; env var stubs; validation helpers.
2. **Sync module** — Table API pull; pagination; upsert; cursor; normalization; unit tests.
3. **Case linking** — deterministic matcher; tests with seeded `notable_cases.cases`.
4. **Job wiring** — `notable-disposition-sync.service` + timer; `config.env.example`; operator doc section.
5. **Retention purge** — delete or archive rows where `expires_at < now()` (can ship with slice 4 or immediately after).
6. **Later:** portal read API + case detail "Analyst disposition" panel; eval harness join on `case_id`.

## Related Docs

- [`../operations/integrations/SERVICENOW_OPERATIONS.md`](../operations/integrations/SERVICENOW_OPERATIONS.md) — outbound draft/create today
- [`FUTURE_ENHANCEMENTS_ROADMAP.md`](FUTURE_ENHANCEMENTS_ROADMAP.md) — analyst feedback / eval backlog
- [`ANALYST_PORTAL_CASE_ARCHIVE_PLAN.md`](ANALYST_PORTAL_CASE_ARCHIVE_PLAN.md) — v1 explicitly excludes analyst disposition mutation
- [`../../../NOTABLE_ANALYSIS_END_STATE.md`](../../../NOTABLE_ANALYSIS_END_STATE.md) — Tier 4 feedback/evaluation target
