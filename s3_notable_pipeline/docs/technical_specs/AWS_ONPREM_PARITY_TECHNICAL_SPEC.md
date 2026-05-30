# AWS / On-Prem Parity Technical Spec

## Status

Technical-spec shell for the AWS parity implementation. Diff 1 establishes
runtime configuration, centralized AWS client creation, deployment-parameter
scaffolding, and documentation structure. Later diffs must fill in the relevant
sections before implementing each capability.

## Normative Source

The implementation plan is
[`../planning/AWS_ONPREM_PARITY_PLAN.md`](../planning/AWS_ONPREM_PARITY_PLAN.md).
If this spec and the plan conflict before a section is filled in, stop and
resolve the conflict before coding.

## Locked Runtime Shape

The AWS pipeline keeps its current architecture:

```text
S3 incoming object -> Lambda -> Bedrock analysis -> S3 report output -> optional Splunk writeback
```

New capabilities must be inserted as optional, default-off steps around that
flow. Do not move orchestration to Step Functions as part of this parity block.

## Diff 1 Contract

Diff 1 adds:

- `src/s3_notable_pipeline/config.py` for capability profile parsing and runtime
  config validation.
- `src/s3_notable_pipeline/aws_clients.py` for centralized boto3 client creation
  with `AWS_ENDPOINT_URL` support for local emulation.
- `config.env.example` as the operator-readable runtime contract companion to
  SAM/CloudFormation parameters.
- Operations documentation skeletons.
- SAM and pure CloudFormation parameter scaffolding for Lambda resource tuning
  and future profile-driven settings.

Diff 1 must preserve current default behavior:

- `CAPABILITY_PROFILES=core`
- `SPLUNK_SINK_MODE=s3`
- one S3 object triggers one Lambda analysis run
- markdown and JSON outputs are written under `reports/`
- `SPLUNK_SINK_MODE=notable_rest` still writes S3 output first, then posts to
  Splunk REST

## Capability Profiles

Supported profile names:

- `core`
- `html_reports`
- `rag`
- `spl_readonly`
- `elastic_readonly`
- `ticket_draft`
- `action_gated`

Rules:

- `core` is always included.
- Unknown profiles fail configuration validation.
- `spl_readonly` and `elastic_readonly` are mutually exclusive.
- Risky capabilities remain off unless enabled by profile or documented legacy
  low-level flags.

## AWS Client Creation

All new AWS SDK clients must come from `aws_clients.py`.

Unit tests must mock clients and must not require AWS credentials. Local
integration tests, if added later, must use `AWS_ENDPOINT_URL` and local test
credentials.

## Open Sections For Later Diffs

The following sections must be completed in the same diff that implements the
feature:

- ServiceNow draft/create contract.
- DynamoDB idempotency contract.
- Elasticsearch generation, grounding, and execution contract.

## Bedrock Knowledge Base Retrieval Contract

General SOC RAG is implemented in `bedrock_kb_retrieval.py`.

Rules:

- RAG is default-off.
- Retrieved content is advisory context only and must not be treated as direct
  current-alert evidence.
- Missing Knowledge Base ids fail soft by default with `RAG_FAILURE_MODE=suppress`.
- `RAG_FAILURE_MODE=fail_closed` raises and causes the Lambda record processing
  path to fail.
- Retrieval is bounded by `RAG_MAX_SNIPPETS` and
  `RAG_CONTEXT_BUDGET_CHARS`.
- JSON output metadata records `rag_status`, `rag_snippet_count`, and optional
  `rag_message`.

The prompt uses a `SOC_OPERATIONAL_CONTEXT` block and explicitly instructs the
model that this context is not observed alert evidence.

## HTML Report Output Contract

HTML reporting is implemented in `html_generator.py` and wired through
`write_to_s3_sink`.

Rules:

- HTML is default-off.
- When enabled, HTML is written as `<output_prefix>/<base_name>.html`.
- Markdown and JSON output keys are unchanged.
- HTML rendering is deterministic and does not call the model.
- Alert text and model-controlled text are HTML-escaped before rendering.

## SPL Generation And Grounding Contract

SPL query generation is implemented in `spl_query_generation.py`,
`spl_query_grounding.py`, and `BedrockAnalyzer.generate_spl_queries()`.

Rules:

- SPL generation is default-off and enabled by `spl_readonly` or
  `SPL_QUERY_GENERATION_ENABLED=true`.
- The SPL call is a second bounded Bedrock call. It may only add
  `query_strategy`, `primary_spl_query`, `why_this_query`, `supports_if`, and
  `weakens_if` to the six existing competing hypotheses.
- SPL-specific grounding uses `SPL_QUERY_RAG_BEDROCK_KB_ID`. The runtime reads
  the Lambda environment variable, while operators should set the value through
  SAM/CloudFormation parameters.
- Retrieved SPL grounding is advisory Splunk-environment context, not current
  alert evidence.
- Generated queries must not contain placeholder tokens, pseudo-query ellipses,
  or ungrounded indexes, sourcetypes, macros, or data model names when SPL query
  grounding is required.
- Generation failures fail soft by leaving the base analysis unchanged and
  recording `spl_query_generation_status` metadata.

## Splunk REST/MCP Execution Contract

Read-only Splunk investigation is implemented in `splunk_investigation.py`.

Rules:

- Execution is default-off and runs only when
  `INVESTIGATION_QUERY_EXECUTION_ENABLED=true` with
  `INVESTIGATION_QUERY_BACKEND=splunk`.
- Every generated query is policy-validated before any external call.
- Queries must include explicit `index=...`, use only allowlisted indexes and
  commands, avoid denied commands, and stay within configured row, timeout, and
  time-range bounds.
- `INVESTIGATION_QUERY_EXECUTOR=rest` calls Splunk REST oneshot search using the
  existing Splunk token resolver.
- `INVESTIGATION_QUERY_EXECUTOR=mcp` calls a configured HTTPS MCP bridge
  endpoint. This has no Cursor MCP dependency.
- REST and MCP execution return the same normalized result shape and are stored
  under `investigation_query_results` until deterministic enrichment is added in
  Diff 4.

## Query-Result Enrichment And Interpretation Contract

Deterministic enrichment is implemented in `query_result_enrichment.py`.
Optional interpretation is implemented in `query_result_interpretation.py` and
`BedrockAnalyzer.interpret_query_results()`.

Rules:

- Query-result enrichment is deterministic and runs after read-only query
  execution returns normalized records.
- Enrichment adds `query_result_section` and hypothesis-level
  `query_result_status`, `query_result_summary`, and optional
  `query_result_reference`.
- Enrichment does not mutate `alert_reconciliation`, TTP scores, query status,
  result counts, or source references.
- Query-result interpretation is default-off.
- When enabled, interpretation is a separate bounded Bedrock call over a pruned
  JSON context containing only alert summary facts, hypotheses, and deterministic
  query-result records.
- Malformed interpretation output gets one repair attempt. If repair fails, the
  interpretation is dropped and deterministic query results remain.
- Interpretation may produce prose assessment, observations, gaps, and
  `confidence_delta` labels only. It must not rewrite deterministic facts.
