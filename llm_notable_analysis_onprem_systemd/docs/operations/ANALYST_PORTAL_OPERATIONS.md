# Analyst Portal Operations

This guide covers the on-prem read-only analyst portal, Postgres case archive,
archive-backed Case Q&A, chunk maintenance, legacy markdown backfill, and nginx
fronting pattern.

## What This Controls

The `analyst_portal` capability persists validated cases to Postgres, serves a
read-only FastAPI portal, and enables retrieval-bound Case Q&A over retained
case evidence and configured SOC context stores.

No portal endpoint mutates cases, runs SPL or Elasticsearch searches, creates
ServiceNow tickets, calls SOAR, or triggers remediation. `POST /api/chat` is a
query transport only.

## Enable And Disable

Recommended enablement:

```bash
CAPABILITY_PROFILES=core,analyst_portal
CASE_POSTGRES_DSN=postgresql://notable_analyzer@127.0.0.1:5432/notable_rag
CASE_POSTGRES_SCHEMA=notable_cases
CASE_RETENTION_DAYS=90
PORTAL_BIND_HOST=127.0.0.1
PORTAL_PORT=8080
PORTAL_PAGE_SIZE=50
PORTAL_TRUSTED_USER_HEADER=X-Forwarded-User
```

The `analyst_portal` profile enables `CASE_ARCHIVE_ENABLED`, `PORTAL_ENABLED`,
`CASE_QA_ENABLED`, and `CASE_QA_GLOBAL_RETRIEVAL_ENABLED`. It does not enable
`HTML_REPORT_ENABLED`; add `html_reports` separately if static HTML artifacts
are still required.

Rollback options:

- Remove `analyst_portal` from `CAPABILITY_PROFILES` and restart the analyzer
  and portal service.
- For emergency archive disablement, set `CASE_ARCHIVE_ENABLED=false` and stop
  `notable-portal.service`.
- Existing Postgres rows are not deleted by disabling the profile. Retention
  continues only when archive cleanup is enabled and the retention job runs.

## Systemd Service

The portal service unit is `deploy/systemd/notable-portal.service`.

Expected host shape:

- Service user: `notable-analyzer`
- Environment file: `/etc/notable-analyzer/config.env`
- Process: `python -m llm_notable_analysis_onprem_systemd.onprem_service.portal_app`
- Default bind: `127.0.0.1:8080`
- Restart behavior: `Restart=on-failure`
- Logs: `journalctl -u notable-portal.service`

Example commands:

```bash
sudo cp deploy/systemd/notable-portal.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now notable-portal.service
sudo systemctl status notable-portal.service
sudo journalctl -u notable-portal.service -n 100 --no-pager
```

## Nginx Front Door

Use nginx as the first documented production path. FastAPI/Uvicorn should stay
on loopback by default.

The example config is `deploy/nginx/notable-portal.conf`. It documents:

- Internal DNS name via `server_name`.
- TLS certificate and key paths.
- Basic auth with `auth_basic_user_file`.
- `client_max_body_size 1m`.
- Trusted user forwarding through `X-Forwarded-User`.
- Proxying to `http://127.0.0.1:8080`.

Create the htpasswd file with an approved enterprise process, then install the
site:

```bash
sudo cp deploy/nginx/notable-portal.conf /etc/nginx/conf.d/notable-portal.conf
sudo nginx -t
sudo systemctl reload nginx
```

V1 trusts `PORTAL_TRUSTED_USER_HEADER` only when nginx is the front door. Do not
expose Uvicorn directly to the analyst network.

## Health Checks

`GET /health` is the liveness check. `GET /ready` is the Postgres-backed
readiness check.

Liveness:

```bash
curl -fsS http://127.0.0.1:8080/health
```

Readiness:

```bash
curl -fsS http://127.0.0.1:8080/ready
```

`/health` returns `200` when the FastAPI process is running. `/ready` checks
Postgres connectivity and required case tables; it returns `503` when the portal
cannot serve case data.

## Database Setup And Maintenance

Apply the schema in `deploy/postgres/notable_cases_schema.sql` before enabling
the profile. The portal requires:

- `notable_cases.cases`
- `notable_cases.case_chunks`
- `pgvector`
- indexes for `processed_at`, `expires_at`, full-text search, and vector search

Recommended checks:

```sql
SELECT to_regclass('notable_cases.cases');
SELECT to_regclass('notable_cases.case_chunks');
SELECT COUNT(*) FROM notable_cases.cases;
SELECT retrieval_status, COUNT(*) FROM notable_cases.cases GROUP BY 1;
```

