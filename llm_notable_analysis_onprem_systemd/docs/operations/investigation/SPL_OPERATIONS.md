# SPL Operations

Operator guide for Splunk SPL generation, read-only execution, and optional
query-result interpretation. Tune index allowlists, command policy, timeouts,
concurrency, grounding KB, and execution posture per customer.

Complements [`EXECUTIVE_ONPREM_WORKFLOW.md`](../../delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md)
and the env contract in [`config.env.example`](../../../config.env.example).

## What This Controls

Three independent layers (each gated by its own flags):

1. **SPL query generation** — second LLM call adds `primary_spl_query` and related
   fields to each of six competing hypotheses. No Splunk credentials required.
   Controlled by `SPL_QUERY_GENERATION_ENABLED` (on when `spl_readonly` profile
   is selected). Requires `INVESTIGATION_QUERY_BACKEND=splunk`.

2. **Read-only investigation execution** — runs generated SPL via REST or an
   injected MCP client after local policy checks. Requires Splunk credentials
   for REST (`SPLUNK_BASE_URL`, `SPLUNK_API_TOKEN`). Controlled by
   `INVESTIGATION_QUERY_EXECUTION_ENABLED` (also on with `spl_readonly` profile).

3. **Query-result interpretation** — optional third LLM call after deterministic
   execution. Controlled by `QUERY_RESULT_INTERPRETATION_ENABLED` (default off).
   Does not change query status, counts, search refs, or confidence scores.

**Profile note:** `CAPABILITY_PROFILES=core,spl_readonly` enables both generation
and execution; profile flags override direct env values for those two settings.
For generation-only lab work, use `CAPABILITY_PROFILES=core` and set
`SPL_QUERY_GENERATION_ENABLED=true` without `spl_readonly`.

Splunk writeback (`SPLUNK_SINK_ENABLED`, `SPLUNK_NOTABLE_UPDATE_PATH`) is
separate from investigation and is not covered here.

## Recommended Starting Posture

- Lab generation-only: `CAPABILITY_PROFILES=core`, `SPL_QUERY_GENERATION_ENABLED=true`,
  leave execution off.
- Before production execution: review generated SPL with Splunk admins; curate SPL
  grounding KB if queries need `index=` / sourcetype / macro tokens.
- Keep `QUERY_RESULT_INTERPRETATION_ENABLED=false` until deterministic execution
  quality is accepted.
- Keep `SPLUNK_SEARCH_*` allowlists narrow; prefer REST unless MCP is required.
- Start with `SPL_QUERY_RAG_FAILURE_MODE=suppress`.

## SPL Generation Modes

SPL comes from one bounded second LLM call when generation is enabled. Modes
differ only in prompt context attached to that call.

| Mode | Typical flags | Prompt context | Operator tuning |
|------|---------------|----------------|-----------------|
| Alert-only | `core` + `SPL_QUERY_GENERATION_ENABLED=true`, `SPL_QUERY_RAG_ENABLED=false` | Alert, hypotheses. No `SOC_OPERATIONAL_CONTEXT` unless `rag` profile is also on. | Validation **rejects** `index=`, `sourcetype=`, macros, and `datamodel=` in generated SPL. Queries use observable alert fields only. |
| General SOC KB | `core,rag,spl_readonly`, `SPL_QUERY_RAG_ENABLED=false` | Alert, hypotheses, `SOC_OPERATIONAL_CONTEXT` from the normal KB. | Runbooks guide reasoning; they do **not** authorize environment SPL tokens. Same token rejection as alert-only. |
| SPL grounding KB | `spl_readonly`, `SPL_QUERY_RAG_ENABLED=true` | Alert, hypotheses, optional `SOC_OPERATIONAL_CONTEXT`, plus `SPL_QUERY_GROUNDING_CONTEXT` from the Splunk-focused KB. | Curate real indexes, sourcetypes, macros, datamodel notes, and examples. Environment tokens are allowed only when present in the alert **or** retrieved SPL grounding context. |

When non-empty grounding context is present, validation uses strict grounding
(`require_spl_grounding=true`): unlisted environment tokens fail contract
validation. RAG does not bypass execution allowlists.

### Dedicated SPL KB

**Settings:** `SPL_QUERY_RAG_ENABLED`, `SPL_QUERY_RAG_SOURCE_DIR`,
`SPL_QUERY_RAG_INDEX_DIR`, `SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE`,
`SPL_QUERY_RAG_MAX_SNIPPETS`, `SPL_QUERY_RAG_CONTEXT_BUDGET_CHARS`,
`SPL_QUERY_RAG_FAILURE_MODE`

