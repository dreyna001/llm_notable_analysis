# AWS Notable Pipeline Technical Spec

## Status

Implementation contract for the AWS notable pipeline. **Wave 1 sections** (profiles
through idempotency below) describe implemented analyzer behavior. **Wave 2
sections** (analyst portal block at end) are synced from
[`../planning/AWS_ONPREM_PARITY_REQUIREMENTS_AND_DESIGN.md`](../planning/AWS_ONPREM_PARITY_REQUIREMENTS_AND_DESIGN.md)
as of the doc sync; code, SAM/CFN, and tests catch up in Diff 1 through Diff 5.

## Normative Source

Primary (wave 2 — portal, archive, Case Q&A, Decisions 1-36):

[`../planning/AWS_ONPREM_PARITY_REQUIREMENTS_AND_DESIGN.md`](../planning/AWS_ONPREM_PARITY_REQUIREMENTS_AND_DESIGN.md)

Background (wave 1 — profiles, RAG, SPL, Elastic, ServiceNow, idempotency):

[`../planning/AWS_ONPREM_PARITY_PLAN.md`](../planning/AWS_ONPREM_PARITY_PLAN.md)

If this spec conflicts with REQUIREMENTS_AND_DESIGN, stop and resolve before
coding. Wave 1 PLAN content applies only where wave 2 does not supersede it.

## Deployment Target (v1)

**Locked deployment target:** Production parity deploys target **AWS GovCloud
`us-gov-west-1`**. Use `arn:aws-us-gov:...` partition ARNs in examples and
templates unless a customer explicitly chooses a commercial region.

## Locked Runtime Shape

The AWS pipeline keeps its current architecture:

```text
S3 incoming object -> Lambda -> Bedrock analysis -> S3 report output -> optional Splunk writeback
```

New capabilities must be inserted as optional, default-off steps around that
flow. Do not move orchestration to Step Functions as part of this parity block.

## Diff 1 Contract

Diff 1 adds (wave 2 portal block):

- `analyst_portal` capability profile parsing and validation in `config.py`.
- Portal/archive/chunk/index runtime settings in `config.env.example` and
  SAM/CloudFormation parameter scaffolding (default-off; no behavior change for
  `core` only).
- This technical spec wave 2 sections below.

Diff 1 must preserve current default behavior:

- `CAPABILITY_PROFILES=core`
- `SPLUNK_SINK_MODE=s3`
- one S3 object triggers one Lambda analysis run
- markdown and JSON outputs are written under `reports/`
- `SPLUNK_SINK_MODE=notable_rest` still writes S3 output first, then posts to
  Splunk REST
- If the S3 sink write fails, Splunk REST writeback is skipped and the Lambda
  invocation fails so the event can be retried.

## Capability Profiles

Supported profile names:

- `core`
- `html_reports`
- `rag`
- `spl_readonly`
- `elastic_readonly`
- `ticket_draft`
- `action_gated`
- `analyst_portal` (wave 2; enables case archive, portal API, and Case Q&A per
  REQUIREMENTS_AND_DESIGN)

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
- Subsearch and macro syntax is denied by default for generated read-only SPL.
- Result samples drop `_raw` and retain only `SPLUNK_SEARCH_ALLOWED_FIELDS` when
  configured before reports or LLM interpretation see the rows.
- `INVESTIGATION_QUERY_EXECUTOR=rest` calls Splunk REST oneshot search using the
  existing Splunk token resolver.
- `INVESTIGATION_QUERY_EXECUTOR=mcp` calls a configured HTTPS MCP bridge
  endpoint. This has no Cursor MCP dependency.
- REST and MCP execution return the same normalized result shape and are stored
  under `investigation_query_results` until deterministic enrichment is added in
  Diff 4.

## Elasticsearch Generation, Grounding, And Execution Contract

Elasticsearch read-only investigation is implemented in
`elastic_query_generation.py`, `elasticsearch_query_grounding.py`,
`elasticsearch_investigation.py`, and
`BedrockAnalyzer.generate_elastic_queries()`.

Rules:

- Elasticsearch generation is default-off and enabled by `elastic_readonly` or
  `ELASTIC_QUERY_GENERATION_ENABLED=true`.
