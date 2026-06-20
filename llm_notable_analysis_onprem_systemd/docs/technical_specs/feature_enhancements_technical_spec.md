# Feature Enhancements Technical Spec

## Status

Normative implementation contract for optional investigation, enrichment,
interpretation, ServiceNow, HTML reports, and side-effect idempotency in
`llm_notable_analysis_onprem_systemd`. Modules listed below are **shipped**;
this spec wins over older planning notes when they conflict.

Operator runbooks: [`docs/operations/README.md`](../operations/README.md).

## 1. Purpose

Preserve the default file-drop analysis path while adding optional:

- Splunk SPL query generation and read-only investigation (REST or MCP)
- Elasticsearch Query DSL generation and read-only `_search` execution (REST only)
- Deterministic query-result enrichment and optional bounded LLM interpretation
- ServiceNow incident draft/create with explicit approval
- Static HTML dashboard reports (`html_reports` profile)
- File-backed idempotency for external side effects (`action_gated` profile)

Parity is required in `onprem_main.py` and `onprem_main_nonsdk.py`.

## 2. Scope

### In scope (shipped)

- `spl_query_generation.py`, `spl_query_grounding.py`, `splunk_investigation.py`
- `elastic_query_generation.py`, `elasticsearch_query_grounding.py`, `elasticsearch_investigation.py`
- `query_result_enrichment.py`, `query_result_interpretation.py`
- `servicenow.py`, `idempotency.py`, `sinks.py`, `html_generator.py`
- Capability profiles in `config.py` (`CAPABILITY_PROFILES`)
- Env contract in `config.env.example` and `config.py`
- Deterministic unit tests under `tests/onprem_service/`

### Out of scope

- **Gzip file-drop intake** — **planned on-prem** (not in `ingest.py`); **shipped in AWS**
  `s3_notable_pipeline` (`.json.gz` / `.txt.gz`, S3 `ContentEncoding: gzip`,
  `MAX_DECOMPRESSED_INPUT_BYTES`). See
  [on-prem file-drop ops](../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md)
  and
  [AWS file-drop ops](../../../s3_notable_pipeline/docs/operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md).
- Broad refactor of `local_llm_client.py`
- Separate `query_models.py`, `query_policy.py`, or `writeback_policy.py` modules
- Changing default RAG behavior or enabling new features by default
- Live Splunk, Elasticsearch, MCP, ServiceNow, or LLM calls in unit tests

## 3. Capability Profiles

Authoritative mapping lives in `config.py` (`_CAPABILITY_PROFILE_FLAGS`) and
[`CAPABILITY_PROFILES.md`](../operations/platform/CAPABILITY_PROFILES.md).

| Profile | Enables (summary) |
|---------|-------------------|
| `core` | Base file-drop path (no feature flags) |
| `html_reports` | `HTML_REPORT_ENABLED` |
| `rag` | `RAG_ENABLED` |
| `spl_readonly` | `SPL_QUERY_GENERATION_ENABLED`, `INVESTIGATION_QUERY_EXECUTION_ENABLED`, `INVESTIGATION_QUERY_BACKEND=splunk` |
| `elastic_readonly` | `ELASTIC_QUERY_GENERATION_ENABLED`, `INVESTIGATION_QUERY_EXECUTION_ENABLED`, `INVESTIGATION_QUERY_BACKEND=elasticsearch` |
| `ticket_draft` | `SERVICENOW_DRAFT_ENABLED` |
| `action_gated` | Splunk writeback, ServiceNow draft/create, create approval, `SIDE_EFFECT_IDEMPOTENCY_ENABLED` |
| `analyst_portal` | Case archive, portal, Case Q&A (separate from this block) |

Rules:

- `spl_readonly` and `elastic_readonly` are mutually exclusive.
- Profile-controlled flags override legacy direct env when the profile sets them.
- `SPL_QUERY_RAG_ENABLED`, `ELASTICSEARCH_GROUNDING_ENABLED`, and
  `QUERY_RESULT_INTERPRETATION_ENABLED` are **not** profile-controlled.