Use separate least-privilege roles for the analyzer and portal where possible.
The analyzer role needs writes to `cases` and `case_chunks`; the portal role only
needs reads for browsing and retrieval.

Backups must include the `notable_cases` schema. Restore tests should include
case list, case detail, readiness, and a sample chat request.

Expired cases are removed by retention cleanup using `expires_at`. Deleting a
case row cascades derived `case_chunks` rows through the database foreign key.

## Chunk Maintenance

Rebuild chunks after changing chunking logic, embedding model, vector dimension,
or after repairing failed `retrieval_status` rows.

Dry-run one case:

```bash
python scripts/rebuild_case_chunks.py --case-id case-123 --dry-run --config-env /etc/notable-analyzer/config.env
```

Rebuild all retained cases in batches:

```bash
python scripts/rebuild_case_chunks.py --all --batch-size 100 --config-env /etc/notable-analyzer/config.env
```

Warnings:

- `CASE_QA_VECTOR_DIMENSIONS` is fixed at `768` for v1.
- Embedding model changes require a chunk rebuild.
- Stale or missing chunks show up as weak retrieval, `unknown` chat answers, or
  cases with `retrieval_status` not equal to `ready`.

## Legacy Backfill

Use `scripts/backfill_case_archive.py` once when importing existing markdown
reports into the case archive.

Dry-run:

```bash
python scripts/backfill_case_archive.py --dry-run --report-dir /var/notables/reports --config-env /etc/notable-analyzer/config.env
```

Execute:

```bash
python scripts/backfill_case_archive.py --report-dir /var/notables/reports --config-env /etc/notable-analyzer/config.env
```

Backfill behavior:

- IDs use `backfill:<sha256-prefix>` and are idempotent for the same report path
  and content.
- Markdown-only imports are marked `backfill_status=legacy_summary`,
  `source_completeness=markdown_only`, and `retrieval_status=not_indexed`.
- Dry-run reports importable files and generated case IDs without writing rows.
- Re-run is safe; the case-store upsert path updates the same backfill ID.

Operator review points:

- Confirm the report directory is correct before execute.
- Keep the dry-run JSON output for change records.
- Review row counts after execute.
- Run chunk rebuild only for native cases with structured alert/analysis data;
  markdown-only legacy summaries are intentionally not indexed for retrieval.

## Chatbot Behavior

Supported modes:

- `selected_case`
- `global_archive`
- `selected_case_plus_archive`
- `soc_context_only`

Every answered response includes machine-readable citations. Case citations use
contextual lanes `current_case` or `prior_case` and preserve stored chunk lanes
such as `case_analysis` or `alert_payload`. SOC guidance uses `soc_context`.

Weak retrieval returns `answer_status=unknown`. Action requests return
`answer_status=refused`. The portal chat does not call Splunk, ServiceNow, SOAR,
or remediation systems.

## Troubleshooting

Postgres unavailable:

- `/ready` returns `503`.
- Check `CASE_POSTGRES_DSN`, firewall, local Postgres status, and journal logs.

Migration mismatch:

- Verify `cases`, `case_chunks`, `search_vector`, GIN, and HNSW objects exist.
- Reapply the schema migration in a maintenance window.

Embedding failures:

- Confirm `CASE_QA_EMBEDDING_MODEL` is staged locally.
- Check `SENTENCE_TRANSFORMERS_HOME` and cache permissions.

Chunk rebuild failures:

- Run `rebuild_case_chunks.py --case-id <id> --dry-run`.
- Check vector dimension and Postgres statement timeout.

Auth or trusted-header issues:

- Confirm nginx basic auth succeeds.
- Confirm nginx forwards `X-Forwarded-User`.
- Keep `PORTAL_BIND_HOST=127.0.0.1` unless the reverse proxy design is reviewed.

Portal startup failures:

- Check `/etc/notable-analyzer/config.env`.
- Confirm `PORTAL_ENABLED=true` and `CASE_ARCHIVE_ENABLED=true`.
- Run `journalctl -u notable-portal.service -n 100 --no-pager`.

## Security And Admin Notes

- All authenticated analysts can see all retained cases in v1.
- Nginx terminates TLS and authentication.
- The FastAPI app should stay behind nginx on loopback.
- Treat case data as sensitive incident evidence.
- Do not log tokens, auth headers, or raw sensitive payloads.
- The portal and chat path are read-only by design.
