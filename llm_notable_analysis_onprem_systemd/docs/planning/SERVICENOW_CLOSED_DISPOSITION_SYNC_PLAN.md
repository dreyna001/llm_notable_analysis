# ServiceNow Closed Disposition Sync Plan

## Status

Planning on branch `feature/servicenow-closed-disposition-sync`. Not implemented.

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
| Table | Customer uses **`sn_si_incident`** (Security Incident) or equivalent; field map is configurable |
| Scope of sync | **Closed / resolved** records only (not open/active queue) |
| Direction | Inbound sync only in v1 |
| Credentials | Read-only ServiceNow API user (separate from draft/create write token if needed) |
| Identity | Stable external key = ServiceNow `sys_id` (plus `number` for display) |
| Link to archive | Best-effort match on correlation fields (notable ID, correlation ID, search name + time window) |

## Current Behavior

| Area | Today |
|------|--------|
| ServiceNow integration | Outbound **draft/create** only (`servicenow.py`, `ticket_draft` / `action_gated`) |
| Case archive | `notable_cases.cases` + `case_chunks`; model `verdict` column |
| Disposition feedback | Roadmap only (`FUTURE_ENHANCEMENTS_ROADMAP.md`, Tier 4 in `NOTABLE_ANALYSIS_END_STATE.md`) |
| RAG | SOC / SPL / Elastic **document** chunks; not disposition history |

## Target Behavior

1. **Scheduled sync job** (systemd timer or analyzer-side loop) queries ServiceNow for incidents closed since last cursor.
2. **Upsert** into a dedicated Postgres table by `snow_sys_id`.
3. **Normalize** disposition to a small internal enum aligned with portal verdict tones where possible (`likely_malicious`, `likely_benign`, `unknown`, plus raw ServiceNow close code).
4. **Optional link** `case_id` when a archived case matches correlation rules.
5. **Expose read APIs** later (portal list/filter, case detail panel) — out of v1 sync slice unless trivial.

## Proposed Data Model

New schema/table (names tentative):

**Schema:** `notable_dispositions` (or table under `notable_cases` with clear separation from analyzer ingest — prefer **separate schema** to avoid retention coupling).

**Table:** `servicenow_closed_incidents` (example)

| Column | Purpose |
|--------|---------|
| `snow_sys_id` | Primary key; ServiceNow incident sys_id |
| `snow_number` | INC/SIR display number |
| `state` | Raw ServiceNow state |
| `closed_at` | When incident was closed (ServiceNow field) |
| `disposition_normalized` | Internal enum after mapping |
| `disposition_raw` | Original close code / category field |
| `close_notes` | Truncated resolution / close notes |
| `search_name` / `short_description` | Alert/rule label if present |
| `correlation_id` | Splunk notable / event correlation if present |
| `source_payload` | Bounded JSON snapshot of mapped SN fields |
| `case_id` | Nullable FK to `notable_cases.cases` |
| `synced_at` | Last successful upsert |
| `payload_hash` | Change detection for idempotent updates |

**Indexes:** `closed_at`, `disposition_normalized`, `correlation_id`, `case_id`,
`snow_number`.

**Retention:** separate from `CASE_RETENTION_DAYS` (dispositions may need longer
retention for eval); operator-configured.

Do **not** store disposition rows in `kb_chunks` unless a later phase explicitly
builds a **derived** retrieval corpus from this table.

## Sync Design (v1)

```text
Timer / job
  -> read SERVICENOW_* sync config + last cursor (closed_at / sys_updated_on)
  -> GET closed incidents (Table API, paginated, bounded page size)
  -> map fields via customer field map (config or JSON file)
  -> normalize disposition
  -> upsert servicenow_closed_incidents
  -> optional: match case_id from notable_cases
  -> persist sync cursor + structured job summary log
```

**Config knobs (planned):**

- `SERVICENOW_DISPOSITION_SYNC_ENABLED=false`
- `SERVICENOW_DISPOSITION_TABLE=sn_si_incident` (or customer table)
- `SERVICENOW_DISPOSITION_QUERY_WINDOW` / initial backfill limit
- `SERVICENOW_DISPOSITION_FIELD_MAP` path or env keys for close code, correlation, search name
- Reuse `SERVICENOW_BASE_URL`; separate read-only token recommended

**Failure modes:** fail closed on auth errors; skip malformed rows with count;
do not partial-update cursor on hard failure.

## Scope Contract

### In scope (first implementation block)

- Planning + schema DDL + field-map contract
- Read-only ServiceNow Table API client for closed incidents
- Upsert into new table + sync cursor storage
- Unit tests with mocked HTTP responses
- Operator doc stub (field mapping checklist)

### Out of scope (v1)

- Portal UI for dispositions
- Writing dispositions back to ServiceNow from portal
- Automatic RAG chunk ingest from dispositions
- Model retraining or verdict override at analysis time
- AWS parity (follow-on after on-prem proves mapping)
- Splunk-as-source disposition pull (ServiceNow is the assumed source)

## Open Questions

- Exact ServiceNow table and fields per customer (Security Incident vs Incident, custom `u_*` disposition fields)?
- Canonical mapping from ServiceNow close codes to `likely_malicious` / `likely_benign` / `unknown`?
- Where sync cursor lives (Postgres row vs file vs `archive_metadata`)?
- Match rules for `case_id` (strict notable ID only vs fuzzy search_name + time)?
- Retention policy for disposition history vs case archive?
- Separate capability profile (e.g. `disposition_sync`) vs flag on existing integration config?

## Proposed Work Slices

1. **Field map + schema DDL** — customer interview template; `deploy/postgres/dispositions_schema.sql`.
2. **Sync module** — `servicenow_disposition_sync.py`; paginated pull; upsert; cursor.
3. **Case linking** — deterministic matcher; nullable `case_id`; tests.
4. **Job wiring** — systemd timer or script; config.env.example entries.
5. **Docs** — extend `SERVICENOW_OPERATIONS.md` with inbound sync section.
6. **Later:** portal read API + case detail "Analyst disposition" panel; optional eval harness join.

## Related Docs

- [`../operations/integrations/SERVICENOW_OPERATIONS.md`](../operations/integrations/SERVICENOW_OPERATIONS.md) — outbound draft/create today
- [`FUTURE_ENHANCEMENTS_ROADMAP.md`](FUTURE_ENHANCEMENTS_ROADMAP.md) — analyst feedback / eval backlog
- [`ANALYST_PORTAL_CASE_ARCHIVE_PLAN.md`](ANALYST_PORTAL_CASE_ARCHIVE_PLAN.md) — v1 explicitly excludes analyst disposition mutation
- [`../../../NOTABLE_ANALYSIS_END_STATE.md`](../../../NOTABLE_ANALYSIS_END_STATE.md) — Tier 4 feedback/evaluation target
