# Analyst Portal And Case Archive Technical Spec

## Status

Normative implementation contract for the shipped on-prem analyst portal, 30-day
Postgres case archive, and retrieval-bound portal chat.

Deferred work and open decisions (non-normative):
[`../planning/ANALYST_PORTAL_CASE_ARCHIVE_PLAN.md`](../planning/ANALYST_PORTAL_CASE_ARCHIVE_PLAN.md).

Operator runbooks:

- [`../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md)
- [`../operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](../operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md)
- [`../operations/analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md`](../operations/analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md)

AWS portal/archive parity contract (separate deployment path):
[`../../../s3_notable_pipeline/docs/technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md`](../../../s3_notable_pipeline/docs/technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md).

This document covers **on-prem only**. AWS portal, case archive, and Case Q&A are
shipped in `s3_notable_pipeline/` under the linked spec.

## Goal

Provide a read-only on-prem analyst portal backed by Postgres. Authenticated
analysts browse retained notables and ask retrieval-bound chat questions over:

- the full original alert/notable payload (stored canonically; UI may bound display),
- the validated structured analysis output,
- configured Knowledge Base / query-grounding context when enabled,
- the pinned retained case only (no cross-case archive search).

## Non-Goals

- Threat-intel adapters, CMDB enrichment, SOAR invocation, golden eval harness.
- Portal-triggered Splunk, ServiceNow, SOAR, remediation, suppression, rerun, or writeback.
- Per-case RBAC.
- Filesystem, SQLite, or FAISS fallback for portal/archive storage.
- Storing HTML as a canonical archive artifact.
- Alternate unstructured analyzer outputs as authoritative archive analysis in v1.

## Locked Decisions

- Postgres is required for the `analyst_portal` capability.
- Use the existing Postgres server/database with schema `notable_cases`; RAG tables
  remain in their current schema (for example `notable_rag`).
- Canonical case source of truth is Postgres JSONB, not markdown or HTML.
- Markdown/HTML may still be generated when current settings enable them; portal
  chat does not depend on filesystem artifacts.
- FastAPI/Uvicorn serves the portal API; React UI is served by nginx in production.
- FastAPI binds to loopback by default: `127.0.0.1:8080`.
- All authenticated analysts can see all non-expired retained cases in v1.
- Chat history is off by default.
- Chunk rebuild is a manual operator script, not automatic in v1.
- Native case writes are idempotent by deterministic `case_id`.
- nginx terminates TLS and basic auth; FastAPI trusts proxy-injected identity headers
  only when the shared proxy secret matches.
- V1 chunks selected high-value alert fields and the full validated analysis.

### Network Design Rationale

| Decision | Rationale |
|----------|-----------|
| nginx is the documented front door | TLS, authentication, static SPA delivery, rate limits, and access logs stay outside FastAPI. |
| FastAPI binds to loopback | Analyst subnets cannot reach Uvicorn directly; `PORTAL_ALLOW_NON_LOOPBACK_BIND=false` is the default. |
| nginx basic auth is the v1 example | It provides a simple internal deployment path while allowing customer SSO to replace authentication at nginx later. |
| OIDC is the recommended future state | oauth2-proxy runs on loopback, nginx uses `auth_request`, and the corporate IdP enforces MFA plus an approved analyst group. |
| nginx injects a shared proxy secret | `X-Notable-Portal-Proxy-Secret` prevents direct loopback callers from impersonating an authenticated proxy request. |
| nginx supplies trusted user identity | `PORTAL_TRUSTED_USER_HEADER=X-Forwarded-User` is accepted only after proxy-secret validation. |
| Case visibility is flat in v1 | Every authenticated analyst can see every retained case; per-case RBAC is deferred. |
| nginx is co-located by default | `install.sh` assumes the analyzer host, but a separate internal web host is valid when the proxy, database, identity, and secret boundaries are preserved. |

## Implementation Status

### Shipped