## 4. Baseline Assumptions

- Default ingest is plain `.json` / `.txt` file-drop (`INGEST_MODE=file_drop`).
- Splunk notable writeback (`SPLUNK_SINK_ENABLED`) is separate from read-only investigation.
- Query results are advisory; they must not populate `evidence_vs_inference.evidence`.
- ServiceNow create requires payload approval when `SERVICENOW_CREATE_REQUIRES_APPROVAL=true`.
- All new behavior is optional and off by default (`CAPABILITY_PROFILES=core`).

## 5. Module and File Contract

### Shipped modules

| Module | Responsibility |
|--------|----------------|
| `spl_query_generation.py` | SPL contract, validation, normalization, merge-by-position, prompt schema |
| `spl_query_grounding.py` | Postgres retrieval for `SPL_QUERY_GROUNDING_CONTEXT` |
| `splunk_investigation.py` | SPL policy validation, REST oneshot, MCP `run_search`, parallel fan-out |
| `elastic_query_generation.py` | Elastic Query DSL contract, validation, normalization, merge-by-position |
| `elasticsearch_query_grounding.py` | Postgres retrieval for Elastic grounding context |
| `elasticsearch_investigation.py` | DSL policy validation, HTTPS `_search`, process-wide concurrency guard |
| `query_result_enrichment.py` | Adds `query_result_section`; annotates hypotheses; no evidence mutation |
| `query_result_interpretation.py` | Bounded interpretation schema/validation; no score mutation |
| `servicenow.py` | Draft builder, approval gate, create POST, idempotent create |
| `idempotency.py` | File-backed side-effect reservations (`begin_side_effect`, markers, locks) |
| `sinks.py` | Markdown/HTML filesystem writes; Splunk notable update with idempotency |
| `html_generator.py` | Static HTML dashboard including query, interpretation, ServiceNow tabs |

### Orchestration and rendering

- `local_llm_client.py` / `local_llm_client_nonsdk.py` — transport, main analysis, optional second call for SPL or Elastic query fields, optional interpretation call, `LLM_STRUCTURED_OUTPUT_MODE` (`prompt_json` \| `tool_call`)
- `markdown_generator.py` — Query Results and Query Result Interpretation sections
- `onprem_main.py` / `onprem_main_nonsdk.py` — wiring below
- `config.py`, `config.env.example`

### Tests (required coverage areas)

`test_spl_query_generation.py`, `test_splunk_investigation.py`,
`test_elastic_query_generation.py`, `test_elasticsearch_investigation.py`,
`test_query_result_enrichment.py`, `test_query_result_interpretation.py`,
`test_servicenow.py`, `test_idempotency.py`, `test_html_generator.py`,
`test_markdown_generator.py`, `test_onprem_main_investigation.py`,
`test_onprem_main_servicenow.py`, `test_config_runtime_contract.py`.

Run:

```bash
python -m unittest discover -s llm_notable_analysis_onprem_systemd/tests/onprem_service -p "test*.py" -v
```

## 6. Runtime Config Contract

### 6.1 Shared investigation flags

```env
CAPABILITY_PROFILES=core
INVESTIGATION_QUERY_EXECUTION_ENABLED=false
INVESTIGATION_QUERY_BACKEND=splunk
INVESTIGATION_MAX_QUERIES_PER_ALERT=6
INVESTIGATION_MAX_CONCURRENT_QUERIES=6
QUERY_RESULT_INTERPRETATION_ENABLED=false
QUERY_RESULT_INTERPRETATION_CONTEXT_BUDGET_CHARS=4000
QUERY_RESULT_INTERPRETATION_MAX_SAMPLE_ROWS=3
QUERY_RESULT_INTERPRETATION_MAX_TOKENS=768
LLM_STRUCTURED_OUTPUT_MODE=prompt_json
```

Validation highlights:

- `INVESTIGATION_QUERY_BACKEND` must be `splunk` or `elasticsearch`.
- `INVESTIGATION_QUERY_EXECUTOR` must be `rest` or `mcp` (**Splunk only**; Elastic is REST-only).
- Positive integer bounds on concurrency, interpretation budgets, timeouts, max rows.
- Do **not** add `QUERY_RESULT_ENRICHMENT_ENABLED` (enrichment is deterministic whenever execution returns results).

### 6.2 Splunk (when `INVESTIGATION_QUERY_BACKEND=splunk`)

```env
SPL_QUERY_GENERATION_ENABLED=false
INVESTIGATION_QUERY_EXECUTOR=rest
SPLUNK_SEARCH_ENDPOINT_PATH=/services/search/jobs/oneshot
SPLUNK_SEARCH_ALLOWED_INDEXES=main,notable,risk
SPLUNK_SEARCH_ALLOWED_COMMANDS=search,stats,table,fields,where,head
SPLUNK_SEARCH_DENIED_COMMANDS=delete,collect,outputlookup,sendemail,map,rest,script,dbxquery
SPLUNK_SEARCH_MAX_TIME_RANGE=24h
SPLUNK_SEARCH_MAX_ROWS=100
SPLUNK_SEARCH_TIMEOUT_SECONDS=30
SPLUNK_MCP_TOOL_NAME=splunk_search
SPL_QUERY_RAG_ENABLED=false
SPL_QUERY_RAG_FAILURE_MODE=suppress
```

Splunk REST credentials (`SPLUNK_BASE_URL`, `SPLUNK_API_TOKEN`) are required for REST execution, not for generation-only mode.

Operator guide: [`SPL_OPERATIONS.md`](../operations/investigation/SPL_OPERATIONS.md).

### 6.3 Elasticsearch (when `INVESTIGATION_QUERY_BACKEND=elasticsearch`)

```env
ELASTIC_QUERY_GENERATION_ENABLED=false
ELASTICSEARCH_BASE_URL=
ELASTICSEARCH_API_KEY=
ELASTICSEARCH_INDEX_ALLOWLIST=
ELASTICSEARCH_ALLOW_WILDCARD_INDEXES=false
ELASTICSEARCH_TIMESTAMP_FIELD=@timestamp
ELASTICSEARCH_ALLOWED_FIELDS=
ELASTICSEARCH_GROUNDING_ENABLED=false
ELASTICSEARCH_GROUNDING_FAILURE_MODE=suppress
ELASTICSEARCH_MAX_TIME_RANGE=24h
ELASTICSEARCH_MAX_ROWS=100
ELASTICSEARCH_TIMEOUT_SECONDS=30
```

When generation or execution is enabled: non-empty `ELASTICSEARCH_INDEX_ALLOWLIST`.
When execution is enabled: HTTPS `ELASTICSEARCH_BASE_URL`, `ELASTICSEARCH_API_KEY`,
and non-empty `ELASTICSEARCH_ALLOWED_FIELDS` (unless grounding supplies field policy).

Operator guide: [`ELASTICSEARCH_OPERATIONS.md`](../operations/investigation/ELASTICSEARCH_OPERATIONS.md).

### 6.4 ServiceNow and side effects

```env
SERVICENOW_DRAFT_ENABLED=false
SERVICENOW_CREATE_ENABLED=false
SERVICENOW_CREATE_REQUIRES_APPROVAL=true
SERVICENOW_BASE_URL=https://your-instance.service-now.com
SERVICENOW_CREATE_PATH=/api/now/table/incident
SERVICENOW_API_TOKEN=
SERVICENOW_ASSIGNMENT_GROUP=
SERVICENOW_TIMEOUT_SECONDS=15
SIDE_EFFECT_IDEMPOTENCY_ENABLED=false
SIDE_EFFECT_IDEMPOTENCY_DIR=/var/notables/idempotency
```

Validation: HTTPS base URL and non-empty token/path when create is enabled;
non-empty assignment group when draft is enabled.

