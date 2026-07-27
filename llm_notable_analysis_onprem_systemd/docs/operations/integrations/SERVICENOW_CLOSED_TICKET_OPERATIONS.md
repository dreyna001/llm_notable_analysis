# ServiceNow Closed Ticket RAG (On-Prem)

Read-only sync of closed security tickets into Postgres, hybrid chunk indexing, and
advisory retrieval for first-pass alert analysis and analyst portal chat.

## One-time setup

1. Apply Postgres schema (included in case archive setup):

   ```bash
   sudo bash scripts/setup_postgres_case_archive.sh \
     --config-env /etc/notable-analyzer/config.env \
     --portal-env /etc/notable-analyzer/portal.env
   ```

   This creates `notable_closed_tickets` tables, grants the analyzer role write access,
   and grants the portal role **read-only** `SELECT` on closed-ticket tables.

2. Configure analyzer `config.env` (see `config.env.example`):

   - `CLOSED_TICKET_RAG_ENABLED=true` for retrieval/indexing
   - `SERVICENOW_CLOSED_TICKET_SYNC_ENABLED=true` plus token, table, and encoded query
   - `CLOSED_TICKET_RETENTION_DAYS` — **30, 60, or 90** (default **30**)
   - `CASE_POSTGRES_DSN` — same database as case archive

3. Configure portal `portal.env` for chat lane:

   - `CLOSED_TICKET_RAG_ENABLED=true`
   - `CASE_QA_CLOSED_TICKET_ENABLED=true`
   - Same `CLOSED_TICKET_POSTGRES_SCHEMA` / chunks table as analyzer

4. Install operator scripts (or full `scripts/install.sh`):

   - `/opt/notable-analyzer/scripts/run_closed_ticket_sync.py`
   - `/opt/notable-analyzer/scripts/rebuild_closed_ticket_chunks.py`

5. Enable timer (not auto-enabled by install):

   ```bash
   sudo systemctl enable --now notable-closed-ticket-sync.timer
   ```

## Daily operation

- **Raw sync:** `notable-closed-ticket-sync.service` (timer ~04:30) pulls tickets,
  journals, and optional attachments into `notable_closed_tickets.servicenow_tickets`.
- **Auto-index:** When `CLOSED_TICKET_RAG_ENABLED=true`, the sync script indexes a
  bounded batch of tickets with `index_status` in `pending` or `failed` (active,
  unexpired only). Index failures are logged and recorded on the sync summary without
  rolling back a successful raw sync.

Manual sync:

```bash
/opt/notable-analyzer/venv/bin/python /opt/notable-analyzer/scripts/run_closed_ticket_sync.py
```

## Status verification

```sql
SELECT index_status, count(*)
FROM notable_closed_tickets.servicenow_tickets
WHERE is_active = true AND expires_at > now()
GROUP BY 1
ORDER BY 1;

SELECT count(*) FROM notable_closed_tickets.ticket_chunks;
```

Analyzer metadata on first-pass reports `closed_ticket_rag_*` fields. Portal chat
logs retrieval errors when Postgres or embedding fails (lane stays fail-soft).

## Full chunk rebuild

After schema/model changes or backfill:

```bash
/opt/notable-analyzer/venv/bin/python \
  /opt/notable-analyzer/scripts/rebuild_closed_ticket_chunks.py \
  --config-env /etc/notable-analyzer/config.env \
  --all --batch-size 100
```

Single ticket:

```bash
/opt/notable-analyzer/venv/bin/python \
  /opt/notable-analyzer/scripts/rebuild_closed_ticket_chunks.py \
  --config-env /etc/notable-analyzer/config.env \
  --ticket-id <sys_id>
```

Dry-run (no writes):

```bash
/opt/notable-analyzer/venv/bin/python \
  /opt/notable-analyzer/scripts/rebuild_closed_ticket_chunks.py \
  --dry-run --all --batch-size 20
```

## Retention

`CLOSED_TICKET_RETENTION_DAYS` sets `expires_at` on upsert. Retrieval and incremental
indexing ignore inactive or expired tickets. Raw rows remain until separately purged.