| Area | Modules / assets |
|------|------------------|
| Archive writes | `case_store.py`, `case_archive_flow.py`, `case_db.py` |
| Chunk index | `case_search.py`, `scripts/rebuild_case_chunks.py` |
| Portal reads | `case_index.py`, `portal_app.py`, `portal_api_models.py`, `portal_case_detail_view.py` |
| Portal chat | `case_chat.py`, `case_chat_history.py` |
| Schema | `deploy/postgres/notable_cases_schema.sql` |
| Deploy | `deploy/systemd/notable-portal.service`, `deploy/nginx/notable-portal.conf` |
| Backfill | `scripts/backfill_case_archive.py` |
| Config | `config.py` (`analyst_portal` profile), `config.env.example`, `config.portal.env.example` |
| Tests | `tests/onprem_service/test_case_*.py`, `test_portal_*.py` |

### Planned / deferred (not required for v1 operation)

- Per-case RBAC, OIDC/oauth2-proxy nginx example and break-glass procedure, cross-case archive chat mode.
- Automatic chunk rebuild on analyzer replay failure recovery.
- Dedicated `notable_portal` role grants in schema SQL (operators grant manually today).
- Embedding every raw alert JSON field (full payload remains in `cases.alert_payload`).

## Runtime Config

Analyzer/runtime reference: `config.env.example`.
Portal-only process reference: `config.portal.env.example` (narrower env; prefer
read-only `CASE_POSTGRES_DSN` for the portal role).

### Archive And Postgres

```env
CASE_ARCHIVE_ENABLED=false
CASE_POSTGRES_DSN=postgresql://notable_analyzer@127.0.0.1:5432/notable_rag
CASE_POSTGRES_SCHEMA=notable_cases
CASE_RETENTION_DAYS=30
CASE_RETENTION_DELETE_BATCH_SIZE=500
CASE_ARCHIVE_WRITE_MAX_ATTEMPTS=3
CASE_ARCHIVE_WRITE_RETRY_BACKOFF_SECONDS=1
CASE_POSTGRES_STATEMENT_TIMEOUT_MS=5000
CASE_SCHEMA_VERSION=1
CASE_ANALYSIS_SCHEMA_VERSION=1
```

### Retrieval And Chat

```env
CASE_QA_ENABLED=false
CASE_QA_MAX_CHUNKS_PER_LANE=6
CASE_QA_MAX_TOTAL_CHUNKS=18
CASE_QA_MAX_INDEX_CHUNKS_PER_CASE=200
CASE_QA_CONTEXT_BUDGET_CHARS=12000
CASE_QA_MAX_QUESTION_CHARS=2000
CASE_QA_MAX_ANSWER_TOKENS=800
CASE_QA_CHUNK_SCHEMA_VERSION=1
CASE_QA_EMBEDDING_MODEL=mixedbread-ai/mxbai-embed-large-v1
CASE_QA_VECTOR_DIMENSIONS=1024
CASE_QA_CHAT_HISTORY_ENABLED=false
CASE_QA_CHAT_HISTORY_RETENTION_DAYS=7
CASE_QA_MAX_MESSAGES_PER_SESSION=30
CASE_QA_MAX_SESSIONS_PER_USER=10
CASE_QA_MAX_STORED_MESSAGE_BYTES=4000
CASE_QA_MAX_CONVERSATION_TURNS=10
CASE_QA_MAX_CONVERSATION_CHARS=6000
CASE_QA_LEXICAL_TOP_K=30
CASE_QA_VECTOR_TOP_K=30
CASE_QA_RRF_K=60
CASE_QA_GENERAL_KNOWLEDGE_ENABLED=true
```

When `CASE_QA_CHAT_HISTORY_ENABLED=true`, prior transcript turns may be loaded
into synthesis prompts up to `CASE_QA_MAX_CONVERSATION_TURNS` and
`CASE_QA_MAX_CONVERSATION_CHARS`. Transcript rows are not retrieval sources.

### Portal

