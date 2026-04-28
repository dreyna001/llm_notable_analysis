# Feature Enhancements Technical Spec

## Status

This document is the normative implementation contract for the feature-enhancement block in `llm_notable_analysis_onprem_systemd`.

If wording conflicts with `../architecture/feature_enhancements_architecture.md`, this spec wins for implementation detail.

## 1. Purpose

Implement optional read-only Splunk investigation, deterministic query-result enrichment, and ServiceNow draft/create support in the existing on-prem `systemd` analyzer.

This block must preserve the current default file-drop analysis path.

## 2. Scope

### In scope

- extract SPL generation helpers from `local_llm_client.py`
- add read-only Splunk REST investigation execution
- add read-only Splunk MCP investigation execution
- add deterministic query-result enrichment before markdown rendering
- add ServiceNow incident draft building
- add ServiceNow incident create with explicit approval
- add env flags to `config.env.example` and `onprem_service/config.py`
- add deterministic unit tests with fake responses

### Out of scope

- broad refactor of `local_llm_client.py`
- creating `query_models.py`, `query_policy.py`, or `writeback_policy.py` as separate files
- introducing capability profiles, customer bundles, shared cores, registries, or plugin systems
- changing existing RAG behavior
- enabling any new feature by default
- live Splunk, MCP, or ServiceNow calls in tests

## 3. Baseline Assumptions

- The current service remains a file-drop `systemd` analyzer.
- `RAG_ENABLED` already injects local SOC context into the prompt.
- `SPL_QUERY_GENERATION_ENABLED` runs a second bounded LLM call for SPL query fields only; it does not execute SPL.
- When `RAG_ENABLED=true`, RAG context may include data dictionary and SOP guidance used by query generation and response wording.
- Existing Splunk notable writeback through `SPLUNK_SINK_ENABLED` remains separate from read-only investigation.
- All new behavior is optional and off by default.

## 4. Baseline Constraints

- Keep the existing direct modular style.
- Keep `onprem_main.py` as the orchestration point.
- Add new files only when an existing module would become harder to read or test.
- Keep query execution read-only.
- Do not treat query results as direct alert evidence.
- Do not create ServiceNow incidents without explicit approval metadata.

## 5. Required File Shape

Required new implementation files:

- `onprem_service/spl_query_generation.py`
- `onprem_service/splunk_investigation.py`
- `onprem_service/query_result_enrichment.py`
- `onprem_service/servicenow.py`

Expected modified files:

- `onprem_service/local_llm_client.py`
- `onprem_service/markdown_generator.py`
- `onprem_service/onprem_main.py`
- `onprem_service/config.py`
- `config.env.example`
- `README.md`

Required test files:

- `tests/onprem_service/test_spl_query_generation.py`
- `tests/onprem_service/test_splunk_investigation.py`
- `tests/onprem_service/test_query_result_enrichment.py`
- `tests/onprem_service/test_servicenow.py`
- updates to existing orchestration and markdown tests as needed

## 6. Runtime Config Contract

### 6.1 New optional env vars

```env
INVESTIGATION_QUERY_EXECUTION_ENABLED=false
INVESTIGATION_QUERY_EXECUTOR=rest
INVESTIGATION_MAX_QUERIES_PER_ALERT=6
INVESTIGATION_MAX_CONCURRENT_QUERIES=3
SPLUNK_SEARCH_ENDPOINT_PATH=/services/search/jobs/oneshot
SPLUNK_SEARCH_ALLOWED_INDEXES=main,notable,risk
SPLUNK_SEARCH_ALLOWED_COMMANDS=search,stats,table,fields,where,head
SPLUNK_SEARCH_DENIED_COMMANDS=delete,collect,outputlookup,sendemail,map,rest,script,dbxquery
SPLUNK_SEARCH_MAX_TIME_RANGE=24h
SPLUNK_SEARCH_MAX_ROWS=100
SPLUNK_SEARCH_TIMEOUT_SECONDS=20
SPLUNK_MCP_TOOL_NAME=splunk_search

SERVICENOW_DRAFT_ENABLED=false
SERVICENOW_CREATE_ENABLED=false
SERVICENOW_CREATE_REQUIRES_APPROVAL=true
SERVICENOW_BASE_URL=https://your-instance.service-now.com
SERVICENOW_CREATE_PATH=/api/now/table/incident
SERVICENOW_API_TOKEN=
SERVICENOW_ASSIGNMENT_GROUP=
SERVICENOW_TIMEOUT_SECONDS=15
```

### 6.2 Config validation rules

