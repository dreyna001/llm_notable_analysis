# Capability Profiles

Capability profiles are the operator-facing way to enable supported feature
bundles. Set `CAPABILITY_PROFILES` first, then configure only the endpoint,
path, secret, and tuning values required by those profiles in
[`config.env.example`](../../../config.env.example) (host path:
`/etc/notable-analyzer/config.env`). The analyst portal process uses the narrower
[`config.portal.env.example`](../../../config.portal.env.example).

Low-level `*_ENABLED` flags remain supported for legacy lab configs when no
selected profile controls that capability. When a selected profile controls a
capability, the profile takes precedence; remove the profile to turn that
capability off.

## Supported Profiles

| Profile | Operator intent | Risk class |
|---------|-----------------|------------|
| `core` | File-drop ingest, base LLM analysis, markdown reports, processed/quarantine movement. Sets no feature flags. | Local read/process/write of runtime files. |
| `html_reports` | Static HTML reports next to markdown reports. | Local report artifact only. |
| `rag` | General SOC RAG context in the main analysis prompt. | Read-only retrieval/advisory context. |
| `spl_readonly` | SPL query generation and bounded read-only Splunk investigation execution. | Read-only external queries. |
| `elastic_readonly` | Elasticsearch Query DSL generation and bounded read-only `_search` execution. | Read-only external queries. |
| `ticket_draft` | ServiceNow incident draft payloads in reports. | Local draft only; no ServiceNow POST. |
| `action_gated` | Splunk notable writeback, ServiceNow draft/create, required create approval, and side-effect idempotency. | External write/action path. |
| `analyst_portal` | Postgres case archive writes, read-only portal service, and Case Q&A. | Local case persistence and read-only archive retrieval. |

Profiles are additive. `core` is automatically included when omitted.
Profiles may be separated with commas or semicolons. Startup rejects unknown
profile names and rejects selecting both `spl_readonly` and `elastic_readonly`.

```bash
CAPABILITY_PROFILES=core
CAPABILITY_PROFILES=core,html_reports,rag
CAPABILITY_PROFILES=core,rag,spl_readonly
CAPABILITY_PROFILES=core,rag,elastic_readonly
CAPABILITY_PROFILES=core,ticket_draft
CAPABILITY_PROFILES=core,action_gated
CAPABILITY_PROFILES=core,analyst_portal
```

## Profile-to-Flag Mapping

Authoritative mapping from `onprem_service/config.py` (`_CAPABILITY_PROFILE_FLAGS`
and backend selection in `_profile_flag_defaults`):

| Profile | Flags set to `true` | Derived settings |
|---------|---------------------|------------------|
| `core` | _(none)_ | — |
| `html_reports` | `HTML_REPORT_ENABLED` | — |
| `rag` | `RAG_ENABLED` | — |
| `spl_readonly` | `SPL_QUERY_GENERATION_ENABLED`, `INVESTIGATION_QUERY_EXECUTION_ENABLED` | `INVESTIGATION_QUERY_BACKEND=splunk` |
| `elastic_readonly` | `ELASTIC_QUERY_GENERATION_ENABLED`, `INVESTIGATION_QUERY_EXECUTION_ENABLED` | `INVESTIGATION_QUERY_BACKEND=elasticsearch` |
| `ticket_draft` | `SERVICENOW_DRAFT_ENABLED` | — |
| `action_gated` | `SPLUNK_SINK_ENABLED`, `SERVICENOW_DRAFT_ENABLED`, `SERVICENOW_CREATE_ENABLED`, `SERVICENOW_CREATE_REQUIRES_APPROVAL`, `SIDE_EFFECT_IDEMPOTENCY_ENABLED` | — |
| `analyst_portal` | `CASE_ARCHIVE_ENABLED`, `PORTAL_ENABLED`, `CASE_QA_ENABLED` | — |

`action_gated` includes draft behavior (`SERVICENOW_DRAFT_ENABLED`); `ticket_draft`
is the draft-only bundle when create/writeback are not approved.

Flags not controlled by any profile (legacy/lab only unless noted):

