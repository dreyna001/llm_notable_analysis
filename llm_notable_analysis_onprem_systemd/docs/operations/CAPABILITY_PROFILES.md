# Capability Profiles

Capability profiles are the operator-facing way to enable supported feature
bundles. Use `CAPABILITY_PROFILES` first, then set only the endpoint, path,
secret, and tuning values needed by that profile.

Low-level `*_ENABLED` flags remain supported for legacy lab configs when no
selected profile controls that capability, but they are no longer the preferred
operator workflow. When a selected profile controls a capability, the profile
takes precedence; remove the profile to turn that capability off.

## Supported Profiles

| Profile | Enables | Risk class |
|---------|---------|------------|
| `core` | File-drop ingest, base LLM analysis, markdown reports, processed/quarantine movement. | Local read/process/write of runtime files. |
| `html_reports` | Static HTML reports next to markdown reports. | Local report artifact only. |
| `rag` | General SOC RAG context in the main analysis prompt. | Read-only retrieval/advisory context. |
| `spl_readonly` | SPL query generation and bounded read-only Splunk investigation execution. | Read-only external queries. |
| `elastic_readonly` | Elasticsearch Query DSL generation and bounded read-only `_search` execution. | Read-only external queries. |
| `ticket_draft` | ServiceNow incident draft payloads in reports. | Local draft only; no ServiceNow POST. |
| `action_gated` | Splunk notable writeback, ServiceNow draft/create, required ServiceNow approval, and side-effect idempotency. | External write/action path. |
| `analyst_portal` | Postgres case archive writes, read-only portal service, Case Q&A, and global case archive retrieval. | Local case persistence and read-only archive retrieval. |

Profiles are additive. `core` is automatically included when omitted.
Profiles may be separated with commas or semicolons.

```bash
CAPABILITY_PROFILES=core
CAPABILITY_PROFILES=core,html_reports,rag
CAPABILITY_PROFILES=core,rag,spl_readonly
CAPABILITY_PROFILES=core,rag,elastic_readonly
CAPABILITY_PROFILES=core,ticket_draft
CAPABILITY_PROFILES=core,action_gated
CAPABILITY_PROFILES=core,analyst_portal
```

## Operator Workflow

1. Start with `CAPABILITY_PROFILES=core`.
2. Add one profile at a time in a lab or non-production scope.
3. Configure required endpoint, credential, path, and tuning values for the
   selected profile.
4. Run the relevant smoke test or focused validation from the operations guide.
5. Promote the same profile list after ownership, approval boundaries, and
   rollback expectations are documented.

## Profile Details

### `html_reports`

Use when operators want static HTML dashboards in addition to markdown reports.
No external system is contacted.

Primary follow-up values:

- `REPORT_DIR`
- retention settings for report/archive lifecycle

### `rag`

Use after the general knowledge base source documents are curated and owned.
Retrieved content is advisory context, not direct alert evidence.

Primary follow-up values:

- `RAG_BACKEND`
- `RAG_FAIL_CLOSED`
- `RAG_POSTGRES_*` or `RAG_SQLITE_PATH` / `RAG_FAISS_PATH`
- embedding, rerank, snippet, and budget knobs

### `spl_readonly`

Use when Splunk owners approve generated SPL and bounded read-only execution.
This profile does not enable Splunk notable writeback.

Primary follow-up values:

- `INVESTIGATION_QUERY_EXECUTOR`
- `SPLUNK_SEARCH_ALLOWED_INDEXES`
- `SPLUNK_SEARCH_ALLOWED_COMMANDS`
- `SPLUNK_SEARCH_DENIED_COMMANDS`
- `SPLUNK_SEARCH_MAX_TIME_RANGE`
- `SPLUNK_SEARCH_MAX_ROWS`
- `SPLUNK_SEARCH_TIMEOUT_SECONDS`
- optional `SPL_QUERY_RAG_*` values for dedicated SPL grounding

`spl_readonly` and `elastic_readonly` are mutually exclusive for v1. Choose one
active read-only investigation backend per deployment.

### `elastic_readonly`

Use when Elasticsearch owners approve generated Query DSL and bounded read-only
`_search` execution. This profile does not enable writeback or action-taking.

Primary follow-up values:

- `INVESTIGATION_QUERY_BACKEND=elasticsearch`
- `ELASTICSEARCH_BASE_URL`
- `ELASTICSEARCH_API_KEY`
- `ELASTICSEARCH_INDEX_ALLOWLIST`
- `ELASTICSEARCH_ALLOW_WILDCARD_INDEXES`
- `ELASTICSEARCH_TIMESTAMP_FIELD`
- `ELASTICSEARCH_ALLOWED_FIELDS`
- `ELASTICSEARCH_MAX_TIME_RANGE`
- `ELASTICSEARCH_MAX_ROWS`
- `ELASTICSEARCH_TIMEOUT_SECONDS`
- `ELASTICSEARCH_CA_BUNDLE`
- optional `ELASTICSEARCH_GROUNDING_*` values for dedicated Elastic grounding