- The Elastic call is a second bounded Bedrock call. It may only add
  `query_strategy`, `primary_elastic_query`, `why_this_query`, `supports_if`,
  and `weakens_if` to the six existing competing hypotheses.
- Elastic-specific grounding uses `ELASTICSEARCH_GROUNDING_BEDROCK_KB_ID`.
  Retrieved grounding is advisory environment context, not current-alert
  evidence.
- Generated `primary_elastic_query` values must contain `index_pattern` and
  read-only `_search` Query DSL `body`.
- Query DSL must not use scripts, `query_string`, wildcard clauses,
  aggregations, highlighting, or runtime mappings.
- Query bodies must include a bounded range filter on
  `ELASTICSEARCH_TIMESTAMP_FIELD`, stay within `ELASTICSEARCH_MAX_TIME_RANGE`,
  and use only allowlisted fields or fields grounded by alert or KB context.
- `_search` execution runs only when
  `INVESTIGATION_QUERY_EXECUTION_ENABLED=true` with
  `INVESTIGATION_QUERY_BACKEND=elasticsearch`.
- `ELASTICSEARCH_BASE_URL` must be HTTPS when execution is enabled. The API key
  is read from `ELASTICSEARCH_API_KEY_SECRET_ARN` and is never logged.
- Execution returns the same normalized `investigation_query_results` shape used
  by Splunk results so deterministic enrichment and optional interpretation can
  remain backend-neutral.

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

## ServiceNow Draft/Create Contract

ServiceNow support is implemented in `servicenow.py` and wired into
`lambda_handler.py`.

Rules:

- Draft generation is default-off and has no network side effect.
- Drafts require `SERVICENOW_ASSIGNMENT_GROUP` and produce an
  `incident_payload` under `servicenow_section.draft`.
- Incident create is default-off and uses `SERVICENOW_API_TOKEN_SECRET_ARN` for
  the bearer token.
- When `SERVICENOW_CREATE_REQUIRES_APPROVAL=true`, create requires
  `servicenow_create_approval.approved` to be the JSON boolean `true`,
  non-empty `approved_by`, and a valid HMAC signature from
  `SERVICENOW_APPROVAL_HMAC_SECRET_ARN`.
- Create results are written under `servicenow_section.create`.
- ServiceNow URLs must use HTTPS.

## DynamoDB Idempotency Contract

External side-effect idempotency is implemented in `idempotency.py`.

Rules:

- Idempotency is only for external side effects, not the S3 analysis run itself.
- `action_gated` enables idempotency by default.
- The DynamoDB table uses `id` as a string hash key and `expires_at` as a TTL
  attribute.
- Reservation keys are deterministic and operation-scoped:
  `splunk_notable_update` uses `finding_id`; `servicenow_incident_create` uses
  the ServiceNow correlation id.
- Conditional `PutItem` prevents duplicate side effects. Completed rows return a
  skipped result with prior metadata where available. Stale in-progress rows can
  be reclaimed after `SIDE_EFFECT_IDEMPOTENCY_LOCK_SECONDS`; fresh in-progress
  rows are reported as locked rather than completed.
- Failed side effects release their in-progress reservation.

---

## Wave 2: Analyst Portal Block (Diff 1-5)

Normative detail: REQUIREMENTS_AND_DESIGN Decisions 1-36 and diff sequence.
Implement only the diff scope active in the current change.

### Analyzer And Portal Bedrock Model Contract (Decisions 28, 29)

Default analyzer model: **Claude Sonnet 4.6** on Amazon Bedrock unless the
customer overrides `BEDROCK_MODEL_ID`.

- SAM/CloudFormation default `BEDROCK_MODEL_ID` uses the regional Sonnet 4.6
  inference profile ARN for the deployment region.
- Portal chat inherits `BEDROCK_MODEL_ID` when `PORTAL_CHAT_BEDROCK_MODEL_ID` is
  unset.
- Optional `PORTAL_CHAT_BEDROCK_MODEL_ID` overrides chat synthesis only.
- Portal chat must not import or reuse analyzer prompts from `ttp_analyzer.py`.

### Case Archive And Index Contract (Decisions 1, 5, 10, 20, 24-26)

