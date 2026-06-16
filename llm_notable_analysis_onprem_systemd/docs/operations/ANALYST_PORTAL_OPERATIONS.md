# Analyst Portal Operations

This guide covers the on-prem read-only analyst portal, Postgres case archive,
archive-backed Case Q&A, chunk maintenance, legacy markdown backfill, and nginx
fronting pattern.

**Network URL rollout (DNS, TLS, firewall, analyst browser access):**
[`ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](ANALYST_PORTAL_NETWORK_DEPLOYMENT.md).

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
PORTAL_BIND_HOST=127.0.0.1
PORTAL_PORT=8080
PORTAL_PAGE_SIZE=50
PORTAL_CHAT_MAX_CONCURRENCY=18
PORTAL_TRUSTED_USER_HEADER=X-Forwarded-User
PORTAL_ALLOW_NON_LOOPBACK_BIND=false
PORTAL_PROXY_SECRET=<generate-a-random-shared-secret>
PORTAL_PROXY_SECRET_HEADER=X-Notable-Portal-Proxy-Secret
```

The `analyst_portal` profile enables `CASE_ARCHIVE_ENABLED`, `PORTAL_ENABLED`,
and `CASE_QA_ENABLED`. Portal chat requires a pinned case (`selected_case_id`).
It does not enable `HTML_REPORT_ENABLED` or `CASE_QA_CHAT_HISTORY_ENABLED`;
enable `CASE_QA_CHAT_HISTORY_ENABLED=true` only when bounded transcript
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

Port contract:

- Analysts access nginx on `https://<portal-host>/` over TCP `443`.
- nginx proxies API and probe traffic to FastAPI on `127.0.0.1:8080`.
- `PORTAL_PORT=8080` is the internal loopback application port, not the analyst
  network port.
- SSH tunnel mappings such as local `8443 -> remote 443` are operator
  conveniences for lab access only; they do not change the production listener.

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

Basic auth credentials are not stored in the application database and are not
created by the production installer. Create or rotate the nginx htpasswd entry
through your approved secret process:

```bash
sudo htpasswd -c /etc/nginx/htpasswd/notable-portal <analyst-user>
sudo nginx -t
sudo systemctl reload nginx
```

For one-off lab VMs, `scripts/vm_portal_finish.sh` defaults to:

- Username: `analyst`
- Password: `analyst-lab-change-me`

That default is for tunnel-only lab bring-up. Rotate it before sharing the host
or exposing nginx outside the operator workstation.

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
  `case_retention_days`, `chat_ready`, and optional `chat_degraded_reason` are exposed on authenticated `GET /api/capabilities`.
  When `chat_ready` is false, `chat_dependency_status` reports each dependency (`embeddings`, `archive_retrieval`, `llm_gateway`) as `ready` or `unavailable`, and `chat_degraded_reason` summarizes all unavailable dependencies.
  Operators can also call `GET /api/diagnostics/chat-readiness` for the same reason in the `503` JSON body.
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
| `/api/capabilities` | GET | Portal feature flags, limits, retention window, and live `chat_ready` status |
| `/api/cases` | GET | Paginated case list |
| `/api/cases/{case_id}` | GET | Bounded case detail view |
| `/api/cases/{case_id}/raw/{section}` | GET | Paginated raw `alert_payload` or `analysis` JSON |

`GET /api/cases/{case_id}` returns a stable, size-bounded view of archived case
content. Large strings, deep nesting, and non-UI analysis keys such as
`raw_response` are omitted or truncated. The response includes `content_bounds`
with truncation flags, total key counts, and `raw_sections` that can be fetched
from the raw endpoint.

`GET /api/cases/{case_id}/raw/{section}` query parameters:

- `section` — path segment: `alert_payload` or `analysis`
- `offset`, `limit` — paginate top-level keys (default limit 50, max 100)
- `key` — optional single-key lookup (for example `raw_response`)

`GET /api/cases` optional query parameters:

- `limit` — pagination page size
- `cursor_processed_at`, `cursor_case_id` — cursor pagination (both required together)
- `start_date`, `end_date` — inclusive UTC calendar days (`YYYY-MM-DD`) applied to `processed_at`
- `start`, `end` — legacy inclusive ISO-8601 UTC instants (prefer `start_date` / `end_date`)
- `verdict`, `search_name` — summary filters

The analyst UI sends `start_date` / `end_date` only. Date filters use UTC calendar days end-to-end so list results match stored `processed_at` timestamps without browser timezone conversion.
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
packages (nginx, PostgreSQL, the matching pgvector package where available with
a source-build fallback on supported Debian-like and RHEL-like hosts, and an
`htpasswd` tool package where supported), runs `npm install` + `npm run build`
for the React SPA, and copies `frontend/analyst-portal/dist` into
`/opt/notable-analyzer`.

The installer generates a shared `PORTAL_PROXY_SECRET`, synchronizes it into
both `/etc/notable-analyzer/config.env` and
`/etc/notable-analyzer/portal.env`, and writes the nginx include file that
forwards the matching proxy-secret header. When the case archive DSNs use TCP
localhost and omit passwords, the installer generates Postgres role passwords in
the root-readable env files before running the schema helper; the helper then
applies those passwords to the database roles.

Operator follow-up is still required for TLS certificates, basic-auth users,
nginx `server_name`, and optional legacy report backfill. Skip automated
package or frontend build when those assets are pre-staged:

```bash
sudo INSTALL_PORTAL_SKIP_OS_PACKAGES=true INSTALL_ANALYST_PORTAL=true bash scripts/install.sh
sudo INSTALL_PORTAL_SKIP_FRONTEND_BUILD=true INSTALL_ANALYST_PORTAL=true bash scripts/install.sh
```

`INSTALL_ANALYST_PORTAL=true` treats Postgres schema setup as required. Use
`INSTALL_PORTAL_ALLOW_PARTIAL=true` only when intentionally staging files before
database access is available.

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

- `CASE_QA_VECTOR_DIMENSIONS` is fixed at `1024` for v1.
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

Portal chat requires a pinned case. Supported mode:

- `selected_case` (requires `selected_case_id`)

General technology / TTP questions still work via `CASE_QA_GENERAL_KNOWLEDGE_ENABLED`
and optional advisory knowledge-base context when enabled. Cross-case archive
search is not supported.

Weak retrieval returns `answer_status=unknown`. The portal chat has no live
Splunk, ServiceNow, SOAR, or remediation integrations and cannot execute
searches or tickets. Analysts may ask for draft Splunk SPL, Elasticsearch
queries, CrowdStrike hunts, and similar guidance; the assistant should answer
with investigation steps and unvalidated draft query text, not pre-refuse the
question. Answers that claim the portal already performed an external action
still return `answer_status=refused`. Chat responses return the synthesized
answer and `answer_status` only; source citations are not exposed in the API or
UI.

For architecture, threat model, and non-execution guarantees, see
[`ANALYST_PORTAL_CHAT_SECURITY.md`](ANALYST_PORTAL_CHAT_SECURITY.md).

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
- Direct local requests to non-public routes should return `401` with a generic
  `Authentication required.` message without both the trusted user header and
  the proxy secret. Check `notable-portal.service` logs for the missing header
  name and path.
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
- Portal chat cannot execute integrations or filesystem operations; see
  [`ANALYST_PORTAL_CHAT_SECURITY.md`](ANALYST_PORTAL_CHAT_SECURITY.md).
