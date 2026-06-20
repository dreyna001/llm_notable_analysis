# Analyst Portal And Case Archive Plan

## Status

Living planning document. Use
[`../technical_specs/analyst_portal_case_archive_technical_spec.md`](../technical_specs/analyst_portal_case_archive_technical_spec.md)
as the implementation contract for shipped behavior. This plan captures design
rationale, deferred work, and open product decisions.

Operator runbooks:

- [`../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md)
- [`../operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](../operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md)
- [`ANALYST_PORTAL_NETWORKING_PLAN.md`](ANALYST_PORTAL_NETWORKING_PLAN.md)

### Shipped on-prem (verified)

| Area | Shipped behavior |
|------|------------------|
| Capability profile | `analyst_portal` sets `CASE_ARCHIVE_ENABLED`, `PORTAL_ENABLED`, `CASE_QA_ENABLED` (`config.py`) |
| Archive writes | `case_store.py` upserts `notable_cases.cases`; bounded retries; identity-collision guard |
| Archive orchestration | `case_archive_flow.py` writes case row, indexes chunks, marks `retrieval_status=failed` on chunk failure |
| Ingest coupling | Archive failure is logged and non-blocking; analysis still moves to processed (`onprem_main.py`) |
| Retention | `CASE_RETENTION_DAYS=30` default; expired case + chunk delete via retention loop (`retention.py`) |
| Schema | `deploy/postgres/notable_cases_schema.sql` — `cases`, `case_chunks`, optional chat tables, pgvector HNSW, lexical `search_vector` |
| Chunk rebuild | `scripts/rebuild_case_chunks.py` |
| Legacy backfill | `scripts/backfill_case_archive.py` (markdown-only imports as `legacy_summary`) |
| Portal API | `portal_app.py` — list/detail/raw sections, chat, capabilities, readiness probes, bounded chat-history CRUD when enabled |
| Chat mode | `selected_case` only; requires `selected_case_id` (`case_chat.py`, React types) |
| Chat response | API returns `answer`, `answer_status`, optional `session_id` only — no citations in API/UI |
| Chat history | Off by default (`CASE_QA_CHAT_HISTORY_ENABLED=false`); bounded sessions/messages when enabled |
| Frontend | React SPA `frontend/analyst-portal/`; server-rendered pages in `portal_app.py` retired |
| Deploy artifacts | `deploy/systemd/notable-portal.service`, `deploy/nginx/notable-portal.conf`, `install.sh` portal path |

### Remaining / deferred

- `global_archive` chat mode (cross-case retrieval without a pinned case).
- Prior-case retrieval as a tertiary chat lane in production chat paths.
- Cooperative backend chat cancellation (client-side Stop only today).
- AWS portal/archive implementation.
- Threat-intel, CMDB, SOAR, golden-eval harness (see Deferred Roadmap Items).
- Per-case RBAC.
- Portal-triggered actions (rerun, writeback, tickets, suppressions).

## Current Goal

Build the on-prem version first: a read-only analyst portal backed by a tunable
case archive, defaulting to 30 days. The portal includes a chatbot that helps
an analyst iterate on alerts using retained case evidence plus approved SOC
context.

The AWS version should come later, after the on-prem storage, retrieval, prompt,
and security boundaries are proven.

## Deferred Roadmap Items

Keep these out of the current implementation block:

- Threat-intel adapters.
- CMDB / asset / ownership enrichment.
- SOAR playbook invocation.
- Golden evaluation harness implementation.
- AWS portal implementation.

The portal design should leave room for these later, but it should not build
generic adapter frameworks or action surfaces now.

## Scope Contract

### In Scope

- On-prem case archive with configurable retention, default `30` days.
- Read-only analyst portal with case browse/search and selected-case chat over
  retained cases.
