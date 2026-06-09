# Analyst Portal And Case Archive Technical Spec

## Status

Implementation contract for the on-prem analyst portal, 30-day Postgres case
archive, and retrieval-bound portal chatbot.

The planning sources are:

- `../planning/ANALYST_PORTAL_CASE_ARCHIVE_PLAN.md`
- `../planning/ANALYST_PORTAL_NETWORKING_PLAN.md`

## Goal

Add an on-prem, read-only analyst portal backed by Postgres. The portal lets
authenticated analysts browse retained notables and ask retrieval-bound chat
questions over:

- the full original alert/notable payload,
- the validated structured analysis output,
- approved Knowledge Base context,
- related retained cases from the 30-day archive.

AWS implementation is explicitly out of scope for this spec.

## Non-Goals

- AWS portal/archive implementation.
- Threat-intel adapters.
- CMDB or asset enrichment.
- SOAR playbook invocation.
- Golden eval harness implementation.
- Portal-triggered Splunk, ServiceNow, SOAR, remediation, suppression, rerun, or
  writeback actions.
- Per-case RBAC.
- Filesystem, SQLite, or FAISS fallback for portal/archive storage.
- Storing HTML as a canonical archive artifact.
- Freeform analyzer portal archival in v1. This spec targets the structured
  notable analyzer path first.

## Locked Decisions

- Postgres is required for the `analyst_portal` capability.
- Use the existing Postgres server/database, with a new schema:
  `notable_cases`.
- Existing RAG/SPL grounding tables remain in their current schema, such as
  `notable_rag`.
- The portal/archive uses new Postgres tables under `notable_cases`.
- The canonical case source of truth is Postgres JSONB, not markdown or HTML.
- Markdown and HTML may still be generated when current settings enable them,
  but portal/chat does not depend on filesystem artifacts.
- Use FastAPI/Uvicorn for the portal app.
- Use a custom minimal FastAPI-served portal UI for v1; do not integrate
  OpenWebUI or another open-source chat UI in this slice.
- Use nginx as the first documented reverse proxy path.
- FastAPI binds to loopback by default: `127.0.0.1:8080`.
- All authenticated analysts can see all retained cases in v1.
- Chat history is off by default.
- Chunk rebuild is a manual operator script, not automatic in v1.
- Native case writes are idempotent by deterministic `case_id`.
- Basic auth through nginx is the first documented v1 auth path.
- V1 chunks selected high-value alert fields and the full validated analysis.

## Runtime Config

Add these config values to `config.py` and `config.env.example`.

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
CASE_QA_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
CASE_QA_VECTOR_DIMENSIONS=768
CASE_QA_CHAT_HISTORY_ENABLED=false
CASE_QA_CHAT_HISTORY_RETENTION_DAYS=7
CASE_QA_MAX_MESSAGES_PER_SESSION=30
CASE_QA_MAX_STORED_MESSAGE_BYTES=4000
CASE_QA_LEXICAL_TOP_K=30
CASE_QA_VECTOR_TOP_K=30
CASE_QA_RRF_K=60
```

### Portal

```env
PORTAL_ENABLED=false
PORTAL_BIND_HOST=127.0.0.1
PORTAL_PORT=8080
PORTAL_PAGE_SIZE=50
PORTAL_TRUSTED_USER_HEADER=X-Forwarded-User
```

## Capability Profile Behavior

Add a new profile:

```env
CAPABILITY_PROFILES=core,analyst_portal
```

`analyst_portal` enables:

- `CASE_ARCHIVE_ENABLED=true`
- `PORTAL_ENABLED=true`
- `CASE_QA_ENABLED=true`

Portal chat requires a pinned case (`selected_case_id`). Cross-case archive
search is not supported.

It must not enable:

- Splunk execution.
- Elasticsearch execution.
- ServiceNow create.
- SOAR actions.
- Chat history.

Explicit low-level env overrides remain allowed.

## Postgres DDL

The migration should create schema `notable_cases` and these tables. Use
`pgvector` for embeddings.

### Extensions And Schema

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS notable_cases;
```

### `notable_cases.cases`

