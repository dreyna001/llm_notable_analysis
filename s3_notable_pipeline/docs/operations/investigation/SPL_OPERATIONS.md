# SPL Operations

Operator guide for Splunk SPL generation, optional Bedrock Knowledge Base
grounding, bounded read-only REST or MCP execution, and optional query-result
interpretation on AWS.

## What This Controls

Three independent layers (each gated by its own flags):

1. **SPL query generation** — a bounded second Bedrock call adds `primary_spl_query`
   and related fields to each of six competing hypotheses. No Splunk credentials
   required. Controlled by `SPL_QUERY_GENERATION_ENABLED` (on when the
   `spl_readonly` profile is selected). Requires
   `INVESTIGATION_QUERY_BACKEND=splunk`.

2. **Read-only investigation execution** — runs generated SPL via Splunk REST or
   an HTTPS MCP bridge after local policy checks. Controlled by
   `INVESTIGATION_QUERY_EXECUTION_ENABLED` (also on with `spl_readonly`).
   Requires `SPLUNK_BASE_URL` and `SPLUNK_API_TOKEN_SECRET_ARN` when
   `INVESTIGATION_QUERY_EXECUTOR=rest`, or `SPLUNK_MCP_ENDPOINT` when
   `INVESTIGATION_QUERY_EXECUTOR=mcp`.

3. **Query-result interpretation** — optional third Bedrock call after
   deterministic execution. Controlled by `QUERY_RESULT_INTERPRETATION_ENABLED`
   (default off; no SAM parameter). Does not change query status, counts,
   search refs, or confidence scores.

**Profile note:** `CapabilityProfiles=core,spl_readonly` enables both generation
and execution and sets `INVESTIGATION_QUERY_BACKEND=splunk`. Profile flags take
precedence over direct env values for capabilities they control. For
generation-only lab work, use `CapabilityProfiles=core` and set
`SPL_QUERY_GENERATION_ENABLED=true` without `spl_readonly`.