- `SPL_QUERY_RAG_ENABLED`
- `ELASTICSEARCH_GROUNDING_ENABLED`
- `QUERY_RESULT_INTERPRETATION_ENABLED`
- `CASE_QA_CHAT_HISTORY_ENABLED` (default `false`; not enabled by `analyst_portal`)
- `CONCURRENCY_ENABLED`

## Operator Workflow

1. Start with `CAPABILITY_PROFILES=core`.
2. Add one profile at a time in a lab or non-production scope.
3. Configure required endpoint, credential, path, and tuning values for the
   selected profile.
4. Run the relevant smoke test or focused validation from the operations guide.
5. Promote the same profile list after ownership, approval boundaries, and
   rollback expectations are documented.

## Profile Details

### `core`

Baseline service behavior. No profile flags are set. Requires file-drop paths,
LLM endpoint settings, and MITRE data path from `config.env.example`.

### `html_reports`

Static HTML dashboards in addition to markdown reports. No external system is
contacted.

Primary follow-up values: `REPORT_DIR`, report/archive retention settings.

### `rag`

Use after the general knowledge base source documents are curated and owned.
Retrieved content is advisory context, not direct alert evidence.

Primary follow-up values: `RAG_BACKEND`, `RAG_FAIL_CLOSED`, `RAG_POSTGRES_*` or
`RAG_SQLITE_PATH` / `RAG_FAISS_PATH`, embedding/rerank/snippet/budget knobs.

### `spl_readonly`

Bounded read-only Splunk investigation. Does not enable Splunk notable writeback
(`SPLUNK_SINK_ENABLED`). Profile sets `INVESTIGATION_QUERY_BACKEND=splunk`; do
not also select `elastic_readonly`.

Primary follow-up values: `INVESTIGATION_QUERY_EXECUTOR`, `SPLUNK_SEARCH_*`
allowlists and bounds, optional `SPL_QUERY_RAG_*` for dedicated SPL grounding.

### `elastic_readonly`

Bounded read-only Elasticsearch `_search`. Does not enable writeback or
action-taking. Profile sets `INVESTIGATION_QUERY_BACKEND=elasticsearch`; do not
also select `spl_readonly`.

When execution is enabled, startup requires HTTPS `ELASTICSEARCH_BASE_URL`,
`ELASTICSEARCH_API_KEY`, `ELASTICSEARCH_INDEX_ALLOWLIST`, and
`ELASTICSEARCH_ALLOWED_FIELDS` (even when `ELASTICSEARCH_GROUNDING_ENABLED=true`).

Primary follow-up values: `ELASTICSEARCH_BASE_URL`, `ELASTICSEARCH_API_KEY`,
`ELASTICSEARCH_INDEX_ALLOWLIST`, `ELASTICSEARCH_ALLOW_WILDCARD_INDEXES`,
`ELASTICSEARCH_TIMESTAMP_FIELD`, `ELASTICSEARCH_ALLOWED_FIELDS`,
`ELASTICSEARCH_MAX_TIME_RANGE`, `ELASTICSEARCH_MAX_ROWS`,
`ELASTICSEARCH_TIMEOUT_SECONDS`, `ELASTICSEARCH_CA_BUNDLE`, optional
`ELASTICSEARCH_GROUNDING_*`.

### `ticket_draft`

ServiceNow incident drafts in reports without incident create or POST.

Primary follow-up values: `SERVICENOW_ASSIGNMENT_GROUP`.

### `action_gated`

Use only after owners approve external write/action behavior. Enables Splunk
notable writeback, ServiceNow draft and create, mandatory create approval
(`SERVICENOW_CREATE_REQUIRES_APPROVAL=true` via profile), and side-effect
idempotency. ServiceNow create remains gated on payload
`servicenow_create_approval` metadata.

Idempotency applies only to external side effects (Splunk notable update,
ServiceNow incident create). It does not deduplicate local reports, input
movement, read-only queries, or LLM calls. Requires a specific key:
`finding_id` for Splunk writeback; draft `correlation_id` or
`correlation_display` for ServiceNow create (create rejected when idempotency is
enabled and the key is generic or missing). Markers live under
`SIDE_EFFECT_IDEMPOTENCY_DIR` and are pruned after
`SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS`.