- Keep disabled until Splunk owners approve source docs.
- Uses the shared Postgres RAG stack (`RAG_POSTGRES_DSN`, embedding/rerank
  settings) but a **separate** chunks table (default `spl_query_chunks`).
- `suppress` (default): skip SPL generation if the SPL KB is unavailable.
- `fallback_to_ungrounded`: generate without grounding context on KB failure
  (environment tokens will still fail validation unless absent from queries).
- Ingest: `scripts/setup_postgres_rag.sh --spl-query-rag`
- Templates and quality checks:
  [`KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md)

**Provenance:** merged hypotheses may include `primary_spl_query_grounding_refs`
(source file + section path). Markdown reports do not render these today; see
`metadata.spl_query_rag_*` fields on the analysis result.

### Generation contract (code-enforced)

Per hypothesis (six total: three benign, three adversary):

- `query_strategy`: `resolve_unknown` or `check_contradiction`
- `primary_spl_query`, `why_this_query`, `supports_if`, `weakens_if` (all required)
- No placeholders (`<...>`) or pseudo-queries (`...`)
- Prompt asks for bounded time windows when `ALERT_TIME` is available

## Execution Policy and Tuning

### Enable gate

**Settings:** `INVESTIGATION_QUERY_EXECUTION_ENABLED`, `INVESTIGATION_QUERY_BACKEND`,
`INVESTIGATION_QUERY_EXECUTOR`

- Backend must be `splunk` for SPL execution (`onprem_main` routes by backend).
- Executor: `rest` (direct Splunk REST) or `mcp` (injected client; no MCP endpoint
  env on-prem — wiring is in service code).
- MCP client must implement `run_search(payload)` with fields:
  `tool_name` (`SPLUNK_MCP_TOOL_NAME`), `query`, `query_dialect`, `time_range`,
  `max_rows`, `timeout_seconds`. Success responses need a search reference
  (`raw_result_ref`, `search_id`, `job_id`, or `sid`) plus optional `rows`.

### Index and command policy

**Settings:** `SPLUNK_SEARCH_ALLOWED_INDEXES`, `SPLUNK_SEARCH_ALLOWED_COMMANDS`,
`SPLUNK_SEARCH_DENIED_COMMANDS`

`validate_splunk_query_policy` (local, not full SPL grammar) requires:

- Non-empty query with explicit `index=...` matching the allowlist
- No denied command tokens (word-boundary match)
- Every piped command in the allowlist (first segment with `=` is treated as
  an implicit base search)
- Requested time range, row count, and timeout within configured maxima

**Generation vs execution gap:** ungrounded generated SPL typically omits
`index=...` and will be **denied** at execution unless SPL grounding KB enables
environment tokens. Plan KB curation before turning execution on.

Default denied commands:
`delete,collect,outputlookup,sendemail,map,rest,script,dbxquery`

Default allowed commands:
`search,stats,table,fields,where,head`

### Bounds and concurrency

**Settings:** `SPLUNK_SEARCH_MAX_TIME_RANGE`, `SPLUNK_SEARCH_MAX_ROWS`,
`SPLUNK_SEARCH_TIMEOUT_SECONDS`, `INVESTIGATION_MAX_QUERIES_PER_ALERT`,
`INVESTIGATION_MAX_CONCURRENT_QUERIES`

- Execution applies one lookback to all queries: `SPLUNK_SEARCH_MAX_TIME_RANGE`
  (default `24h`) as `earliest_time`; not per-query LLM windows.
- REST prepends `search` when the query does not already start with `search`.
- Defaults: 6 queries/alert, 6 concurrent (caps: 24 queries, 8 concurrent).
- Defaults: 100 rows (max 1000), 30s timeout (max 300s).
- REST TLS: `SPLUNK_CA_BUNDLE` or system trust store.

### Splunk connectivity (REST)

**Settings:** `SPLUNK_BASE_URL`, `SPLUNK_API_TOKEN`, `SPLUNK_CA_BUNDLE`,
`SPLUNK_SEARCH_ENDPOINT_PATH` (default oneshot:
`/services/search/jobs/oneshot`)

### Query-result interpretation

**Settings:** `QUERY_RESULT_INTERPRETATION_ENABLED`,
`QUERY_RESULT_INTERPRETATION_CONTEXT_BUDGET_CHARS` (default 4000),
`QUERY_RESULT_INTERPRETATION_MAX_SAMPLE_ROWS` (default 3),
`QUERY_RESULT_INTERPRETATION_MAX_TOKENS` (default 768)

- Runs only after successful deterministic execution enrichment.
- Markdown keeps `Query Results` (status, counts, sample columns, search refs).
- Optional `Query Result Interpretation` section when enabled and validation passes.
- `confidence_delta` is prose-only (`increase` / `decrease` / `unchanged` /
  `unknown`); never mutates scores or query facts.
- Execution stores up to 5 sample rows internally; interpretation prompt uses the
  configured sample-row cap.

## Customer Onboarding — Splunk Query Grounding

Complete with Splunk owners before `SPL_QUERY_RAG_ENABLED=true`.

| Item | Required | Notes |
|------|----------|-------|
| Approved `index=` names | Yes | Align with `SPLUNK_SEARCH_ALLOWED_INDEXES` when execution is on |
| Approved `sourcetype=` names | Yes | Per index or hunt pattern |
| Macro / datamodel names | If used | Only tokens that may appear in generated SPL |
| Field hints | Recommended | Improves retrieval; not code-enforced |
| Example SPL patterns | Recommended | Known-good admin-approved queries |
| Representative notables | Yes | 3–5 per major log source |
| Execution scope | Yes | Generation-only vs read-only execute |
| Failure mode | Yes | Default `suppress` |
| KB owner / review cadence | Yes | Approve doc changes before rebuild |

**Rollout:** stage docs under `SPL_QUERY_RAG_SOURCE_DIR` → ingest with
`setup_postgres_rag.sh --spl-query-rag` → enable `SPL_QUERY_RAG_ENABLED=true`
→ spot-check `primary_spl_query` and metadata → if executing, align
`SPLUNK_SEARCH_*` with KB indexes.

## Config Quick Reference

| Area | Variables |
|------|-----------|
| Profiles | `CAPABILITY_PROFILES` (`spl_readonly` enables generation + execution + `INVESTIGATION_QUERY_BACKEND=splunk`) |
| Generation | `SPL_QUERY_GENERATION_ENABLED`, `INVESTIGATION_QUERY_BACKEND` |
| SPL grounding KB | `SPL_QUERY_RAG_*` (see above) |
| Execution | `INVESTIGATION_QUERY_EXECUTION_ENABLED`, `INVESTIGATION_QUERY_EXECUTOR`, `INVESTIGATION_MAX_QUERIES_PER_ALERT`, `INVESTIGATION_MAX_CONCURRENT_QUERIES` |
| Interpretation | `QUERY_RESULT_INTERPRETATION_*` |
| Splunk REST | `SPLUNK_BASE_URL`, `SPLUNK_API_TOKEN`, `SPLUNK_CA_BUNDLE`, `SPLUNK_SEARCH_ENDPOINT_PATH` |
| Policy | `SPLUNK_SEARCH_ALLOWED_INDEXES`, `SPLUNK_SEARCH_ALLOWED_COMMANDS`, `SPLUNK_SEARCH_DENIED_COMMANDS`, `SPLUNK_SEARCH_MAX_TIME_RANGE`, `SPLUNK_SEARCH_MAX_ROWS`, `SPLUNK_SEARCH_TIMEOUT_SECONDS` |
| MCP | `SPLUNK_MCP_TOOL_NAME` (+ injected client in code) |

## Validation And Rollout

1. Enable generation only; review hypothesis SPL blocks in reports.
2. Optionally ingest SPL KB and enable `SPL_QUERY_RAG_ENABLED=true`.
3. Set customer `SPLUNK_SEARCH_*` allowlists in lab config.
4. Enable execution against non-prod or narrow indexes; track denied/error/success
   in report `Query Results` and analysis metadata.
5. Promote wider policy only after load and quality review.

**Code references:**

- [`spl_query_generation.py`](../../../src/llm_notable_analysis_onprem_systemd/onprem_service/spl_query_generation.py) — prompt, contract validation, grounding refs
- [`spl_query_grounding.py`](../../../src/llm_notable_analysis_onprem_systemd/onprem_service/spl_query_grounding.py) — SPL KB retrieval
- [`splunk_investigation.py`](../../../src/llm_notable_analysis_onprem_systemd/onprem_service/splunk_investigation.py) — policy gate and REST/MCP execution

## Related Docs

- [`KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md) — SPL KB templates and retrieval tuning
- [`RAG_OPERATIONS.md`](../rag/RAG_OPERATIONS.md) — shared Postgres RAG knobs
- [`ELASTICSEARCH_OPERATIONS.md`](ELASTICSEARCH_OPERATIONS.md) — alternate investigation backend