Operator guides:
[`SERVICENOW_OPERATIONS.md`](../operations/integrations/SERVICENOW_OPERATIONS.md),
[`SPLUNK_WRITEBACK_OPERATIONS.md`](../operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md).

### 6.5 HTML reports

```env
HTML_REPORT_ENABLED=false
```

Enabled by `html_reports` profile. Renders query, interpretation, and ServiceNow sections when present.

## 7. SPL Query Generation

**Module:** `spl_query_generation.py`

- Constants: `SPL_QUERY_GENERATION_RULES`, `SPL_QUERY_FIELDS`, `SPL_QUERY_STRATEGIES`
- Contract validation rejects placeholders, invented `index=` / `sourcetype` / macros / datamodel tokens (unless grounding context authorizes)
- Second bounded LLM call when `SPL_QUERY_GENERATION_ENABLED=true` and backend is `splunk`
- Merge generated fields onto six hypotheses by position; one repair attempt; fail-soft suppression on contract failure
- `LLM_STRUCTURED_OUTPUT_MODE=tool_call`: local tool `generate_spl_queries`; fallback to prompt JSON on parse failure

## 8. Splunk Investigation Execution

**Module:** `splunk_investigation.py`

Policy (`validate_splunk_query_policy`) requires:

- non-empty query with explicit `index=` in allowlist
- no denied commands; piped commands strictly allowlisted
- at least one allowed command
- `time_range`, `max_rows`, `timeout_seconds` within configured maxima

Execution:

- **REST:** `POST {SPLUNK_BASE_URL}{SPLUNK_SEARCH_ENDPOINT_PATH}` oneshot
- **MCP:** injected client `run_search(payload) -> dict` with tool payload:

```python
{
    "tool_name": "splunk_search",
    "query": "search index=main ...",
    "query_dialect": "spl",
    "time_range": "1h",
    "max_rows": 100,
    "timeout_seconds": 20,
}
```

MCP response mapping must expose `raw_result_ref`, `search_id`, `job_id`, or `sid`.

Fan-out: up to `INVESTIGATION_MAX_QUERIES_PER_ALERT` (default 6) per alert;
`INVESTIGATION_MAX_CONCURRENT_QUERIES` (default **6**) parallel workers.
Normalized results include compact sample rows (max 5); raw row bodies are not stored in report metadata by default.

## 9. Elasticsearch Query Generation and Execution

**Modules:** `elastic_query_generation.py`, `elasticsearch_investigation.py`

Generation mirrors SPL: second LLM call when `ELASTIC_QUERY_GENERATION_ENABLED=true`;
fields include `primary_elastic_query` (`index_pattern` + `_search` body),
`query_strategy`, `why_this_query`, `supports_if`, `weakens_if`.

Execution validates DSL against index allowlist, denied DSL keys, allowed field
policy, bounded time range and `size`, then POSTs to
`{ELASTICSEARCH_BASE_URL}/{index}/_search` with API key auth. **No MCP path.**

Shared enrichment and interpretation consume the same `query_result_section` shape.

## 10. Query-Result Enrichment

**Module:** `query_result_enrichment.py`

- Adds `query_result_section.summary` and `query_result_section.queries`
- Per-query status: `executed`, `denied`, `skipped`, `failed` (maps REST `success` -> `executed`)
- Hypothesis annotations: `query_result_status`, `query_result_summary`, optional `query_result_reference`
- Does not modify `evidence_vs_inference.evidence` or baseline report fields

**Rendering:** `markdown_generator.py` and `html_generator.py` render Query Results when the section exists.

## 11. Query-Result Interpretation (optional)

**Module:** `query_result_interpretation.py`

When `QUERY_RESULT_INTERPRETATION_ENABLED=true` and `query_result_section` exists:

- One bounded LLM call; output key `query_result_interpretation` (list of per-hypothesis items)
- Allowed `assessment`: `supports`, `weakens`, `inconclusive`, `unknown`
- Allowed `confidence_delta`: `increase`, `decrease`, `unchanged`, `unknown` — **interpretation only**; must not mutate `alert_reconciliation.confidence`, TTP scores, query status, counts, or search references
- Validator rejects invalid hypothesis indexes, enum values, and source refs not in deterministic results
- Malformed output fails soft; deterministic section preserved
- Markdown/HTML render **Query Result Interpretation** after **Query Results**

## 12. ServiceNow Draft and Create

**Module:** `servicenow.py`

Draft fields (standard Incident table; no custom fields v1):

- `short_description`, `description`, `assignment_group`, `category`, `subcategory`, `impact`, `urgency`, `correlation_id`, `correlation_display`, `work_notes`

Create: `POST {SERVICENOW_BASE_URL}{SERVICENOW_CREATE_PATH}` with `Authorization: Bearer <token>`; tokens must not be logged.

Normalized create result: `status`, `sys_id`, `number`, `message`, approval metadata.

Report payload: `servicenow_section.draft|create` with status, message, number, sys_id, approval.

Idempotency (when `SIDE_EFFECT_IDEMPOTENCY_ENABLED=true`): operation `servicenow_incident_create`, key = `correlation_id` or `correlation_display`.

## 13. Side Effects, Sinks, and Idempotency

**Modules:** `idempotency.py`, `sinks.py`

Idempotent operations:

| Operation | Key | Used by |
|-----------|-----|---------|
| `splunk_notable_update` | `finding_id` | `sinks.update_splunk_notable` |
| `servicenow_incident_create` | correlation id | `servicenow.create_servicenow_incident` |

Duplicate completed markers return `status=skipped` without re-posting.

Filesystem sinks write `{notable_id}.md` and optional `{notable_id}.html` to `REPORT_DIR`.

## 14. Processing Order (`onprem_main.py`)

1. Read and normalize alert; run main LLM analysis (`analyze_alert`), including optional second call for SPL or Elastic query fields when generation is enabled (with optional grounding retrieval).
2. If `INVESTIGATION_QUERY_EXECUTION_ENABLED=true`, execute up to six eligible queries via Splunk or Elasticsearch backend.
3. Enrich with `query_result_enrichment.enrich_analysis_with_query_results`.
4. If `QUERY_RESULT_INTERPRETATION_ENABLED=true`, run bounded interpretation.
5. If ServiceNow draft/create enabled, build draft and optionally create with approval.
6. Render markdown; optionally HTML when `HTML_REPORT_ENABLED=true`.
7. Optionally archive case (`analyst_portal` profile).
8. Optionally Splunk notable writeback when `SPLUNK_SINK_ENABLED=true`.
9. Move input to processed/quarantine per existing behavior.

Default config performs steps 1, 6 (markdown only), and 9.

## 15. Approval Input

ServiceNow create approval from incoming JSON root:

```json
{
  "servicenow_create_approval": {
    "approved": true,
    "approved_by": "analyst@example.com",
    "approval_ref": "SNOW-CHANGE-123",
    "approved_at": "2026-04-27T19:40:00Z"
  }
}
```

Missing or incomplete approval denies create when `SERVICENOW_CREATE_REQUIRES_APPROVAL=true`.

## 16. Open Customer Unknowns

Confirm before production enablement:

- ServiceNow table, auth, or field requirements differ from standard Incident Table API
- Splunk MCP client cannot expose `run_search(payload: dict) -> dict`
- Elasticsearch index patterns, field allowlists, or API gateway auth differ from defaults
- Splunk ES `notable_update` contract for writeback (`SPLUNK_NOTABLE_UPDATE_PATH`)

## 17. Rollback

Additive block. Set profiles/flags to off, or remove profile entries; default file-drop analysis remains intact.

## 18. Summary

Optional env- and profile-flagged investigation, enrichment, interpretation, ServiceNow, HTML, and idempotent side effects extend the on-prem analyzer via concrete helper modules and deterministic tests without changing the default runtime path.