```sql
CREATE TABLE IF NOT EXISTS notable_cases.cases (
    case_id text PRIMARY KEY,
    finding_id text,
    source_filename text NOT NULL,
    processed_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    correlation_id text,
    capability_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    archive_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,

    alert_payload jsonb,
    analysis jsonb,
    case_schema_version integer NOT NULL,
    analysis_schema_version integer NOT NULL,

    verdict text,
    confidence numeric,
    search_name text,
    risk_score numeric,

    report_md_path text,
    report_html_path text,

    retrieval_status text NOT NULL DEFAULT 'pending',
    backfill_status text NOT NULL DEFAULT 'native',
    source_completeness text NOT NULL DEFAULT 'complete',

    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT cases_retrieval_status_check
        CHECK (retrieval_status IN ('pending', 'ready', 'failed', 'not_indexed')),
    CONSTRAINT cases_backfill_status_check
        CHECK (backfill_status IN ('native', 'backfilled', 'legacy_summary')),
    CONSTRAINT cases_source_completeness_check
        CHECK (source_completeness IN ('complete', 'missing_alert', 'missing_analysis', 'markdown_only'))
);
```

Indexes:

```sql
CREATE INDEX IF NOT EXISTS cases_processed_at_idx
    ON notable_cases.cases (processed_at DESC);

CREATE INDEX IF NOT EXISTS cases_expires_at_idx
    ON notable_cases.cases (expires_at);

CREATE INDEX IF NOT EXISTS cases_verdict_idx
    ON notable_cases.cases (verdict);

CREATE INDEX IF NOT EXISTS cases_search_name_idx
    ON notable_cases.cases (search_name);

CREATE INDEX IF NOT EXISTS cases_search_name_trgm_idx
    ON notable_cases.cases USING gin (search_name gin_trgm_ops);
```

`updated_at` must be maintained either by application code on every update or by
a migration-created trigger. Prefer a trigger in `deploy/postgres/notable_cases_schema.sql`
so backfill and rebuild tools get the same behavior:

```sql
CREATE OR REPLACE FUNCTION notable_cases.set_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS cases_set_updated_at ON notable_cases.cases;
CREATE TRIGGER cases_set_updated_at
BEFORE UPDATE ON notable_cases.cases
FOR EACH ROW EXECUTE FUNCTION notable_cases.set_updated_at();
```

### `notable_cases.case_chunks`

```sql
CREATE TABLE IF NOT EXISTS notable_cases.case_chunks (
    chunk_id text PRIMARY KEY,
    case_id text NOT NULL REFERENCES notable_cases.cases(case_id) ON DELETE CASCADE,
    source_lane text NOT NULL,
    section text NOT NULL,
    field_path text NOT NULL,
    text text NOT NULL,
    embedding vector(768),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    chunk_schema_version integer NOT NULL,
    embedding_model text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT case_chunks_source_lane_check
        CHECK (source_lane IN ('alert_payload', 'case_analysis', 'legacy_summary'))
);
```

Indexes:

```sql
CREATE INDEX IF NOT EXISTS case_chunks_case_id_idx
    ON notable_cases.case_chunks (case_id);

CREATE INDEX IF NOT EXISTS case_chunks_section_idx
    ON notable_cases.case_chunks (section);
```

If the target Postgres version supports the chosen pgvector index type, add a
vector index during migration or as a documented optional operator step. Exact
index parameters should be set after measuring corpus size.

V1 fixes `CASE_QA_VECTOR_DIMENSIONS=768` to match the existing BGE embedding
default and the `vector(768)` column. Changing dimensions later requires a
schema migration and chunk rebuild.

### Optional Chat History Tables

Only use these when `CASE_QA_CHAT_HISTORY_ENABLED=true`.

```sql
CREATE TABLE IF NOT EXISTS notable_cases.chat_sessions (
    session_id text PRIMARY KEY,
    user_id text,
    mode text NOT NULL,
    selected_case_id text,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS notable_cases.chat_messages (
    message_id text PRIMARY KEY,
    session_id text NOT NULL REFERENCES notable_cases.chat_sessions(session_id) ON DELETE CASCADE,
    role text NOT NULL,
    content text NOT NULL,
    cited_sources jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT chat_messages_role_check
        CHECK (role IN ('user', 'assistant', 'system'))
);

CREATE INDEX IF NOT EXISTS chat_messages_session_id_idx
    ON notable_cases.chat_messages (session_id, created_at);

CREATE INDEX IF NOT EXISTS chat_sessions_expires_at_idx
    ON notable_cases.chat_sessions (expires_at);
```