Splunk notable writeback (`SPLUNK_SINK_ENABLED`, `SplunkSinkMode=notable_rest`)
is separate from investigation. See
[`../integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](../integrations/SPLUNK_WRITEBACK_OPERATIONS.md).

Do not enable `spl_readonly` and `elastic_readonly` together. The runtime
supports one read-only investigation backend per deployment.

## Recommended Starting Posture

- Keep SPL generation and execution disabled for the first `core` rollout.
- Lab generation-only: `CapabilityProfiles=core`,
  `SPL_QUERY_GENERATION_ENABLED=true`, leave execution off.
- Before production execution: review generated SPL with Splunk admins; curate the
  SPL grounding Knowledge Base when queries need approved `index=`, sourcetype,
  macro, or datamodel tokens.
- Keep `QUERY_RESULT_INTERPRETATION_ENABLED=false` until deterministic execution
  quality is accepted.
- Prefer `InvestigationQueryExecutor=rest` unless the customer requires a managed
  MCP bridge.
- Keep `SplunkSearchAllowedIndexes`, command allowlists, row caps, and timeouts
  narrow.
- For parity stacks with `rag` plus read-only investigation, start with
  `LambdaTimeoutSeconds=900` and `LambdaMemorySize=1024` (core defaults are
  `360` / `512`).

## Customer Decisions

- Which Splunk indexes are safe for read-only investigation queries?
- Which SPL commands are allowed and which commands are denied?
- Should Lambda call Splunk REST directly, or a customer-managed MCP bridge over
  HTTPS?
- Which Bedrock Knowledge Base contains customer-approved SPL index, sourcetype,
  macro, and data model guidance?
- What network path is required from Lambda to Splunk or the MCP bridge?
- Should SPL grounding retrieval failures suppress generation or fall back to
  ungrounded output?

## Config Quick Reference

| Area | SAM parameter / Lambda env |
|------|----------------------------|
| Enablement | `CapabilityProfiles=core,spl_readonly` -> `CAPABILITY_PROFILES`; sets `SPL_QUERY_GENERATION_ENABLED`, `INVESTIGATION_QUERY_EXECUTION_ENABLED`, `INVESTIGATION_QUERY_BACKEND=splunk` |
| Executor | `InvestigationQueryExecutor` / `INVESTIGATION_QUERY_EXECUTOR=rest\|mcp` (default `rest`) |
| Splunk REST | `SplunkBaseUrl` / `SPLUNK_BASE_URL`; `SplunkApiTokenSecretArn` / `SPLUNK_API_TOKEN_SECRET_ARN`; optional `SplunkApiTokenSecretField` / `SPLUNK_API_TOKEN_SECRET_FIELD` (default `token`) |
| Splunk REST path | `SPLUNK_SEARCH_ENDPOINT_PATH` (default `/services/search/jobs/oneshot`; env only) |
| Splunk MCP | `SplunkMcpEndpoint` / `SPLUNK_MCP_ENDPOINT`; optional `SplunkMcpAuthSecretArn` / `SPLUNK_MCP_AUTH_SECRET_ARN`; optional `SPLUNK_MCP_AUTH_SECRET_FIELD` (default `token`); `SPLUNK_MCP_HTTP_TIMEOUT_SECONDS` (default `SPLUNK_SEARCH_TIMEOUT_SECONDS + 5`); `SPLUNK_MCP_TOOL_NAME` (default `splunk_search`; env only) |
| Search policy | `SplunkSearchAllowedIndexes` / `SPLUNK_SEARCH_ALLOWED_INDEXES`; `SplunkSearchAllowedCommands` / `SPLUNK_SEARCH_ALLOWED_COMMANDS`; `SplunkSearchDeniedCommands` / `SPLUNK_SEARCH_DENIED_COMMANDS`; optional `SplunkSearchAllowedFields` / `SPLUNK_SEARCH_ALLOWED_FIELDS` (`_raw` is always dropped) |
| Search bounds | `SplunkSearchMaxTimeRange` / `SPLUNK_SEARCH_MAX_TIME_RANGE` (default `24h`); `SplunkSearchMaxRows` / `SPLUNK_SEARCH_MAX_ROWS` (default `100`, max `1000`); `SplunkSearchTimeoutSeconds` / `SPLUNK_SEARCH_TIMEOUT_SECONDS` (default `30`, max `300`) |
| Concurrency | `InvestigationMaxQueriesPerAlert` / `INVESTIGATION_MAX_QUERIES_PER_ALERT` (default `6`); `InvestigationMaxConcurrentQueries` / `INVESTIGATION_MAX_CONCURRENT_QUERIES` (default `6`, max `8`) |
| SPL grounding KB | `SplQueryRagBedrockKbId` / `SPL_QUERY_RAG_BEDROCK_KB_ID` (non-empty id also sets `SPL_QUERY_RAG_ENABLED=true` in the template); `SPL_QUERY_RAG_MAX_SNIPPETS`; `SPL_QUERY_RAG_CONTEXT_BUDGET_CHARS`; `SPL_QUERY_RAG_FAILURE_MODE=suppress\|fallback_to_ungrounded` |
| Query interpretation | `QUERY_RESULT_INTERPRETATION_ENABLED` (env only); `QUERY_RESULT_INTERPRETATION_CONTEXT_BUDGET_CHARS`; `QUERY_RESULT_INTERPRETATION_MAX_SAMPLE_ROWS`; `QUERY_RESULT_INTERPRETATION_MAX_TOKENS` |

SAM and CloudFormation parameters in `deploy/aws/template-sam.yaml` are the
official deployment path. Lambda environment variables are the runtime
representation of those parameters.

## SPL Generation Modes

SPL comes from one bounded second Bedrock call when generation is enabled. Modes
differ only in prompt context attached to that call.

| Mode | Typical flags | Prompt context | Operator tuning |
|------|---------------|----------------|-----------------|
| Alert-only | `core` + `SPL_QUERY_GENERATION_ENABLED=true`, no SPL grounding KB | Alert and hypotheses. No `SOC_OPERATIONAL_CONTEXT` unless `rag` is also enabled. | Contract validation rejects environment tokens such as `index=`, `sourcetype=`, macros, and `datamodel=` unless they appear in the alert or retrieved SPL grounding context. |
| General SOC KB | `core,rag,spl_readonly`, no SPL grounding KB | Alert, hypotheses, and advisory `SOC_OPERATIONAL_CONTEXT` from the general KB. | Runbooks guide reasoning; they do not authorize environment SPL tokens by themselves. |
| SPL grounding KB | `spl_readonly` plus non-empty `SplQueryRagBedrockKbId` | Alert, hypotheses, optional `SOC_OPERATIONAL_CONTEXT`, plus `SPL_QUERY_GROUNDING_CONTEXT` from the Splunk-focused KB. | Curate real indexes, sourcetypes, macros, datamodel notes, and examples. When grounding context is present, contract validation requires environment tokens to appear in the alert or that context. |

When `SPL_QUERY_RAG_ENABLED=true` and grounding retrieval fails,
`SPL_QUERY_RAG_FAILURE_MODE=suppress` (default) skips SPL generation;
`fallback_to_ungrounded` continues without grounding context. RAG and grounding
do not bypass execution allowlists.

## Execution Paths

### Splunk REST (`INVESTIGATION_QUERY_EXECUTOR=rest`)

After `validate_splunk_query_policy` passes, Lambda POSTs form-urlencoded data to
`{SPLUNK_BASE_URL}{SPLUNK_SEARCH_ENDPOINT_PATH}` with a Bearer token from
Secrets Manager. The search uses the configured max time range as `earliest_time`,
`latest_time=now`, and the configured row cap. Denied or invalid queries return
`status=denied` locally with no outbound call.

Implementation: `s3_notable_pipeline/src/s3_notable_pipeline/splunk_investigation.py`
(`execute_splunk_rest_query`).

### MCP over HTTPS (`INVESTIGATION_QUERY_EXECUTOR=mcp`)

After the same policy checks, Lambda POSTs JSON to `SPLUNK_MCP_ENDPOINT` with:

- `tool_name` (default `splunk_search`)
- `query`, `query_dialect=spl`, `time_range`, `max_rows`, `timeout_seconds`

An optional Bearer token comes from `SPLUNK_MCP_AUTH_SECRET_ARN`. The bridge
response must include one of `raw_result_ref`, `search_id`, `job_id`, or `sid`,
plus a `rows` array for normalization.

Implementation: `HttpSplunkMcpClient` and `execute_splunk_mcp_query` in
`splunk_investigation.py`.

## Safety Bounds

Generated SPL is policy-validated before execution. The validator rejects empty
queries, subsearch or macro syntax (`[`, `]`, `` ` ``), queries without explicit
`index=`, indexes outside the allowlist, denied commands, commands outside the
allowlist, excessive time windows, row caps, and timeouts.

