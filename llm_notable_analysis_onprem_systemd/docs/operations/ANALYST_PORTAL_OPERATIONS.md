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
CASE_POSTGRES_DSN=postgresql://notable_portal@127.0.0.1:5432/notable_rag
CASE_POSTGRES_SCHEMA=notable_cases
CASE_RETENTION_DAYS=30
CASE_QA_GLOBAL_RETRIEVAL_ENABLED=false
PORTAL_BIND_HOST=127.0.0.1
PORTAL_PORT=8080
PORTAL_PAGE_SIZE=50
PORTAL_CHAT_MAX_CONCURRENCY=4
PORTAL_TRUSTED_USER_HEADER=X-Forwarded-User
PORTAL_ALLOW_NON_LOOPBACK_BIND=false
PORTAL_PROXY_SECRET=<generate-a-random-shared-secret>
PORTAL_PROXY_SECRET_HEADER=X-Notable-Portal-Proxy-Secret
```

The `analyst_portal` profile enables `CASE_ARCHIVE_ENABLED`, `PORTAL_ENABLED`,
and `CASE_QA_ENABLED`. It does not enable cross-case/global chat retrieval or
`HTML_REPORT_ENABLED`, or `CASE_QA_CHAT_HISTORY_ENABLED`; enable
`CASE_QA_GLOBAL_RETRIEVAL_ENABLED=true` only after reviewing case visibility
policy, enable `CASE_QA_CHAT_HISTORY_ENABLED=true` only when bounded transcript
persistence is required, and add `html_reports` separately if static HTML
artifacts are still required.

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
- Environment file: `/etc/notable-analyzer/portal.env`
- Process: `python -m llm_notable_analysis_onprem_systemd.onprem_service.portal_app`
- Default bind: `127.0.0.1:8080`
- Restart behavior: `Restart=on-failure`
- Graceful shutdown: `TimeoutStopSec=300` allows in-flight chat/LLM requests to
  finish; the portal does not cancel active synthesis on SIGTERM.
- Logs: `journalctl -u notable-portal.service`

Example commands:

```bash
sudo cp config.portal.env.example /etc/notable-analyzer/portal.env
sudo chmod 600 /etc/notable-analyzer/portal.env
sudo vi /etc/notable-analyzer/portal.env
sudo cp deploy/systemd/notable-portal.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now notable-portal.service
sudo systemctl status notable-portal.service
sudo journalctl -u notable-portal.service -n 100 --no-pager
```

## Nginx Front Door

Use nginx as the first documented production path. FastAPI/Uvicorn should stay
on loopback by default. Non-public portal routes require
`PORTAL_TRUSTED_USER_HEADER` even on loopback, so direct local requests to case
data fail closed unless they came through the reverse proxy auth path.

The example config is `deploy/nginx/notable-portal.conf`. It documents:

- Internal DNS name via `server_name`.
- TLS certificate and key paths.
- Basic auth with `auth_basic_user_file`.
- `client_max_body_size 1m`.
- React static assets served from
  `/opt/notable-analyzer/frontend/analyst-portal/dist` with SPA fallback.
- Rate limit on `POST /api/chat` via `limit_req` (see example zone in config).
- Trusted user forwarding through `X-Forwarded-User`.
- Proxying `/api/`, `/health`, and `/ready` to `http://127.0.0.1:8080`.

Create the htpasswd file with an approved enterprise process, then install the
site:

```bash
sudo cp deploy/nginx/notable-portal.conf /etc/nginx/conf.d/notable-portal.conf
sudo nginx -t
sudo systemctl reload nginx
```

V1 trusts `PORTAL_TRUSTED_USER_HEADER` only after nginx authenticates the user
and forwards `PORTAL_PROXY_SECRET_HEADER`. Do not expose Uvicorn directly to the
analyst network. `PORTAL_PROXY_SECRET` is required even for loopback binds
because local host access is not an authentication boundary. Store the matching
nginx directive in `/etc/nginx/notable-portal-proxy-secret.conf` with root-only
write permissions, for example:

```nginx
proxy_set_header X-Notable-Portal-Proxy-Secret "<PORTAL_PROXY_SECRET>";
```

`PORTAL_BIND_HOST` values other than loopback are rejected unless
`PORTAL_ALLOW_NON_LOOPBACK_BIND=true` is configured. Use that mode only after an
explicit network review, with host firewall rules allowing the approved reverse
proxy.

## Health Checks

`GET /health` is the liveness check. `GET /ready` is the Postgres-backed
readiness check.

Threat model for unauthenticated probes:

- `/health` and `/ready` bypass the proxy-secret middleware by design so load
  balancers and systemd can probe loopback without the nginx shared secret.
- FastAPI binds to loopback by default (`PORTAL_BIND_HOST=127.0.0.1`), so these
  endpoints are not analyst-reachable unless the host firewall or bind policy is
  changed.
- `/health` returns only `{"status":"ok"}`; operator metadata such as
  `case_retention_days` is exposed on authenticated `GET /api/capabilities`.
- `/ready` checks archive tables only. It does not call the embedding model or
  LLM gateway.

Liveness:

```bash
curl -fsS http://127.0.0.1:8080/health
```

Readiness:

```bash
curl -fsS http://127.0.0.1:8080/ready
```

`/health` returns `200` when the FastAPI process is running. `/ready` runs the
bounded case list query and a cheap bounded `case_chunks` existence read using
the portal role. It returns `503` when the portal cannot serve case data.

Chat retrieval readiness is intentionally separated from load balancer probes.
Validate embedding, bounded lexical/vector retrieval, and LLM gateway reachability
with an authenticated `GET /api/diagnostics/chat-readiness`, then validate synthesis
with a sample authenticated `POST /api/chat` after deployment.

## Portal API Surface (React SPA)

The shipped analyst UI is a React SPA served by nginx. Authenticated JSON routes:

| Route | Method | Purpose |
| --- | --- | --- |
| `/api/capabilities` | GET | Portal feature flags, limits, retention window |
| `/api/cases` | GET | Paginated case list |
| `/api/cases/{case_id}` | GET | Case detail |
| `/api/chat` | POST | Case Q&A synthesis |
| `/api/chat/sessions` | GET | List saved chat sessions when history enabled |
| `/api/chat/sessions/{id}/messages` | GET | Load session transcript |
| `/api/chat/sessions/{id}` | DELETE | Delete a saved session |
| `/api/chat/sessions/{id}/turns/last` | DELETE | Remove last turn after Stop/cancel cleanup |
| `/api/diagnostics/chat-readiness` | GET | Embedding, retrieval, and LLM readiness |

Stop/cancel behavior: the UI aborts the in-flight `POST /api/chat` request and
restores the composer text. When server chat history is enabled, the client may
call `DELETE .../turns/last` to remove a partial turn that completed on the
server after the browser cancelled.

Markdown rendering uses `rehype-sanitize` with a strict schema plus link protocol
guards. Treat assistant output as untrusted even on trusted on-prem networks.

## Database Setup And Maintenance

Apply the schema before enabling the profile. Preferred path:

```bash
sudo INSTALL_ANALYST_PORTAL=true bash scripts/install.sh
```

With `INSTALL_ANALYST_PORTAL=true`, `scripts/install.sh` also installs portal OS
packages (nginx, PostgreSQL, the matching `postgresql-*-pgvector` package where
available with a source-build fallback on Debian/Ubuntu when apt has no pgvector
package, and an `htpasswd` tool package where supported),
runs `npm install` + `npm run build` for the React SPA, and copies
`frontend/analyst-portal/dist` into `/opt/notable-analyzer`.