The migration grants schema usage and table DML privileges to the default
runtime role `notable_analyzer` when that role exists. Deployments using a
custom `CASE_POSTGRES_DSN` role must grant equivalent least-privilege access to
the `notable_cases` schema and tables.

## Case Identity And Replay Contract

Native analyzer cases use a deterministic archive identity separate from the
report filename. `case_id` prefers the first non-empty upstream source identity
from `correlation_id`, `notable_id`, `event_id`, `sid`, or `id`; if none is
available, it falls back to the sanitized input filename stem. Report filenames
continue to use `get_notable_id(alert_payload, file_path)` so existing file
output behavior is unchanged.

Native writes use `INSERT ... ON CONFLICT (case_id) DO UPDATE` only when the
existing row represents the same source identity. The implementation must treat
the replay as the same case when at least one of these is true:

- `source_filename` matches the current input filename.
- `correlation_id` is non-empty and matches the existing row.
- `finding_id` is non-empty and matches the existing row.

If `case_id` already exists but the source identity does not match, fail the
archive write visibly rather than overwriting an unrelated case.

On native replay, update the case row, replace derived chunks for that `case_id`,
and preserve the original `created_at`. The `updated_at` value must change.
If a replay downgrades to `poc_unstructured_output`, remove previously derived
chunks and set `retrieval_status='not_indexed'`.

Backfilled cases use `case_id = backfill:<sha256-prefix>` where the hash is
derived from the best stable source available, in this order:

1. Original alert bytes plus structured analysis bytes.
2. Original alert bytes.
3. Markdown report bytes.

Use at least the first 16 hex characters of the SHA-256 digest. Backfill is
idempotent by this `case_id` and must not collide with native source-identity
case IDs.

## Case Record Contract

`alert_payload` stores the original alert full fidelity for native portal cases.
If the original input was plain text, wrap it:

```json
{
  "input_type": "text",
  "text": "..."
}
```

`analysis` stores the validated structured LLM analysis object after deterministic
normalization, repair, ATT&CK filtering, optional query-result enrichment,
optional query-result interpretation, and optional ServiceNow status insertion.

Do not store raw unvalidated model output as authoritative `analysis`.

For native cases written by the analyzer, both `alert_payload` and `analysis`
are required at the application layer. The database columns allow nulls only so
one-time backfill can represent incomplete historical cases honestly, such as
markdown-only legacy summaries.

### Column Extraction Rules

The JSONB columns remain canonical. Top-level scalar columns are nullable,
derived fields used for filtering and display.

Use these extraction rules for native cases:

| Column | Extraction rule |
|--------|-----------------|
| `finding_id` | Existing `finding_id` from `file_path.stem` |
| `source_filename` | Original input filename only, not full path |
| `processed_at` | Current UTC processing time after final analysis is built |
| `expires_at` | `processed_at + CASE_RETENTION_DAYS` |
| `correlation_id` | First non-empty known alert identifier, such as `correlation_id`, `notable_id`, or `event_id` |
| `capability_snapshot` | Enabled capability flags plus key model/retrieval config values at processing time |
| `verdict` | Normalized `analysis.alert_reconciliation.verdict`; one of `likely_benign`, `likely_malicious`, or `unknown` |
| `confidence` | Numeric parse of `analysis.alert_reconciliation.confidence`; `"n/a"`, empty, missing, or invalid values become `NULL` |
| `search_name` | First non-empty alert field from `search_name`, `searchName`, `rule_name`, `rule`, `signature`, or `title` |
| `risk_score` | Numeric parse of common alert risk fields such as `risk_score` or `riskScore`; invalid values become `NULL` |

Confidence coercion must accept numeric strings such as `"0.72"` and numeric
values such as `0.72`. It must not fail the archive write solely because the
model emitted `"n/a"` or another non-numeric confidence value.
The confidence value represents confidence in the selected verdict, not an
independent probability that the alert is malicious.

Verdict normalization must keep the stored/API contract bounded. The prompt asks
for `likely_benign`, `likely_malicious`, or `unknown`; legacy/free-form values
such as `false positive`, `benign`, `true positive`, or `likely malicious` are
coerced into the closest allowed value, with unsupported values stored as
`unknown`.