Returned sample rows omit `_raw`, cap at five rows and twelve columns per row,
truncate long values, and filter to `SPLUNK_SEARCH_ALLOWED_FIELDS` when that list
is set. Results appear under `investigation_query_results` in JSON with fields
such as `status`, `executor`, `query`, `result_count`, `sample_columns`, and
`sample_rows`. JSON metadata includes `investigation_query_backend`,
`investigation_query_executor`, and `investigation_query_result_count`.

## IAM And Secrets

The Lambda role needs `secretsmanager:GetSecretValue` for
`SPLUNK_API_TOKEN_SECRET_ARN` when REST execution is configured, and for
`SPLUNK_MCP_AUTH_SECRET_ARN` when MCP auth is configured. When SPL grounding is
enabled, the role also needs `bedrock:Retrieve` scoped to the configured SPL
Knowledge Base ARN.

Store Splunk tokens in Secrets Manager as a plain string or JSON with the
configured secret field (default `token`). Do not place tokens directly in SAM
parameters, CloudFormation templates, Lambda environment variables, logs, or
reports.

## Validation And Rollout

1. Deploy with `CapabilityProfiles=core` and confirm the base S3 report path.
2. Create or select the SPL grounding Knowledge Base and confirm its snippets
   contain only approved operational query guidance.
3. Enable `core,spl_readonly` in a non-production stack with narrow indexes and
   row limits.
4. Verify generated SPL appears in JSON and markdown reports under
   `competing_hypotheses[].primary_spl_query`.
5. Confirm denied queries, including subsearch or macro syntax, return
   `status=denied` and do not make a network call.
6. Confirm REST or MCP results are normalized under `investigation_query_results`.
7. Confirm returned sample rows omit `_raw` and retain only approved fields when
   `SPLUNK_SEARCH_ALLOWED_FIELDS` is set.

Unit test commands (from `s3_notable_pipeline/`):

```bash
python -m pytest tests/test_spl_query_generation.py tests/test_splunk_investigation.py tests/test_lambda_handler.py -v
```

Broader parity and staging guidance: [`../../testing/TESTING.md`](../../testing/TESTING.md).

## Related Docs

- [`../platform/CAPABILITY_PROFILES.md`](../platform/CAPABILITY_PROFILES.md)
- [`../rag/KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md)
- [`../rag/RAG_OPERATIONS.md`](../rag/RAG_OPERATIONS.md)
- [`../llm/LLM_INFERENCE_OPERATIONS.md`](../llm/LLM_INFERENCE_OPERATIONS.md)
- [`../security/SECURITY_OPERATIONS.md`](../security/SECURITY_OPERATIONS.md)
- [`../../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md`](../../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md)