```env
PORTAL_ENABLED=false
PORTAL_BIND_HOST=127.0.0.1
PORTAL_PORT=8080
PORTAL_PAGE_SIZE=50
PORTAL_CHAT_MAX_CONCURRENCY=18
PORTAL_TRUSTED_USER_HEADER=X-Forwarded-User
PORTAL_PROXY_SECRET=
PORTAL_PROXY_SECRET_HEADER=X-Notable-Portal-Proxy-Secret
PORTAL_ALLOW_NON_LOOPBACK_BIND=false
```

Validation rules (`config.py`):

- `CASE_QA_VECTOR_DIMENSIONS` must be `1024` and match `RAG_VECTOR_DIMENSIONS`.
- `PORTAL_ENABLED=true` requires `CASE_ARCHIVE_ENABLED=true` and non-empty
  `PORTAL_PROXY_SECRET`.
- `CASE_QA_ENABLED=true` requires `CASE_ARCHIVE_ENABLED=true`.

## Capability Profile Behavior

```env
CAPABILITY_PROFILES=core,analyst_portal
```

`analyst_portal` enables:

- `CASE_ARCHIVE_ENABLED=true`
- `PORTAL_ENABLED=true`
- `CASE_QA_ENABLED=true`

It does not enable Splunk/Elasticsearch execution, ServiceNow create, SOAR
actions, HTML reports, or chat history. Explicit env overrides remain allowed.

Portal chat requires a pinned case (`selected_case_id`). Cross-case archive search
is not supported.

## Postgres DDL

Source of truth: `deploy/postgres/notable_cases_schema.sql`.