### PoC Fallback Behavior

When `llm_response.get("poc_unstructured_output")` is true, the analyzer did not
produce authoritative validated analysis for archive retrieval.

For native cases with `CASE_ARCHIVE_ENABLED=true`:

- Insert or update the case row so the portal can show that processing happened.
- Set `analysis=NULL`.
- Set `source_completeness='missing_analysis'`.
- Set `retrieval_status='not_indexed'`.
- Store `poc_unstructured_output=true` and `poc_fallback_reason` in
  `archive_metadata`.
- Do not store `raw_response` as authoritative `analysis`.
- Do not build chunks from raw unvalidated model output.

## Chunking Contract

Build chunks deterministically from JSON fields, not from markdown or HTML.

Embedding generation should reuse the existing on-prem RAG embedding stack and
model defaults (`BAAI/bge-base-en-v1.5`, 768 dimensions) rather than adding a
new embedding service in this portal slice.

Initial section mapping:

| Section | JSON path |
|---------|-----------|
| `alert.summary` | Derived summary text from high-value alert fields |
| `alert.key_fields` | Selected high-value alert fields |
| `analysis.alert_reconciliation` | `$.alert_reconciliation` |
| `analysis.competing_hypotheses` | `$.competing_hypotheses` |
| `analysis.evidence_vs_inference` | `$.evidence_vs_inference` |
| `analysis.ioc_extraction` | `$.ioc_extraction` |
| `analysis.ttp_analysis` | `$.ttp_analysis` |
| `analysis.query_result_section` | `$.query_result_section` |
| `analysis.servicenow_section` | `$.servicenow_section` |

V1 alert chunks should cover selected high-value alert fields, not every raw
JSON field. Keep the full alert payload in `cases.alert_payload`; chunk only
fields useful for retrieval, including identifiers, search name, notable title,
risk fields, user, host, src/dest, process, command line, file path, URL, IP,
domain, and the normalized alert summary when available.

V1 analysis chunks must cover the full validated structured analysis. If an
analysis field is too large for one chunk, split it deterministically by array
item or object field while preserving `field_path`.

Chunk indexing must stop deterministically at
`CASE_QA_MAX_INDEX_CHUNKS_PER_CASE` before embedding so one large case cannot
produce an unbounded model encode batch. Preserve the traversal order above when
trimming.

Stored `case_chunks.source_lane` values describe what the chunk is inside the
stored archive record:

- `alert_payload`
- `case_analysis`
- `legacy_summary`

Do not store contextual lanes such as `current_case`, `prior_case`, or
`knowledge_base` in `case_chunks.source_lane`; those are chat retrieval context
lanes assigned at answer time.

Chunk IDs must be deterministic and stable across rebuilds:

```text
<case_id>:<source_lane>:<section>:<ordinal>
```

Sanitize each component with the same conservative filename-safe character set
used for notable IDs. `ordinal` is zero-based within the section after
deterministic traversal.

Every chunk must include:

- `chunk_id`
- `case_id`
- `source_lane`
- `section`
- `field_path`
- `text`
- `metadata`
- `chunk_schema_version`
- `embedding_model`

If a new validated analysis section becomes part of the product, the chunk
builder must either index it or explicitly document why it is excluded.

## Chat Response Contract

Portal chat returns a bounded synthesized answer and `answer_status` only. The
API does not expose retrieved-source citations or case-id lists to the client.
Retrieved chunks still carry internal section metadata for retrieval and prompt
assembly.

Chat response `source_lane` values used during retrieval are contextual to the
request:

- `current_case`: the selected case in `selected_case` mode.
- `prior_case`: removed; cross-case archive search is not supported.
- `knowledge_base`: advisory Knowledge Base grounding used by chat.

## Chat Modes

Supported mode:

| Mode | Backend behavior |
|------|------------------|
| `selected_case` | Search the pinned case and configured Knowledge Base context; requires `selected_case_id` |

Chat is read-only. It must return `unknown` or no-match when retrieval is weak.
General technology / TTP fallback remains available when
`CASE_QA_GENERAL_KNOWLEDGE_ENABLED=true`.