- Full-fidelity storage of the original notable / alert payload.
- One canonical stored analysis output per case in Postgres as structured JSONB.
- Retrieval over:
  - the selected alert payload,
  - the stored validated analysis output,
  - approved SOC context already used by RAG / SPL grounding,
  - other retained case records as a tertiary source (deferred for chat).
- Chat history can be disabled. If enabled, it must have retention limits,
  size limits, and redaction rules.

### Out Of Scope

- Storing HTML as a long-term archive artifact.
- Portal-triggered Splunk searches, ServiceNow actions, SOAR playbooks,
  remediations, suppressions, or ticket/writeback operations.
- Analyst edits, dispositions, notes, or case-state mutation in v1.
- Open-ended model memory or a separate chatbot memory store.
- Using raw model output as authoritative case state unless validation failed;
  if stored for troubleshooting, it must be explicitly flagged.

## Storage Decision (shipped)

Do **not** store pre-rendered HTML in the archive.

Postgres `notable_cases.cases` is the canonical store:

- Full-fidelity original notable / alert payload (`alert_payload` JSONB).
- Validated structured analysis (`analysis` JSONB), or NULL when POC fallback.
- Metadata for list/filter/search: `case_id`, `finding_id`, `processed_at`,
  `expires_at`, `verdict`, `confidence`, `search_name`, `risk_score`,
  `correlation_id`, `capability_snapshot`, `archive_metadata`.
- Operational fields: `retrieval_status`, `backfill_status`,
  `source_completeness`.
- Optional compatibility pointers: `report_md_path`, `report_html_path`.

Portal detail views render from the Postgres case record. Markdown and HTML
continue when analyzer settings enable them; the portal and chatbot do not depend
on filesystem artifacts.

### Why JSON Is The Canonical Case Format

JSON preserves alert fields, validated analysis sections, metadata, and source
references in a machine-readable shape. Markdown and HTML are display formats;
Postgres JSONB powers filters, citations (internal), and retrieval.

## Existing Infrastructure To Reuse

Current on-prem storage/retrieval pieces:

- `REPORT_DIR` stores markdown reports; optional HTML when `html_reports` profile
  or `HTML_REPORT_ENABLED` is on.
- General RAG uses `RAG_BACKEND=postgres` by default (`RAG_POSTGRES_*`).
- `sqlite_faiss` RAG backend exists as a fallback; portal/archive does not use
  it.
- SPL and Elasticsearch grounding use dedicated Postgres tables in the RAG
  schema.
- Side-effect idempotency uses filesystem JSON markers.
- **Case archive:** Postgres `notable_cases` schema (`CASE_POSTGRES_DSN`,
  `CASE_POSTGRES_SCHEMA=notable_cases`).

### Deconfliction Principle

Keep the canonical case archive separate from RAG/SPL grounding corpora. The
archive owns durable case records and retention; pgvector chunks are derived and
rebuildable from `cases` rows.

| Data | Canonical store | Retrieval/index store |
|------|-----------------|-----------------------|
| Original alert + validated analysis | `notable_cases.cases` JSONB | `notable_cases.case_chunks` (pgvector + lexical) |
| SOP/runbooks | Existing RAG source docs | Existing general RAG table/index |
| SPL docs | Existing SPL query source docs | Existing SPL grounding table/index |
| Chat history | Optional `chat_sessions` / `chat_messages` | Not used as retrieval memory |

Chunk `source_lane` values in storage: `alert_payload`, `case_analysis`,
`legacy_summary`. Chat assembly uses `current_case` and `knowledge_base` lanes.

## Chatbot Boundary

The portal chatbot is read-only and retrieval-bound.

It may:

- Answer questions about a selected case (shipped).
- Use approved SOC / Knowledge Base context (`CASE_QA_GENERAL_KNOWLEDGE_ENABLED`
  defaults true).
- Answer global archive questions (deferred — `global_archive` mode not enabled).

It must not:

- Execute SPL or Elasticsearch queries.
- Call Splunk, ServiceNow, SOAR, threat-intel, CMDB, or cloud APIs.
- Re-run analysis.
- Update case state, write notes, create tickets, suppress alerts, or trigger
  playbooks.
- Answer from broad model memory when retrieval is weak.

Internal prompt lanes: `current_case`, `knowledge_base`; `prior_case` reserved
for future cross-case retrieval. Answers should separate current alert facts,
Knowledge Base guidance, model inference, and unknowns.

## Retention And Limits

Default archive retention: `CASE_RETENTION_DAYS=30`.

Shipped limits (config defaults in `config.py`):

| Setting | Default |
|---------|---------|
| `CASE_QA_MAX_CHUNKS_PER_LANE` | `6` |
| `CASE_QA_MAX_TOTAL_CHUNKS` | `18` |
| `CASE_QA_CONTEXT_BUDGET_CHARS` | `12000` |
| `CASE_QA_MAX_QUESTION_CHARS` | `2000` |
| `CASE_QA_MAX_ANSWER_TOKENS` | `800` |
| `CASE_QA_CHAT_HISTORY_ENABLED` | `false` |
| `CASE_QA_CHAT_HISTORY_RETENTION_DAYS` | `7` when enabled |
| `CASE_QA_MAX_MESSAGES_PER_SESSION` | `30` |
| `CASE_QA_MAX_SESSIONS_PER_USER` | `10` |
| `CASE_QA_MAX_STORED_MESSAGE_BYTES` | `4000` |

Expired cases cascade-delete chunks. Expired chat sessions delete via the
retention loop when chat history is enabled.

## Portal Shape

Read-only interactive portal; analyzer remains the only case writer.

Shipped user flows:

- List cases (newest first, cursor pagination, date/verdict/search_name filters).
- Open case detail (structured JSON; paginated raw sections).
- Selected-case chat from case detail / dashboard.
- Optional bounded chat-history persistence.

The portal must not have write access to `INCOMING_DIR`, action secrets,
Splunk writeback, ServiceNow create, or SOAR credentials.

### Operational Control

Without the `analyst_portal` profile, archive/portal/chat default off. Profile
on enables archive, portal, and case Q&A together. Additional gates:

- `CASE_QA_CHAT_HISTORY_ENABLED` — transcript persistence.
- `PORTAL_PROXY_SECRET` required when `PORTAL_ENABLED=true` (nginx shared secret).
- `PORTAL_BIND_HOST=127.0.0.1` by default; nginx is the documented front door.

See [`../operations/platform/CAPABILITY_PROFILES.md`](../operations/platform/CAPABILITY_PROFILES.md).

### Future Action Boundary

V1 is read-only. Future rerun, writeback, ticket, SOAR, or suppression flows
require separate capability flags, policy gates, approval metadata, audit trail,
tests, and least-privilege credentials.

## Access And Authentication

V1: all authenticated analysts see all retained notables; no per-case RBAC.

Shipped boundary:

- FastAPI binds loopback by default.
- nginx terminates TLS, serves React SPA, proxies `/api/*`, `/health`, `/ready`.
- nginx basic auth is the first documented path; customer SSO can replace auth at
  the proxy.
- `PORTAL_TRUSTED_USER_HEADER` (default `X-Forwarded-User`) for audit identity;
  portal fails closed when required headers or proxy secret are missing.

## Case Schema (shipped DDL summary)

Authoritative DDL: `deploy/postgres/notable_cases_schema.sql`.

### `cases`