### Extensions And Schema

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE SCHEMA IF NOT EXISTS notable_cases;
```

### `notable_cases.cases`

Same columns and check constraints as the migration file. Notable indexes beyond
the planning minimum:

- `cases_processed_at_case_id_idx` on `(processed_at DESC, case_id ASC)` for cursor pagination.
- `updated_at` maintained by trigger `cases_set_updated_at`.

### `notable_cases.case_chunks`

Shipped schema adds:

- generated stored `search_vector tsvector` over `section`, `field_path`, and `text`
- GIN index `case_chunks_search_vector_gin_idx`
- HNSW index `case_chunks_embedding_hnsw_idx` on `embedding vector_cosine_ops`

Lexical chat retrieval uses `search_vector`; vector retrieval uses pgvector cosine
distance. V1 fixes `CASE_QA_VECTOR_DIMENSIONS=1024` and `vector(1024)`.

### Chat History Tables

Created by migration; used when `CASE_QA_CHAT_HISTORY_ENABLED=true`.

`chat_messages` includes optional `answer_status` with check constraint
`answered | unknown | refused`. Session/message retention deletes expired
`chat_sessions` in the analyzer retention loop (cascade deletes messages).

Migration grants DML on all `notable_cases` tables to `notable_analyzer` when that
role exists. Deployments using custom DSN roles must grant least privilege separately
(for example read-only portal role on cases/chunks, read/write on chat tables only
when history is enabled).

## Case Identity And Replay Contract

Native `case_id` is built by `build_native_case_id()`:

1. First non-empty alert field among `correlation_id`, `notable_id`, `event_id`, `sid`.
2. Else sanitized input filename stem.

Values are sanitized to a bounded filename-safe id; oversized or unsafe raw values
hash-suffix into `prefix_<sha256-prefix>`.

Report filenames continue to use `get_notable_id(alert_payload, file_path)`; archive
identity is independent of transport filename when upstream ids exist.

Native writes use `INSERT ... ON CONFLICT (case_id) DO UPDATE` only when the
existing row matches the same source identity via at least one of:

- `source_filename`
- non-empty matching `correlation_id`
- non-empty matching `finding_id`

Otherwise the upsert returns no row and `CaseArchiveConflictError` is raised.
The analyzer orchestration logs the conflict and continues ingest; it does not
overwrite an unrelated case.

On native replay, the implementation updates the case row, deletes derived chunks
for that `case_id`, and rebuilds chunks on the subsequent indexing step. Original
`created_at` is preserved; `updated_at` changes via trigger.

When analysis is PoC unstructured output, derived chunks are not built and
`retrieval_status='not_indexed'`.

Backfilled cases use `case_id = backfill:<sha256-prefix>` (minimum 16 hex chars)
from stable source bytes in priority order: alert+analysis, alert only, markdown
report only. Backfill is idempotent by `case_id`.

## Case Record Contract

`alert_payload` stores full-fidelity native input. Plain text inputs wrap as:

```json
{"input_type": "text", "text": "..."}
```

`analysis` stores validated structured output after deterministic normalization,
repair, ATT&CK filtering, optional query enrichment/interpretation, and optional
ServiceNow status insertion. Do not store raw unvalidated model output as
authoritative `analysis`.

For native analyzer writes, both `alert_payload` and validated `analysis` are
required at the application layer except PoC fallback (`analysis=NULL`,
`source_completeness='missing_analysis'`, `retrieval_status='not_indexed'`,
`poc_unstructured_output` / `poc_fallback_reason` in `archive_metadata`).

### Column Extraction Rules

| Column | Rule |
|--------|------|
| `finding_id` | Input filename stem |
| `source_filename` | Original input filename only |
| `processed_at` | UTC time after final analysis is built |
| `expires_at` | `processed_at + CASE_RETENTION_DAYS` |
| `correlation_id` | First non-empty among `correlation_id`, `notable_id`, `event_id`, `sid` |
| `capability_snapshot` | Enabled capability flags and key model/retrieval config at processing time |
| `verdict` | Normalized `analysis.alert_reconciliation.verdict`: `likely_benign`, `likely_malicious`, or `unknown` |
| `confidence` | Numeric parse of reconciliation confidence; non-numeric becomes `NULL` |
| `search_name` | First non-empty among `search_name`, `searchName`, `rule_name`, `rule`, `signature`, `title` |
| `risk_score` | Numeric parse of `risk_score` / `riskScore`; invalid becomes `NULL` |

## Chunking Contract

Chunks are built deterministically from JSON (`case_search.build_case_chunks`), not
from markdown/HTML. Embedding uses the on-prem sentence-transformers stack with
`CASE_QA_EMBEDDING_MODEL` (default Mixedbread 1024-d).

| Section | Source |
|---------|--------|
| `alert.summary` | Derived summary from high-value alert fields |
| `alert.key_fields` | Selected high-value alert leaf fields |
| `analysis.alert_reconciliation` | `$.alert_reconciliation` |
| `analysis.competing_hypotheses` | `$.competing_hypotheses` |
| `analysis.evidence_vs_inference` | `$.evidence_vs_inference` |
| `analysis.ioc_extraction` | `$.ioc_extraction` |
| `analysis.ttp_analysis` | `$.ttp_analysis` |
| `analysis.query_result_section` | `$.query_result_section` |
| `analysis.servicenow_section` | `$.servicenow_section` |

Stored `case_chunks.source_lane` values: `alert_payload`, `case_analysis`,
`legacy_summary`. Contextual lanes (`current_case`, `knowledge_base`) are assigned
at chat retrieval time only.

Chunk IDs: `<case_id>:<source_lane>:<section>:<ordinal>` with sanitized components.
Indexing stops at `CASE_QA_MAX_INDEX_CHUNKS_PER_CASE` in traversal order.

`store_case_chunks()` sets `retrieval_status='ready'` on success, `'not_indexed'`
when zero chunks, and orchestration sets `'failed'` when chunk persistence fails
after the case row exists.

Rebuild tooling skips rows with `retrieval_status='not_indexed'`,
`backfill_status='legacy_summary'`, or `source_completeness != 'complete'`.

## Chat Response Contract

Portal chat returns bounded synthesized `answer`, `answer_status`, and optional
`session_id`. The API does not expose retrieved chunk citations or case-id lists.

`answer_status` values: `answered`, `unknown`, `refused`.

Retrieval context lanes at synthesis time:

- `current_case`: chunks from `selected_case_id`
- `knowledge_base`: advisory RAG / SPL / Elasticsearch grounding when configured
- `prior_case`: unused (cross-case search removed)

Supported mode: `selected_case` only; requires `selected_case_id`.

Synthesis uses configured local LLM (`LLM_API_URL`, `LLM_API_TOKEN`,
`LLM_MODEL_NAME`, `LLM_TIMEOUT`). User-visible answers strip citation markers.

### Retrieval

Hybrid search over `case_chunks`:

1. Lexical candidates via `search_vector` / `plainto_tsquery`, up to `CASE_QA_LEXICAL_TOP_K`.
2. Vector candidates via pgvector cosine distance, up to `CASE_QA_VECTOR_TOP_K`.
3. Reciprocal-rank fusion with `CASE_QA_RRF_K`.
4. Deduplicate by `chunk_id`, assign lanes, trim to per-lane, total chunk, and
   character budgets.

Only cases with `retrieval_status='ready'` and `expires_at > now()` participate.

When chat history is disabled, incoming `session_id` is ignored and responses
return `session_id=null`. When enabled, bounded transcript persistence applies
(`CASE_QA_MAX_MESSAGES_PER_SESSION`, `CASE_QA_MAX_STORED_MESSAGE_BYTES`,
`CASE_QA_CHAT_HISTORY_RETENTION_DAYS`, `CASE_QA_MAX_SESSIONS_PER_USER`).

### Guardrails

- Weak or empty archive retrieval: return `unknown`, or when
  `CASE_QA_GENERAL_KNOWLEDGE_ENABLED=true`, attempt bounded general technology
  synthesis instead of case facts.
- Generated answers that claim portal-performed external actions are post-synthesis
  rejected with `answer_status='refused'`. Question text is not pre-refused by
  keyword rules in production chat.
- Chat must not call Splunk, ServiceNow, SOAR, or other action systems.

## Failure And Retry Contract

When `CASE_ARCHIVE_ENABLED=true`:

- Retry transient Postgres errors up to `CASE_ARCHIVE_WRITE_MAX_ATTEMPTS`.
- Do not retry schema/validation/config errors.
- Archive write failures after retries are logged; ingest continues on the normal
  processed path except identity conflicts (logged, no overwrite).
- Case insert success with chunk failure keeps the row and sets
  `retrieval_status='failed'`.
- Portal chat returns `503` when archive DB is transiently unavailable; it does not
  answer from model memory when retrieval dependencies fail readiness checks.

Analyzer write ordering:

1. Build final `llm_response`.
2. Generate markdown/HTML when enabled.
3. Upsert Postgres case row (`archive_case_for_portal`).
4. Build and store chunks; mark retrieval status.
5. Move input to processed unless analysis itself failed.

## Backfill Contract

Operator command: `scripts/backfill_case_archive.py`.

- Dry-run reports candidate legacy markdown imports.
- Execute requires `CASE_ARCHIVE_ENABLED=true` and `--config-env`.
- Markdown-only imports use `legacy_summary`, `source_completeness='markdown_only'`,
  `retrieval_status='not_indexed'`; not indexed for retrieval in v1.
- Idempotent by `backfill:<sha256-prefix>` case ids.

## Portal API Contract

FastAPI app: `portal_app.build_portal_app()`.

### Public Endpoints

- `GET /health` — liveness (`200`, unauthenticated)
- `GET /ready` — Postgres case archive tables readable (`200` / `503`)

### Authenticated Read/API Endpoints

All non-public routes require:

- matching `PORTAL_PROXY_SECRET_HEADER` value
- non-empty `PORTAL_TRUSTED_USER_HEADER` within length bounds

Mutating browser requests must pass same-origin checks (`Sec-Fetch-Site` / `Origin`).

- `GET /api/capabilities`
- `GET /api/diagnostics/chat-readiness`
- `GET /api/cases`
- `GET /api/cases/{case_id}`
- `GET /api/cases/{case_id}/raw/{section}` — paginated canonical JSON (`alert_payload` or `analysis`)
- `POST /api/chat`
- When `CASE_QA_CHAT_HISTORY_ENABLED=true`:
  - `GET /api/chat/sessions`
  - `GET /api/chat/sessions/{session_id}/messages`
  - `DELETE /api/chat/sessions/{session_id}`
  - `DELETE /api/chat/sessions/{session_id}/turns/last`

`POST /api/chat` is query transport only; it must not mutate cases or trigger
external actions. Concurrent chat is bounded by `PORTAL_CHAT_MAX_CONCURRENCY`
(`429` when saturated).

### `GET /api/cases`

Query params:

- `limit`: optional, default `PORTAL_PAGE_SIZE`, max `100`
- `cursor_processed_at`, `cursor_case_id`: both required when either is present
- `start` / `end`: ISO-8601 filters on `processed_at`
- `start_date` / `end_date`: UTC calendar date (`YYYY-MM-DD`) filters; mutually exclusive with `start`/`end`
- `verdict`: exact match
- `search_name`: case-insensitive substring match

Only non-expired rows (`expires_at > now()`) are returned. Invalid params → `400`.

List items include optional `archive_notices` derived from retrieval/completeness
metadata.

### `GET /api/cases/{case_id}`

Returns bounded `alert_payload` and `analysis` views plus `content_bounds`
(truncation flags, total key counts, available raw sections). Full canonical JSON
remains in Postgres; use the raw section endpoint when truncated.

Unknown or expired cases → `404`.

### `POST /api/chat`

Request:

```json
{
  "mode": "selected_case",
  "question": "What evidence supports this alert?",
  "selected_case_id": "case-123",
  "session_id": null
}
```

Response:

```json
{
  "answer": "...",
  "answer_status": "answered",
  "session_id": null
}
```

Invalid mode, oversized question, or missing `selected_case_id` → `400`.
Unknown `selected_case_id` → `404` with `detail="Case not found."` before retrieval.

Production UI: React analyst portal behind nginx; FastAPI serves API and probes on
loopback.

## Networking Contract

```text
analyst browser
-> https://notable-portal.<internal-domain>
-> nginx :443 (TLS, basic auth, proxy secret + user headers)
-> http://127.0.0.1:8080 FastAPI/Uvicorn
-> Postgres notable_cases schema
```

See [`../operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](../operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md).