Portal chat synthesis should use the existing local LLM configuration
(`LLM_API_URL`, `LLM_API_TOKEN`, `LLM_MODEL_NAME`, `LLM_TIMEOUT`) and a bounded
prompt assembled from retrieved sources. Do not introduce a separate chatbot
model config in v1.

### Chat Retrieval Contract

Embed the analyst question with `CASE_QA_EMBEDDING_MODEL`, which defaults to the
existing RAG embedding model. Retrieve archive chunks with hybrid search:

1. Pull lexical candidates from `case_chunks.text` with Postgres full-text search
   up to `CASE_QA_LEXICAL_TOP_K`.
2. Pull vector candidates with pgvector similarity up to
   `CASE_QA_VECTOR_TOP_K`.
3. Merge candidates with reciprocal-rank fusion using `CASE_QA_RRF_K`.
4. Deduplicate by `chunk_id`.
5. Apply mode-specific lane rules.
6. Trim to `CASE_QA_MAX_CHUNKS_PER_LANE`, `CASE_QA_MAX_TOTAL_CHUNKS`, and
   `CASE_QA_CONTEXT_BUDGET_CHARS`.

Mode-specific retrieval:

- `selected_case`: retrieve chunks from `selected_case_id`, then append
  configured Knowledge Base context as `knowledge_base`.

When chat history is disabled, ignore incoming `session_id` and return
`session_id=null`. When `CASE_QA_CHAT_HISTORY_ENABLED=true`, persist bounded
user/assistant transcript rows in `chat_messages`, return the active
`session_id`, and enforce `CASE_QA_MAX_MESSAGES_PER_SESSION`,
`CASE_QA_MAX_STORED_MESSAGE_BYTES`, and `CASE_QA_CHAT_HISTORY_RETENTION_DAYS`.
Prior chat history is not used as retrieval memory; answers still come only from
case archive and Knowledge Base sources.

## Failure And Retry Contract

When `CASE_ARCHIVE_ENABLED=true`:

- Retry transient Postgres connection/timeout errors up to
  `CASE_ARCHIVE_WRITE_MAX_ATTEMPTS`.
- Do not retry schema errors, validation errors, malformed case records, or
  invalid config.
- If case archive write still fails after retries, log the failure and continue
  moving the input through the normal processed path. Archive identity conflicts
  remain hard failures because they indicate a deterministic-id safety violation.
- Optional markdown/HTML may exist even when the archive write is deferred.
- If case insert succeeds but chunk creation fails, keep the case row and set
  `retrieval_status='failed'`; continue moving the input through the normal
  processed path.
- Portal chat must not answer from model memory when retrieval fails.

Write ordering for the analyzer:

1. Build the final `llm_response` after enrichment, interpretation, and optional
   ServiceNow status insertion.
2. Generate existing markdown/HTML compatibility artifacts when enabled.
3. Write the Postgres case row with any report paths that exist.
4. Build case chunks.
5. Move the input to processed unless analysis itself failed or a hard archive
   identity conflict occurred.

If step 3 fails after markdown/HTML was written, the failure is visible in logs
and should be remediated through replay/backfill rather than by quarantining a
valid source alert.

## Backfill Contract

Add a one-time operator command later in the diff sequence.

Backfill rules:

- Prefer original processed notables plus structured analysis artifacts.
- Complete backfill case: original alert plus structured analysis.
- Incomplete backfill case: missing alert or missing structured analysis.
- Markdown-only historical reports may be imported as `legacy_summary` with
  `source_completeness='markdown_only'`.
- Backfill is idempotent by `case_id`.
- Backfill supports dry-run and bounded batch size.
- Execute mode must fail closed unless `CASE_ARCHIVE_ENABLED=true` and an
  explicit config env file is supplied.
- Markdown-only `legacy_summary` imports are not indexed for retrieval in v1.
  Chunk rebuild runs only for native cases with structured alert/analysis data.

## Portal API Contract

FastAPI endpoints:

- `GET /health`
- `GET /ready`
- `GET /api/cases`
- `GET /api/cases/{case_id}`
- `POST /api/chat`

`POST /api/chat` is query transport only. It must not mutate cases or trigger
external actions.

### Authentication Header