Primary follow-up values: `SIDE_EFFECT_IDEMPOTENCY_DIR`,
`SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS`, `SPLUNK_BASE_URL`,
`SPLUNK_NOTABLE_UPDATE_PATH`, `SPLUNK_API_TOKEN`, `SPLUNK_CA_BUNDLE`,
`SERVICENOW_BASE_URL`, `SERVICENOW_CREATE_PATH`, `SERVICENOW_API_TOKEN`,
`SERVICENOW_ASSIGNMENT_GROUP`, `SERVICENOW_TIMEOUT_SECONDS`.

### `analyst_portal`

Persist validated cases to Postgres and expose the read-only analyst portal with
archive-backed Case Q&A. Does not enable `HTML_REPORT_ENABLED`; add
`html_reports` separately when static HTML artifacts are required. Portal chat
requires a pinned case. `CASE_QA_CHAT_HISTORY_ENABLED` stays `false` unless
explicitly set. `PORTAL_PROXY_SECRET` is required at startup when
`PORTAL_ENABLED=true`.

Primary follow-up values: `CASE_POSTGRES_DSN`, `CASE_POSTGRES_SCHEMA`,
`CASE_RETENTION_DAYS`, `PORTAL_BIND_HOST`, `PORTAL_PORT`, `PORTAL_PAGE_SIZE`,
`PORTAL_PROXY_SECRET`, `PORTAL_PROXY_SECRET_HEADER`, `CASE_QA_MAX_CHUNKS_PER_LANE`,
`CASE_QA_MAX_TOTAL_CHUNKS`. Portal-only deployments may use
`config.portal.env.example` with `CAPABILITY_PROFILES=core,analyst_portal`.

## Advanced Overrides

Use low-level flags only when the capability is not controlled by a selected
profile. Profile-controlled flags (see mapping table): `HTML_REPORT_ENABLED`,
`RAG_ENABLED`, `SPL_QUERY_GENERATION_ENABLED`,
`INVESTIGATION_QUERY_EXECUTION_ENABLED`, `INVESTIGATION_QUERY_BACKEND`,
`ELASTIC_QUERY_GENERATION_ENABLED`, `SERVICENOW_DRAFT_ENABLED`,
`SPLUNK_SINK_ENABLED`, `SERVICENOW_CREATE_ENABLED`,
`SERVICENOW_CREATE_REQUIRES_APPROVAL`, `SIDE_EFFECT_IDEMPOTENCY_ENABLED`,
`CASE_ARCHIVE_ENABLED`, `PORTAL_ENABLED`, `CASE_QA_ENABLED`.

Examples of safe legacy-only overrides:

- `SPL_QUERY_RAG_ENABLED` after the dedicated SPL KB is curated
- `ELASTICSEARCH_GROUNDING_ENABLED` after the dedicated Elastic KB is curated
- `QUERY_RESULT_INTERPRETATION_ENABLED` for optional query-result LLM synthesis
- `CASE_QA_CHAT_HISTORY_ENABLED` for persisted portal chat transcripts

Unknown profile names and invalid boolean overrides fail startup validation.

## Related Docs

- [`RAG_OPERATIONS.md`](../rag/RAG_OPERATIONS.md)
- [`SPL_OPERATIONS.md`](../investigation/SPL_OPERATIONS.md)
- [`ELASTICSEARCH_OPERATIONS.md`](../investigation/ELASTICSEARCH_OPERATIONS.md)
- [`SPLUNK_WRITEBACK_OPERATIONS.md`](../integrations/SPLUNK_WRITEBACK_OPERATIONS.md)
- [`SERVICENOW_OPERATIONS.md`](../integrations/SERVICENOW_OPERATIONS.md)
- [`FILE_DROP_AND_RETENTION_OPERATIONS.md`](FILE_DROP_AND_RETENTION_OPERATIONS.md)