## Postgres Operations Contract

Role separation (same database allowed):

- `notable_analyzer`: read/write cases and chunks; chat tables when history enabled
- `notable_portal`: read-only cases/chunks; chat read/write only when history enabled
- migration/operator role: schema owner; not used by long-running services

Retention deletes expired `notable_cases.cases` rows in batches no larger than
`CASE_RETENTION_DELETE_BATCH_SIZE` from the analyzer retention loop (`retention.py`).
Chunk deletion relies on `ON DELETE CASCADE`. Chat session expiry uses the same
batch size setting in `case_chat_history`.

Vector index: shipped schema includes HNSW; small pilots may operate without tuning.
Index changes must not alter API behavior.

## Documentation Contract

Operator documentation lives under `docs/operations/analyst_portal/`:

- [`ANALYST_PORTAL_OPERATIONS.md`](../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md) — enable/disable, systemd, DB maintenance, chunk rebuild, backfill, troubleshooting
- [`ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](../operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md) — DNS, TLS, nginx, firewall
- [`ANALYST_PORTAL_CHAT_SECURITY.md`](../operations/analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md) — chat guardrails and read-only boundary

## Verification Commands

Primary unit command:

```bash
python -m unittest discover -s llm_notable_analysis_onprem_systemd/tests -v
```

Targeted portal/archive tests live under `tests/onprem_service/test_case_*.py` and
`tests/onprem_service/test_portal_*.py`.

## Deferred Decisions After V1

- Long-term markdown/HTML compatibility outputs after portal adoption.
- Embedding every raw alert field (full JSONB already stored).
- SSO-header nginx example beyond basic auth + trusted user header.
- Alert field `id` as an archive identity source (not used by shipped
  `build_native_case_id()` today).