V1 trusts `PORTAL_TRUSTED_USER_HEADER` only from nginx on loopback. Direct
FastAPI requests without the trusted header are accepted in local development
only when `PORTAL_BIND_HOST=127.0.0.1`; production nginx config must set the
header after basic auth succeeds.

### `GET /health` And `GET /ready`

`GET /health` is a liveness endpoint and should return `200` when the FastAPI
process is running.

`GET /ready` is a readiness endpoint and should check Postgres connectivity plus
required `notable_cases` tables. It returns `200` when ready and `503` when the
portal cannot serve case data.

### `GET /api/cases`

Query params:

- `limit`: optional integer, default `PORTAL_PAGE_SIZE`, max `100`.
- `cursor_processed_at`, `cursor_case_id`: optional cursor pair for the next page; both are required when either is present.
- `start`: optional ISO-8601 timestamp filter on `processed_at`.
- `end`: optional ISO-8601 timestamp filter on `processed_at`.
- `verdict`: optional exact filter.
- `search_name`: optional partial alert-name filter.

Response `200`:

```json
{
  "items": [
    {
      "case_id": "case-123",
      "processed_at": "2026-06-04T00:00:00Z",
      "expires_at": "2026-09-02T00:00:00Z",
      "verdict": "likely_malicious",
      "confidence": 0.72,
      "search_name": "Suspicious PowerShell",
      "retrieval_status": "ready",
      "source_completeness": "complete"
    }
  ],
  "limit": 50,
  "has_more": false,
  "next_cursor": null
}
```

Invalid query params return `400`.

### `GET /api/cases/{case_id}`

Response `200` returns canonical case detail:

```json
{
  "case_id": "case-123",
  "metadata": {
    "processed_at": "2026-06-04T00:00:00Z",
    "expires_at": "2026-09-02T00:00:00Z",
    "retrieval_status": "ready",
    "source_completeness": "complete"
  },
  "alert_payload": {},
  "analysis": {},
  "report_md_path": null,
  "report_html_path": null
}
```

Unknown cases return `404`.

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

Response `200`:

```json
{
  "answer": "The retained evidence shows ...",
  "answer_status": "answered",
  "session_id": null
}
```

Weak retrieval returns `200` with `answer_status="unknown"` and an answer that
states the archive did not contain enough grounded context. Action requests
return `200` with `answer_status="refused"`. Invalid mode, oversized question,
or missing required `selected_case_id` return `400`. Unknown `selected_case_id`
values return `404` with `detail="Case not found."` before retrieval runs.

The production UI is the React analyst portal served by nginx. FastAPI serves
the portal API and health/readiness probes behind the reverse proxy.

## Networking Contract

Use nginx for v1.

Default:

```env
PORTAL_BIND_HOST=127.0.0.1
PORTAL_PORT=8080
```

Request path:

```text
analyst browser
-> https://notable-portal.<internal-domain>
-> nginx TCP 443
-> http://127.0.0.1:8080 FastAPI/Uvicorn
-> Postgres notable_cases schema
```

Nginx handles TLS, basic auth for the first documented path, request size
limits, access logs, and proxying.

## Postgres Operations Contract

Use separate database roles even when they point at the same Postgres database:

- `notable_analyzer`: read/write on `notable_cases.cases` and
  `notable_cases.case_chunks`; no write access to chat tables unless chat
  history is enabled.
- `notable_portal`: read-only on `notable_cases.cases` and
  `notable_cases.case_chunks`; read/write on chat tables only when
  `CASE_QA_CHAT_HISTORY_ENABLED=true`.
- Migration/operator role: owns schema migrations and grants privileges; not
  used by the long-running analyzer or portal service.

Migration verification must check:

- `vector` extension exists.
- `notable_cases` schema exists.
- All required tables, constraints, and indexes exist.
- `case_chunks.embedding` dimensions match `CASE_QA_VECTOR_DIMENSIONS`.
- Analyzer and portal roles have only the intended privileges.

Retention deletes expired rows from `notable_cases.cases` where
`expires_at < now()` in batches no larger than
`CASE_RETENTION_DELETE_BATCH_SIZE`. Chunk deletion relies on `ON DELETE CASCADE`.
Chat history retention deletes expired `chat_sessions`, also relying on cascade
for messages. Run retention from the existing retention loop or a documented
operator command; do not make retention depend on portal traffic.