| Column | Purpose |
|--------|---------|
| `case_id` | Primary key; native id from alert identity or filename stem |
| `finding_id` | Splunk/customer finding id when available |
| `source_filename` | Original dropped filename |
| `processed_at`, `expires_at` | Analysis time and retention cutoff |
| `correlation_id` | Join to service logs |
| `capability_snapshot`, `archive_metadata` | JSONB audit/context |
| `alert_payload`, `analysis` | Full-fidelity JSONB envelope |
| `case_schema_version`, `analysis_schema_version` | Migration versions |
| `verdict`, `confidence`, `search_name`, `risk_score` | Filter facets |
| `report_md_path`, `report_html_path` | Optional compatibility pointers |
| `retrieval_status` | `pending`, `ready`, `failed`, `not_indexed` |
| `backfill_status` | `native`, `backfilled`, `legacy_summary` |
| `source_completeness` | `complete`, `missing_alert`, `missing_analysis`, `markdown_only` |

Alert facets such as `threat_category` live inside `alert_payload`, not as top-level columns.

### `case_chunks`

| Column | Purpose |
|--------|---------|
| `chunk_id`, `case_id` | Keys; cascade delete with case |
| `source_lane` | `alert_payload`, `case_analysis`, `legacy_summary` |
| `section`, `field_path`, `text` | Deterministic chunk identity and content |
| `embedding` | pgvector(1024) |
| `search_vector` | Generated tsvector for lexical retrieval |
| `metadata`, `chunk_schema_version`, `embedding_model` | Citation and rebuild metadata |

### Optional chat tables (when `CASE_QA_CHAT_HISTORY_ENABLED`)

- `chat_sessions`: session id, user id, mode, selected case, expiry.
- `chat_messages`: role, bounded content, internal `cited_sources`, `answer_status`.

## Chunking Policy

Store full alert and analysis in JSONB; embed deterministic section chunks.
Section-level chunks cover alert summary, verdict/reasoning, hypotheses,
evidence, IOCs, ATT&CK, query-result summaries, ServiceNow status summaries
(no secrets).

Do not embed by default: credentials, huge raw blobs, boilerplate, markdown/HTML
renderings, chat transcripts.

## Chat Source Metadata (shipped)

Retrieved chunks carry internal section metadata for hybrid retrieval and prompt
assembly. Portal chat does **not** expose citations, source links, or
`retrieved_case_ids` in the API or UI. Responses return `answer`,
`answer_status`, and optional `session_id` only. `cited_sources` may persist
internally when chat history is enabled.

## Failure Behavior (shipped)

Fail-visible for portal operators; ingest remains resilient:

- Transient Postgres write errors retry (`CASE_ARCHIVE_WRITE_MAX_ATTEMPTS=3`).
- Archive or chunk failure logs the error and returns non-success from
  `archive_case_for_portal`; ingest still completes unless analysis itself failed.
- Chunk failure after case row write keeps the row and sets
  `retrieval_status=failed` for rebuild.
- Portal chat retrieval failure returns clear errors or `unknown`/`refused`
  `answer_status`, not model-memory answers.
- Identity collisions (`CaseArchiveConflictError`) log and skip archive write.

## Backfill Path (shipped)

`scripts/backfill_case_archive.py`:

- Idempotent by `backfill:<sha256-prefix>` case ids.
- Complete imports need original alert plus structured analysis.
- Markdown-only imports become `legacy_summary` / incomplete cases.
- Dry-run and bounded batch size supported.

## Postgres Operations

Portal/archive requires Postgres when `CASE_ARCHIVE_ENABLED=true`.

Shipped:

- Schema SQL and install-time apply path.
- Retention delete for expired cases (and chat sessions when history enabled).
- Indexes: `processed_at`, `expires_at`, `verdict`, `search_name`, HNSW, GIN on
  `search_vector`.
- `CASE_POSTGRES_DSN` separate from `RAG_POSTGRES_DSN` (may share server).
- `scripts/rebuild_case_chunks.py` for manual chunk rebuild after schema/model
  changes.

Operator examples:

```bash
python scripts/rebuild_case_chunks.py --case-id CASE-123 --dry-run
python scripts/rebuild_case_chunks.py --case-id CASE-123
python scripts/rebuild_case_chunks.py --all --dry-run --batch-size 100
python scripts/rebuild_case_chunks.py --all --batch-size 100
```