- `INVESTIGATION_QUERY_EXECUTOR` must be `rest` or `mcp`.
- `INVESTIGATION_MAX_QUERIES_PER_ALERT` must be a positive integer and default to `6`.
- `INVESTIGATION_MAX_CONCURRENT_QUERIES` must be a positive integer and default to `3`.
- Search timeout and max rows must be positive integers.
- Allowed indexes and commands must parse to non-empty lists when query execution is enabled.
- Denied commands must parse to a list.
- `SERVICENOW_BASE_URL` must be HTTPS when create is enabled.
- `SERVICENOW_CREATE_PATH` must be non-empty and start with `/` when create is enabled.
- ServiceNow assignment group must be non-empty when draft is enabled.
- ServiceNow base URL and token must be non-empty when create is enabled.

Do not add `QUERY_RESULT_ENRICHMENT_ENABLED`.

## 7. Diff 1: SPL Generation Extraction

### Objective

Move self-contained SPL generation pieces out of `local_llm_client.py` without changing behavior.

### Files

- `onprem_service/spl_query_generation.py`
- `onprem_service/local_llm_client.py`
- `tests/onprem_service/test_spl_query_generation.py`
- existing LLM client tests as needed

### Implementation

Move these into `spl_query_generation.py`:

- `SPL_QUERY_GENERATION_RULES`
- SPL query field names
- allowed SPL query strategies
- SPL query contract validation
- SPL query field normalization and suppression helpers
- SPL-only prompt builder (alert + 6 hypotheses + SOC/RAG context in, query fields out)
- deterministic merge-by-position helper to attach generated query fields back to hypotheses

Leave these in `local_llm_client.py`:

- LLM transport
- RAG setup and context retrieval
- prompt assembly
- repair loop
- TTP filtering
- metadata annotation

### Acceptance criteria

- Behavior is unchanged when `SPL_QUERY_GENERATION_ENABLED=false`.
- Main alert-analysis prompt does not include SPL query-generation instructions.
- When `SPL_QUERY_GENERATION_ENABLED=true`, SPL query generation runs in a second bounded LLM call.
- SPL output merges onto hypotheses by position and passes SPL contract validation.
- SPL contract failure after one repair attempt suppresses SPL fields without failing base analysis output.
- Existing SPL generation tests still pass.
- New tests cover valid SPL fields, placeholder rejection, index/sourcetype/macro rejection, suppression when disabled, and second-call split behavior.

## 8. Diff 2: Splunk Investigation Execution

### Objective

Add read-only Splunk investigation execution through REST and MCP in one concrete module.

### Files

- `onprem_service/splunk_investigation.py`
- `tests/onprem_service/test_splunk_investigation.py`

### Implementation

`splunk_investigation.py` must include:

- a small query-result evidence shape
- read-only SPL policy validation
- REST execution through Splunk oneshot search
- MCP execution through an injected client with `run_search(payload: dict) -> dict`
- response normalization shared by REST and MCP paths
- bounded parallel execution for up to `INVESTIGATION_MAX_CONCURRENT_QUERIES` searches

Policy validation must check:

- query is non-empty
- query references an allowed `index=...`
- query does not contain denied commands
- query contains at least one allowed command
- time range is present and within max
- max rows is present and within max
- timeout is present and within max

MCP payload shape:

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

MCP response must be a mapping and include either:

- `raw_result_ref`
- `search_id`
- `job_id`
- `sid`

### Acceptance criteria

- Disabled query execution performs no external call.
- Valid REST request builds the expected path and payload.
- Valid MCP request builds the expected tool payload.
- Policy denial prevents REST and MCP calls.
- Up to 6 generated hypothesis queries may be attempted per alert.
- At most 3 searches run concurrently by default.
- Malformed REST or MCP responses return structured failure metadata.
- Raw row bodies are not stored in report metadata by default.

## 9. Diff 3: Query-Result Enrichment

### Objective

Deterministically enrich the existing LLM response object with query-result evidence before markdown rendering.

### Files

- `onprem_service/query_result_enrichment.py`
- `onprem_service/markdown_generator.py`
- `tests/onprem_service/test_query_result_enrichment.py`
- `tests/onprem_service/test_markdown_generator.py`

### Implementation

Enrichment must:

- add a `query_result_section`
- append one entry per attempted query
- record executed, denied, skipped, and failed query states
- annotate matching hypotheses with query-result support or gaps where practical
- preserve existing report fields
- keep query-result evidence separate from `evidence_vs_inference.evidence`
- summarize aggregate results and include only compact samples when needed

Markdown rendering must:

- include a compact "Query Results" section when query results exist
- preserve current report output when no query results exist

### Acceptance criteria

- Successful query results appear in `query_result_section`.
- Denied query attempts appear without execution evidence.
- Adapter failures do not remove the baseline report.
- Markdown renders query results.
- Existing markdown tests still pass.

## 10. Diff 4: ServiceNow Draft And Create

### Objective

Add ServiceNow draft and approved create behavior in one concrete module.

### Files

- `onprem_service/servicenow.py`
- `tests/onprem_service/test_servicenow.py`

### Implementation

`servicenow.py` must include:

- draft builder
- draft payload validation
- create approval validation
- ServiceNow create request to `POST {SERVICENOW_BASE_URL}{SERVICENOW_CREATE_PATH}`
- ServiceNow response normalization

Draft fields:

- `short_description`
- `description`
- `assignment_group`
- `category`
- `impact`
- `urgency`
- `correlation_id`
- `correlation_display`
- `work_notes`

These are standard ServiceNow Incident fields. The app must not create custom ServiceNow fields for v1.

Auth:

- use `Authorization: Bearer <SERVICENOW_API_TOKEN>`
- do not log tokens or full auth headers

Create response normalization:

- `status`
- `sys_id`
- `number`
- `message`
- metadata with operation and source record reference
- approval metadata when present

### Acceptance criteria

- Draft creation has no network side effect.
- Draft creation fails closed when assignment group is missing.
- Oversized summary/body fields are bounded.
- Create is denied when disabled.
- Create is denied when approval metadata is missing.
- Approved create posts expected payload and normalizes response.
- ServiceNow error response is normalized without crashing the service flow.
- Draft/create metadata is recorded locally even when create is skipped, denied, or fails.

## 11. Diff 5: Service Wiring

### Objective

Wire enabled optional features into the existing processing flow.

### Files

- `onprem_service/onprem_main.py`
- `onprem_service/config.py`
- `config.env.example`
- `README.md`
- relevant tests under `tests/onprem_service/`

### Implementation

Processing order:

1. Run current LLM analysis.
2. If `SPL_QUERY_GENERATION_ENABLED=true`, run second LLM call to generate SPL query fields for the 6 hypotheses.
3. If query execution is enabled, validate and execute up to 6 eligible generated SPL queries.
4. Enrich the LLM response with query results.
5. Render markdown.
6. If ServiceNow draft is enabled, build a draft.
7. If ServiceNow create is enabled, require approval and create the incident.
8. Write report and preserve existing processed/quarantine behavior.

### Acceptance criteria

- Default config does not execute queries or ServiceNow writes.
- Enabled REST path executes an approved query and enriches the report.
- Enabled MCP path executes an approved query and enriches the report.
- Denied query records denial and does not call Splunk.
- ServiceNow draft-only path records draft metadata.
- ServiceNow create path requires approval.
- Existing file processing behavior remains unchanged.

## 12. Approval Input

For the first implementation, approval metadata should come from the incoming JSON payload:

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

If missing, create is denied.

## 13. Test Requirements

Tests must be deterministic and require no live Splunk, MCP server, ServiceNow, vLLM, or systemd.

Run:

```bash
python -m unittest discover -s llm_notable_analysis_onprem_systemd/tests/onprem_service -p "test*.py" -v
```

Required coverage:

- SPL generation extraction regression
- query policy allow and deny cases
- REST request construction and response normalization
- MCP payload construction and response normalization
- bounded query fan-out and concurrency
- query-result enrichment success, denial, and failure cases
- markdown rendering with and without query results
- ServiceNow draft success and validation failures
- ServiceNow create approval denied and approved cases
- default-off end-to-end service behavior

## 14. Hard Stops Before Coding

Ask before implementation if any of these remain unknown:

- customer-specific ServiceNow table, auth, or field requirements differ from the standard Incident Table API
- customer-specific Splunk MCP client cannot expose `run_search(payload: dict) -> dict`

## 15. Rollback Note

This block is additive.

Rollback is straightforward:

- set new flags to false
- remove or ignore new modules
- current default file-drop analysis path remains intact

## 16. Recommended First Coding Step

Start with Diff 1 only: extract `spl_query_generation.py` and prove existing SPL generation behavior is unchanged.

Do not wire query execution into `onprem_main.py` until SPL generation extraction and `splunk_investigation.py` tests pass.

## 17. One-Line Summary

Implement the feature enhancements as optional env-flagged additions to the existing on-prem analyzer, using a few concrete helper modules and deterministic tests while preserving the current default runtime path.