Vector index posture for v1:

- The schema must work without a vector index for small pilot archives.
- The operations doc must include the recommended pgvector index command once
  corpus size and Postgres/pgvector version are known.
- Adding or changing a vector index must not change API behavior.

## Documentation Contract

Diff 6 must add `docs/operations/ANALYST_PORTAL_OPERATIONS.md` and update
`docs/README.md`. The operations doc is part of the delivery contract, not an
optional follow-up.

It must cover:

- How to enable and disable `analyst_portal`, including required env vars,
  capability profile behavior, and rollback to `CASE_ARCHIVE_ENABLED=false`.
- Systemd service setup for the portal, expected process owner, restart
  behavior, log locations, and local bind address.
- Nginx setup for internal DNS, TLS, basic auth, request size limits, trusted
  user header forwarding, and proxying to loopback FastAPI.
- Health checks: `GET /health` for liveness and `GET /ready` for Postgres-backed
  readiness.
- Database setup and maintenance: migrations, role grants, privilege checks,
  schema verification, backup/restore expectations, retention, and expired-case
  cleanup.
- Chunk maintenance: manual rebuild script usage, dry-run behavior, one-case vs
  all-case rebuilds, stale chunk symptoms, and embedding-dimension migration
  warnings.
- Backfill runbook: dry-run, execute, idempotency, markdown-only legacy behavior,
  retry/rollback expectations, and operator review points.
- Chatbot behavior: supported modes, weak-retrieval
  `unknown` behavior, action refusal behavior, and the read-only boundary.
- Troubleshooting: Postgres unavailable, migration mismatch, embedding failures,
  chunk rebuild failures, auth/header issues, stale chunks, and portal service
  startup failures.
- Security/admin notes: all authenticated analysts can see all retained cases,
  portal is read-only, nginx terminates TLS/auth for v1, and portal chat must not
  trigger Splunk, ServiceNow, SOAR, or remediation actions.

## Planned Files

### Runtime Code

- `src/llm_notable_analysis_onprem_systemd/onprem_service/case_store.py`
- `src/llm_notable_analysis_onprem_systemd/onprem_service/case_index.py`
- `src/llm_notable_analysis_onprem_systemd/onprem_service/case_search.py`
- `src/llm_notable_analysis_onprem_systemd/onprem_service/portal_app.py`
- `scripts/rebuild_case_chunks.py`
- `scripts/backfill_case_archive.py`
- `deploy/postgres/notable_cases_schema.sql`

### Deployment And Docs

- `deploy/systemd/notable-portal.service`
- `deploy/nginx/notable-portal.conf`
- `docs/operations/ANALYST_PORTAL_OPERATIONS.md`
- `docs/README.md`

### Tests

- `tests/onprem_service/test_case_store.py`
- `tests/onprem_service/test_case_index.py`
- `tests/onprem_service/test_case_search.py`
- `tests/onprem_service/test_portal_app.py`
- `tests/onprem_service/test_case_archive_backfill.py`

## Dependency Plan

Existing dependencies already include `psycopg[binary]` and `pgvector`.

When implementing the portal diff, add:

- `fastapi`
- `uvicorn`

Use package-manager install, not hand-written versions, when coding starts.

## Diff Plan

### Branch And Merge Workflow

Implement each diff on its own feature branch and merge it to `main` before
starting the next diff. Do not stack all six diffs on one long-lived branch.

Required sequence:

1. Start from up-to-date `main`.
2. Create a focused feature branch for the current diff, for example
   `feature/analyst-portal-diff-1-case-store`.
3. Implement only that diff's scope.
4. Run that diff's targeted tests plus the primary unit command.
5. Open/review/merge that feature branch into `main`.
6. Update local `main`.
7. Create the next diff branch from the updated `main`.

Each branch must preserve the current default behavior unless that diff
explicitly enables a new capability behind config. If a diff cannot meet its
acceptance criteria, stop on that branch and fix it before starting the next
diff.

### Diff 1: Config, DDL, And Case Store

Objective:

- Add portal/archive config.
- Add migration SQL or migration helper for `notable_cases`.
- Add `case_store.py`.
- Add `deploy/postgres/notable_cases_schema.sql`.
- Wire analyzer to write a case row after successful analysis when
  `CASE_ARCHIVE_ENABLED=true`.