`spl_readonly` and `elastic_readonly` are mutually exclusive for v1. Choose one
active read-only investigation backend per deployment.

When `elastic_readonly` enables execution, `ELASTICSEARCH_BASE_URL` must be an
HTTPS URL, `ELASTICSEARCH_API_KEY` must be set, and
`ELASTICSEARCH_INDEX_ALLOWLIST` plus `ELASTICSEARCH_ALLOWED_FIELDS` must be
configured before startup succeeds.

### `ticket_draft`

Use when operators want ServiceNow incident drafts rendered into reports without
creating incidents.

Primary follow-up values:

- `SERVICENOW_ASSIGNMENT_GROUP`

### `action_gated`

Use only after owners approve external write/action behavior. This profile
enables Splunk notable writeback and ServiceNow incident create. ServiceNow
create remains approval-gated by default through the incoming
`servicenow_create_approval` object.

Side-effect idempotency is enabled by this profile. The ledger applies only to
external side effects:

- Splunk notable update
- ServiceNow incident create

It does not deduplicate local report files, input movement, read-only Splunk
queries, or LLM calls.

Idempotency requires a specific key. Splunk writeback uses `finding_id`.
ServiceNow incident create uses the draft `correlation_id` or
`correlation_display`; create is rejected when idempotency is enabled and only a
generic or missing key is available.

The idempotency directory must be absolute, writable by the analyzer service
user, and protected with the same host-level permissions as other runtime state.
Markers are pruned by retention housekeeping after
`SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS`.

Primary follow-up values:

- `SIDE_EFFECT_IDEMPOTENCY_DIR`
- `SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS`
- `SPLUNK_BASE_URL`
- `SPLUNK_NOTABLE_UPDATE_PATH`
- `SPLUNK_API_TOKEN`
- `SPLUNK_CA_BUNDLE`
- `SERVICENOW_BASE_URL`
- `SERVICENOW_CREATE_PATH`
- `SERVICENOW_API_TOKEN`
- `SERVICENOW_ASSIGNMENT_GROUP`
- `SERVICENOW_TIMEOUT_SECONDS`

### `analyst_portal`

Use when operators are ready to persist validated cases to Postgres and expose
the read-only analyst portal and archive-backed Case Q&A workflow.

This profile enables:

- `CASE_ARCHIVE_ENABLED`
- `PORTAL_ENABLED`
- `CASE_QA_ENABLED`
- `CASE_QA_GLOBAL_RETRIEVAL_ENABLED`

It does not enable `HTML_REPORT_ENABLED`. Add the `html_reports` profile
separately when static HTML artifacts are required.

Primary follow-up values:

- `CASE_POSTGRES_DSN`
- `CASE_POSTGRES_SCHEMA`
- `CASE_RETENTION_DAYS`
- `PORTAL_BIND_HOST`
- `PORTAL_PAGE_SIZE`
- `CASE_QA_MAX_RETRIEVED_CASES`
- `CASE_QA_MAX_CHUNKS_PER_LANE`
- `CASE_QA_MAX_TOTAL_CHUNKS`

## Advanced Overrides

Use low-level flags only for legacy or lab configs when the capability is not
controlled by a selected profile.
Examples:

- enabling `HTML_REPORT_ENABLED` without selecting `html_reports` in a local lab
- enabling `SPL_QUERY_RAG_ENABLED` after the dedicated SPL KB is curated
- enabling `ELASTICSEARCH_GROUNDING_ENABLED` after the dedicated Elastic KB is curated

Unknown profile names fail startup validation. Invalid boolean overrides also
fail startup validation.

## Related Docs

- [`RAG_OPERATIONS.md`](RAG_OPERATIONS.md)
- [`SPL_OPERATIONS.md`](SPL_OPERATIONS.md)
- [`ELASTICSEARCH_OPERATIONS.md`](ELASTICSEARCH_OPERATIONS.md)
- [`SPLUNK_WRITEBACK_OPERATIONS.md`](SPLUNK_WRITEBACK_OPERATIONS.md)
- [`SERVICENOW_OPERATIONS.md`](SERVICENOW_OPERATIONS.md)
- [`FILE_DROP_AND_RETENTION_OPERATIONS.md`](FILE_DROP_AND_RETENTION_OPERATIONS.md)
- [`../../config.env.example`](../../config.env.example)