- S3 canonical envelope at
  `{CASE_ARCHIVE_PREFIX}/yyyy/mm/dd/{case_id}.json`.
- DynamoDB CaseIndex for browse/query metadata and pointers only; no full alert
  payloads or full analysis bodies in DynamoDB.
- **No Aurora Postgres, RDS Proxy, or OpenSearch** for v1 archive storage or
  case retrieval (Decision 1).
- Analyzer writes envelope and CaseIndex, sets `retrieval_status=pending`, then
  asynchronously invokes the **embed Lambda (Diff 2b)**. Embedding must not run
  inside the analyzer Lambda process (Decisions 10, 24).
- Embed Lambda writes S3 chunk objects at
  `{CASE_ARCHIVE_CHUNKS_PREFIX}/{case_id}/{chunk_id}.json` with `search_text` and
  Titan embeddings; transitions `retrieval_status` to `ready` or `failed`
  (Decisions 6, 20, 26).
- Identity collision on an existing `case_id` suppresses the archive write
  (Decision 25).
- `CASE_ARCHIVE_FAILURE_MODE=suppress` (default) preserves report output on
  archive/index/embed failure (Decision 5).

### Portal Hosting Contract (Decisions 2, 9, 19, 31, 34)

- Portal API: read-only Lambda plus API Gateway with JWT authorizer (IAM
  second-best).
- Static React SPA on S3 plus CloudFront (Decision 18).
- Long-running chat: portal Lambda Function URL behind CloudFront path
  `/api/chat` and `/api/chat/*`; other `/api/*` routes use API Gateway
  (Decisions 19, 31).
- Recommended v1 bundle: `CAPABILITY_PROFILES=core,analyst_portal` (Decision 34).
- Portal Lambda has no write permissions to case index, input bucket, writeback
  secrets, or external integrations.

### Portal API And Case Q&A Contract (Decisions 3-4, 7, 11-14, 21-23, 27, 33, 36)

- Read-only portal handler; no case mutations from the portal.
- Pinned-case chat only (`selected_case_id` required on every chat request).
- Hybrid retrieval in portal Lambda over **S3 case chunk objects**: in-memory
  BM25 on `search_text`, cosine similarity on Bedrock Titan query embeddings,
  merged with RRF (`CASE_QA_RRF_K=60`). No OpenSearch, Kendra, or Bedrock KB for
  case-archive retrieval (Decision 7).
- Optional advisory KB context when `rag`, `spl_readonly`, or `elastic_readonly`
  profiles are also enabled (Decision 12).
- Chat synthesis in `portal_chat.py`; do not import `ttp_analyzer.py`
  (Decision 33).
- Response shapes follow `docs/contracts/portal.openapi.json` and
  `portal_api_models.py` (Pydantic); pin `pydantic` in `requirements.txt` per
  Decision 35.
- `archive_notices` on case list and detail; full `chat_dependency_status` when
  `CASE_QA_ENABLED=true` (Decisions 21-22).
- Chat concurrency: each portal Lambda instance handles at most
  `PORTAL_CHAT_MAX_CONCURRENCY` in-flight chat requests (default `18`, max `64`);
  returns HTTP 429 when exceeded. Under load, total capacity scales with warm
  instances. v1 does not use a cross-instance counter (Decisions 23, 36).

### Embedding Contract (Decision 6)

- Chunk and query embeddings: Bedrock Titan (`amazon.titan-embed-text-v2:0`),
  `1024` dimensions with `normalize=true`.
- Do not load local Mixedbread embedder into Lambda.
- Same model at chunk write (embed Lambda) and chat query time (portal Lambda).

### Chat History Contract (Decisions 8, 17)

- Default-off: `CASE_QA_CHAT_HISTORY_ENABLED=false`.
- When enabled: DynamoDB `CHAT_SESSIONS_TABLE` and `CHAT_MESSAGES_TABLE`; portal
  Lambda read/write only.

### Python Dependencies (Decision 35)

- Add `pydantic` (pinned to on-prem resolved version) when Diff 3 ships.
- Do not deploy `fastapi` or `uvicorn` on the portal Lambda.
- Do not port local ML/RAG stack packages; AWS uses Bedrock for embed and chat.