Operator follow-up is still required for TLS certificates, basic-auth users,
nginx `server_name`, and optional legacy report backfill. Skip automated
package or frontend build when those assets are pre-staged:

```bash
sudo INSTALL_PORTAL_SKIP_OS_PACKAGES=true INSTALL_ANALYST_PORTAL=true bash scripts/install.sh
sudo INSTALL_PORTAL_SKIP_FRONTEND_BUILD=true INSTALL_ANALYST_PORTAL=true bash scripts/install.sh
```

Or run the dedicated helper after editing env files:

```bash
sudo bash scripts/setup_postgres_case_archive.sh \
  --config-env /etc/notable-analyzer/config.env \
  --portal-env /etc/notable-analyzer/portal.env
```

Manual SQL path: apply `deploy/postgres/notable_cases_schema.sql` after creating
the analyzer and portal roles/database. The portal requires:

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
needs reads for browsing and retrieval plus scoped writes/deletes on
`chat_sessions` and `chat_messages` when `CASE_QA_CHAT_HISTORY_ENABLED=true`.
Expired chat sessions are deleted by the existing retention loop using
`CASE_QA_CHAT_HISTORY_RETENTION_DAYS`.

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
python scripts/backfill_case_archive.py --report-dir /var/notables/reports --batch-size 100 --config-env /etc/notable-analyzer/config.env
```

Backfill behavior:

- IDs use `backfill:<sha256-prefix>` and are idempotent for the same report path
  and content.
- Markdown-only imports are marked `backfill_status=legacy_summary`,
  `source_completeness=markdown_only`, and `retrieval_status=not_indexed`.
- Legacy rows store the report path, content hash, source size, and a bounded
  markdown excerpt in Postgres rather than duplicating the full report body.
- Dry-run reports importable files, generated case IDs, skipped files, and
  validation failures without writing rows.
- Execute mode requires `--config-env` and `CASE_ARCHIVE_ENABLED=true`.
- Each run imports at most `--batch-size` markdown files. Oversized files,
  symlinked reports, and paths that do not remain under `--report-dir` are
  skipped and reported in the JSON output.
- Re-run is safe; the case-store upsert path updates the same backfill ID.

Operator review points:

- Confirm the report directory is correct before execute.
- Keep the dry-run JSON output for change records.
- Review `cases`, `skipped`, and `failures` after execute. A non-empty
  `failures` list returns a nonzero exit code.
- Run chunk rebuild only for native cases with structured alert/analysis data;
  markdown-only legacy summaries are intentionally not indexed for retrieval.

## Chatbot Behavior

Supported modes:

- `selected_case`
- `global_archive`

Weak retrieval returns `answer_status=unknown`. Action requests return
`answer_status=refused`. The portal chat does not call Splunk, ServiceNow, SOAR,
or remediation systems. Chat responses return the synthesized answer and
`answer_status` only; source citations are not exposed in the API or UI.

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
- Confirm nginx forwards `X-Notable-Portal-Proxy-Secret` from the protected
  include file.
- Direct local requests to non-public routes should return `401` without both
  the trusted user header and the proxy secret.
- Keep `PORTAL_BIND_HOST=127.0.0.1` unless the reverse proxy design is reviewed.
- For reviewed non-loopback binds, confirm nginx forwards
  `X-Notable-Portal-Proxy-Secret` and the host firewall only allows the proxy.

Portal startup failures:

- Check `/etc/notable-analyzer/portal.env`.
- Confirm `PORTAL_ENABLED=true` and `CASE_ARCHIVE_ENABLED=true`.
- Run `journalctl -u notable-portal.service -n 100 --no-pager`.

## Security And Admin Notes

- All authenticated analysts can see all retained cases in v1.
- Nginx terminates TLS and authentication.
- The FastAPI app should stay behind nginx on loopback by default.
- Treat case data as sensitive incident evidence.
- Do not log tokens, auth headers, or raw sensitive payloads.
- The portal and chat path are read-only by design.