Files:

- `config.py`
- `config.env.example`
- `case_store.py`
- `deploy/postgres/notable_cases_schema.sql`
- `onprem_main.py`
- `onprem_main_nonsdk.py`
- tests for config and case-store writes

Acceptance criteria:

- `CASE_ARCHIVE_ENABLED=false` preserves current behavior.
- When enabled, successful analysis inserts one `cases` row.
- Replaying the same source identity updates the same `case_id` and replaces
  derived chunks.
- A colliding `case_id` with a different source identity fails visibly.
- `poc_unstructured_output` stores a visible `not_indexed` case row and does not
  build chunks from raw model output.
- Scalar filter columns follow the extraction and coercion rules in this spec.
- Postgres transient write failures retry.
- Non-retryable failures fail visibly.

### Diff 2: Chunk Builder And Manual Rebuild Script

Objective:

- Add deterministic chunk builder from JSON fields.
- Add `case_search.py` insert/rebuild behavior.
- Add `scripts/rebuild_case_chunks.py`.

Acceptance criteria:

- Chunks cover every initial section listed in this spec.
- Stored chunk lanes are limited to `alert_payload`, `case_analysis`, and
  `legacy_summary`.
- Every chunk includes section and field-path metadata for retrieval.
- Rebuild script can dry-run and execute for one case or all cases.

### Diff 3: Case Index And Retention

Objective:

- Add `case_index.py`.
- Add list/detail queries.
- Extend retention to delete expired case rows and chunks.

Acceptance criteria:

- Cases list by `processed_at` descending.
- Filters support date range, verdict, and search name.
- Expired case delete cascades chunks.

### Diff 4: FastAPI Portal API And React UI

Objective:

- Add `portal_app.py`.
- Add React analyst portal served by nginx.
- Add systemd service.

Acceptance criteria:

- `GET /health` works.
- `GET /ready` validates Postgres readiness and returns `503` when required
  case tables are unavailable.
- `GET /api/cases` returns paginated cases.
- `GET /api/cases/{case_id}` returns canonical case detail.
- Invalid filters return `400`; unknown case IDs return `404`.
- Portal uses the trusted user header only as documented behind nginx.
- No mutating case endpoints exist.

### Diff 5: Chat Retrieval And Guardrails

Objective:

- Add `POST /api/chat`.
- Implement chat modes.
- Retrieve from selected case plus Knowledge Base, or all-case archive chunks
  plus Knowledge Base.

Acceptance criteria:

- Chat answers return `answer` and `answer_status` only.
- Archive retrieval uses the hybrid lexical/vector/RRF contract and configured
  retrieval limits.
- Weak retrieval returns `unknown` or no-match.
- Action requests are refused.
- Chat does not call Splunk, ServiceNow, SOAR, or external action systems.

### Diff 6: Backfill And Operations Docs

Objective:

- Add one-time backfill script.
- Add nginx config example.
- Add operations docs.
- Update docs index links.

Acceptance criteria:

- Backfill dry-run reports what would be imported.
- Backfill marks markdown-only imports as incomplete legacy summaries.
- Backfill IDs use the `backfill:<sha256-prefix>` rule and are idempotent.
- Nginx docs describe internal DNS, TLS, basic auth, and proxying to loopback.
- Operations docs cover enable/disable, service management, DB maintenance,
  chunk rebuild, backfill, health checks, troubleshooting, and security/admin
  notes from the Documentation Contract.

## Verification Commands

Primary unit command:

```bash
python -m unittest discover -s llm_notable_analysis_onprem_systemd/tests -v
```

Targeted commands should be added per diff once test files exist.

## Deferred Decisions After V1

These do not block the v1 coding sequence:

- Whether markdown remains a long-term compatibility output after portal
  adoption. V1 preserves the current markdown/HTML settings and does not make
  portal/chat depend on filesystem artifacts.
- Whether future chunking should embed every raw alert field. V1 stores the full
  alert JSONB but embeds only selected high-value alert fields plus the full
  validated analysis.
- Whether to add an SSO-header nginx example. V1 documents basic auth first and
  keeps `PORTAL_TRUSTED_USER_HEADER` for a later proxy-auth integration.