Use `--config-env /etc/notable-analyzer/config.env` outside systemd.

## FastAPI Portal (shipped)

Separate `notable-portal.service`; Uvicorn on loopback; nginx in front.

Shipped endpoints:

- `GET /health`, `GET /ready`
- `GET /api/capabilities`, `GET /api/diagnostics/chat-readiness`
- `GET /api/cases`, `GET /api/cases/{case_id}`,
  `GET /api/cases/{case_id}/raw/{section}`
- `POST /api/chat` (query transport only; no case mutation)
- Chat history when enabled: `GET/DELETE /api/chat/sessions`, message fetch,
  `DELETE .../turns/last`

Implementation map:

- `portal_app.py` — routes, auth/proxy boundary, probes.
- `case_store.py` — analyzer-side Postgres writes.
- `case_index.py` — read-only list/detail queries.
- `case_search.py` — chunk creation and hybrid retrieval.
- `case_chat.py`, `case_chat_history.py` — chat synthesis and optional history.
- `scripts/rebuild_case_chunks.py`, `scripts/backfill_case_archive.py`.

### Frontend And Network (shipped)

React analyst portal (`frontend/analyst-portal/`) is the production UI. nginx
serves the built SPA and proxies API routes. See networking plan and network
deployment runbook for TLS, basic auth, DNS, and firewall.

Target path:

```text
analyst browser -> https://notable-portal.<internal-domain> -> nginx -> http://127.0.0.1:8080 -> Postgres notable_cases
```

## Chat Guardrails

Retrieval before generation. Structured input: question, `mode`, optional
`selected_case_id`, session id when history enabled. Structured output:
`answer`, `answer_status` (`answered`, `unknown`, `refused`).

### Chat Modes

| Mode | Status | Behavior |
|------|--------|----------|
| `selected_case` | Shipped | Pinned case chunks + Knowledge Base context; requires `selected_case_id` |
| `global_archive` | Deferred | Cross-case retrieval without a pinned case |

### Chat Cancellation

**Shipped:** client-side Stop aborts fetch; best-effort session/turn cleanup via
delete endpoints. Backend does not cooperatively cancel in-flight LLM work.

**Deferred:** cooperative disconnect handling and upstream abort.

## Schema Versioning

Stored on durable and derived data: `case_schema_version`,
`analysis_schema_version` on `cases`; `chunk_schema_version`, `embedding_model`
on `case_chunks`. Rebuild chunks when versions or embedding model change.

## End-To-End Slice Status

| Step | Status |
|------|--------|
| Canonical Postgres case record after analysis | Shipped |
| 30-day retention configuration and delete job | Shipped |
| Read-only portal list/detail over Postgres | Shipped |
| Selected-case chat with Knowledge Base context | Shipped |
| Global archive chat | Deferred |
| Optional bounded chat-history persistence | Shipped (off by default) |
| Legacy markdown backfill | Shipped |
| Prior-case tertiary retrieval in chat | Deferred |

## Open Decisions

- Should markdown remain a first-class output forever, or only as a compatibility
  artifact while the portal renders from Postgres JSONB?
- Should case-derived retrieval chunks include full alert fields, selected
  fields, or redacted field subsets?
- Which customer proxy/auth pattern should the first deployment guide emphasize
  beyond nginx basic auth: SSO header, mTLS, or all as examples?
- When to enable `global_archive` and prior-case retrieval without weakening
  source boundaries?

## Current Assumptions

- On-prem comes first; AWS follows after lessons learned.
- Original notable / alert payload is stored full fidelity.
- HTML is not stored as part of the archive.
- All authenticated analysts can see all retained notables in v1.
- FastAPI is the portal API framework; React is the portal UI.
- Chat history is disabled by default.
- Selected-case chat is the shipped chat slice; global archive chat is deferred.
- Prior retained cases are useful but tertiary behind current alert facts and SOC
  context.
