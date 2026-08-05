# AWS / On-Prem Parity Technical Spec

## Status

Normative implementation contract for optional AWS notable-pipeline capabilities
and on-prem behavioral parity. **Wave 1** (profiles through idempotency),
**Wave 2** (analyst portal block, Diff 1-5), **Wave 3** (runtime parity gaps),
and **P3-1** (multi-turn synthesis) are **shipped on `main`**.

**Not shipped in this repo:** real-AWS deploy validation in a staging account;
customer front-door wiring (JWT issuer/audience, CORS, DNS/WAF). Those are
operator closeout steps.

Operator runbooks: [`../operations/README.md`](../operations/README.md).

On-prem normative counterpart:
[`../../../llm_notable_analysis_onprem_systemd/docs/technical_specs/feature_enhancements_technical_spec.md`](../../../llm_notable_analysis_onprem_systemd/docs/technical_specs/feature_enhancements_technical_spec.md)
(analyzer) and
[`../../../llm_notable_analysis_onprem_systemd/docs/technical_specs/analyst_portal_case_archive_technical_spec.md`](../../../llm_notable_analysis_onprem_systemd/docs/technical_specs/analyst_portal_case_archive_technical_spec.md)
(portal / archive / chat).

## Normative Source

This document is the single normative AWS/on-prem parity contract. Historical
Wave 1–3 planning notes were removed after runtime parity landed on `main`.

## Operator Runbooks

Category index: [`../operations/README.md`](../operations/README.md).

| Category | Guide |
| --- | --- |
| Deployment | [`../operations/deployment/DEPLOYMENT_IMAGE_STEPS.md`](../operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) |
| Platform | [`../operations/platform/CAPABILITY_PROFILES.md`](../operations/platform/CAPABILITY_PROFILES.md), [`../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md), [`../operations/platform/MITRE_TTP_OPERATIONS.md`](../operations/platform/MITRE_TTP_OPERATIONS.md), [`../operations/platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](../operations/platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md) |
| Analyst portal | [`../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md) |
| LLM inference | [`../operations/llm/LLM_INFERENCE_OPERATIONS.md`](../operations/llm/LLM_INFERENCE_OPERATIONS.md) |
| RAG / KB | [`../operations/rag/KNOWLEDGE_BASE_OPERATIONS.md`](../operations/rag/KNOWLEDGE_BASE_OPERATIONS.md), [`../operations/rag/RAG_OPERATIONS.md`](../operations/rag/RAG_OPERATIONS.md) |
| Investigation | [`../operations/investigation/SPL_OPERATIONS.md`](../operations/investigation/SPL_OPERATIONS.md), [`../operations/investigation/ELASTICSEARCH_OPERATIONS.md`](../operations/investigation/ELASTICSEARCH_OPERATIONS.md) |
| Integrations | [`../operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](../operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md), [`../operations/integrations/SERVICENOW_OPERATIONS.md`](../operations/integrations/SERVICENOW_OPERATIONS.md) |
| Security | [`../operations/security/SECURITY_OPERATIONS.md`](../operations/security/SECURITY_OPERATIONS.md) |

Testing: [`../testing/TESTING.md`](../testing/TESTING.md).

## Deployment Target (v1)

**Locked deployment target:** Production deployments target **commercial AWS
`us-east-1`**. Templates derive `arn:aws:...` with
`AWS::Partition`; customer-specific account, identity, network, key, model, and
retention values are deployment inputs rather than product forks.

## Locked Runtime Shape

The AWS pipeline uses durable AWS-native processing boundaries:

```text
S3 incoming object -> SQS -> analyzer Lambda -> Bedrock analysis -> versioned S3 reports/case runs
                                      |-> bounded external-action jobs
                                      |-> embed/RAG ingestion queues -> OpenSearch
```

New capabilities remain optional and profile-gated. SQS owns retry and poison
handling; do not add Step Functions or synchronous Lambda-to-Lambda glue where
a durable queue is the natural AWS boundary.

## Diff 1 Contract

Diff 1 adds (Wave 2 portal block):

- `analyst_portal` capability profile parsing and validation in `config.py`.
- Portal/archive/chunk/index runtime settings in `config.env.example` and
  SAM/CloudFormation parameter scaffolding (default-off; no behavior change for
  `core` only).
- This technical spec Wave 2 sections below.

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
- `analyst_portal` (Wave 2; enables case archive, portal API, and Case Q&A per
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

## Commercial AWS RAG Retrieval Contract

The `us-east-1` deployment performs application-managed RAG over one
VPC-only Amazon OpenSearch Service domain. S3 holds approved, versioned source
documents and manifests; OpenSearch holds generated chunks, Titan embeddings,
retrieval metadata, and source provenance.

Rules:

- RAG is default-off.
- Retrieved content is advisory context only and must not be treated as direct
  current-alert evidence.
- Missing or unavailable OpenSearch corpora fail soft by default with
  `RAG_FAILURE_MODE=suppress`.
- `RAG_FAILURE_MODE=fail_closed` raises and causes the Lambda record processing
  path to fail.
- Retrieval is bounded by `RAG_MAX_SNIPPETS` and
  `RAG_CONTEXT_BUDGET_CHARS`.
- JSON output metadata records `rag_status`, `rag_snippet_count`, and optional
  `rag_message`.

The prompt uses a `SOC_OPERATIONAL_CONTEXT` block and explicitly instructs the
model that this context is not observed alert evidence.

Separate indexes isolate current-case chunks, general SOC operational
knowledge, Splunk/SIEM dictionaries, and optional Elasticsearch dictionaries.
The SIEM dictionary grounds SPL generation with approved indexes, sourcetypes,
fields, CIM models, macros, lookups, and examples; it is not direct case
evidence. Application-managed OpenSearch is the commercial production default.
Bedrock Knowledge Bases remain an optional compatibility backend, while S3
Vectors are not a v1 runtime dependency.

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
  under `investigation_query_results` for deterministic enrichment and optional
  interpretation.

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
Wave 3 sections below supersede Wave 2 portal chat items where they conflict.

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

- S3 immutable run envelope under the logical case and processing/run identity;
  the CaseIndex atomically publishes the current `latest_run` pointer while
  preserving prior runs.
- DynamoDB CaseIndex for browse/query metadata and pointers only; no full alert
  payloads or full analysis bodies in DynamoDB.
- S3 remains the canonical evidence/archive store; DynamoDB remains the
  transactional case/status index; OpenSearch is a rebuildable retrieval index.
- Analyzer publishes a durable embed job after the run is committed. The embed
  consumer writes case chunks and embeddings to OpenSearch and transitions
  retrieval status to `ready` or `failed`.
- `finding_id` is the logical case identity. Bucket, full decoded key, object
  version or ETag, and sequencer form the immutable processing identity.
- `CASE_ARCHIVE_FAILURE_MODE=suppress` (default) preserves report output on
  archive/index/embed failure (Decision 5).

### Portal Hosting Contract (Decisions 2, 9, 19, 31, 34)

- Regional API Gateway is the only browser/API front door and uses JWT or
  Lambda authorization. Commercial v1 does not create Lambda Function URLs or
  CloudFront distributions; adding either requires a separate edge-architecture
  and security review.
- The private portal S3 bucket is exposed only through a scoped API Gateway AWS
  service integration for deployed SPA objects.
- Recommended v1 bundle: `CAPABILITY_PROFILES=core,analyst_portal` (Decision 34).
- Portal Lambda has no write permissions to case index, input bucket, writeback
  secrets, or external integrations.

### Portal API And Case Q&A Contract (Decisions 3-4, 7, 11-14, 21-23, 27, 33, 36)

- Read-only portal handler; no case mutations from the portal.
- Pinned-case chat only (`selected_case_id` required on every chat request).
- Per-query hybrid lexical/vector retrieval executes in OpenSearch with required
  deployment/tenant and `case_id` filters. Returned chunks retain canonical S3
  provenance.
- Optional advisory KB context when `rag`, `spl_readonly`, or `elastic_readonly`
  profiles are also enabled (`portal_chat_kb.py`; Decision 12).
- Chat synthesis in `portal_chat.py`; do not import `ttp_analyzer.py`
  (Decision 33).
- Response shapes follow `docs/contracts/portal.openapi.json` and
  `portal_api_models.py` (Pydantic); `pydantic` is pinned in `requirements.txt`
  (Decision 35).
- `archive_notices` on case list and detail; full `chat_dependency_status` when
  `CASE_QA_ENABLED=true` (Decisions 21-22).
- Chat admission is bounded at API Gateway and Lambda reserved concurrency, with
  customer-configured per-user/deployment quotas. The in-process semaphore is
  not treated as a global quota.

### Embedding Contract (Decision 6)

- Chunk and query embeddings: Bedrock Titan (`amazon.titan-embed-text-v2:0`),
  `1024` dimensions with `normalize=true`.
- Do not load local Mixedbread embedder into Lambda.
- Same model at chunk write (embed Lambda) and chat query time (portal Lambda).

### Chat History Contract (Decisions 8, 17)

- Default-off: `CASE_QA_CHAT_HISTORY_ENABLED=false`.
- When enabled: DynamoDB `CHAT_SESSIONS_TABLE` and `CHAT_MESSAGES_TABLE`; portal
  Lambda read/write only.
- When enabled, bounded prior turns are included in synthesis (P3-1).

### Python Dependencies (Decision 35)

- `pydantic` is pinned in `requirements.txt` (shipped with Diff 3).
- Do not deploy `fastapi` or `uvicorn` on the portal Lambda.
- Do not port local ML/RAG stack packages; AWS uses Bedrock for embed and chat.

---

## Wave 3: Runtime Parity (Portal Chat And Analyzer)

On-prem is the source of truth unless noted below.

### Portal Chat Prompt And API Contract

- Bedrock chat synthesis returns **plain Markdown text** in `answer`, not JSON
  from the model.
- External API shape: `answer`, `answer_status`, `session_id` only. **No
  `citations` field** in `ChatResponseModel` or handler responses.
- `answer_status` is **`answered`**, **`unknown`**, or **`refused`** only. Do
  not emit `insufficient_context` in new responses; map legacy stored values at
  read time if needed.
- Prompt builders in `portal_chat.py` mirror on-prem `_build_prompt` and
  `_build_general_knowledge_prompt` (adapted for AWS chunk dicts only).
- Context packaging uses `<CONTEXT_BLOCK>` plus
  `UNTRUSTED_TEXT_JSON: <json.dumps(chunk_text)>` per source. Do not use
  numbered `[1] chunk_id=...` source blocks in prompts.
- General-knowledge fallback follows on-prem `answer_case_chat()` branching when
  `CASE_QA_GENERAL_KNOWLEDGE_ENABLED=true` (default `true` on AWS).
- Post-LLM guards: `sanitize_portal_chat_answer`,
  `synthesized_answer_crosses_action_boundary` -> `refused`,
  `_should_fallback_to_general_knowledge` -> general-knowledge path.
- Advisory KB snippets merge into chat sources before synthesis when `rag`,
  `spl_readonly`, or `elastic_readonly` profiles/flags are on
  (`portal_chat_kb.py`).

### Portal Diagnostics Contract

- `GET /api/diagnostics/chat-readiness` probes chat dependencies and exposes
  `chat_history_enabled`, `general_knowledge_enabled`, and related readiness
  fields per OpenAPI.

### Analyzer Verdict And SOC Context Contract

- `alert_reconciliation.verdict` uses on-prem enum only:
  `likely_benign`, `likely_malicious`, `unknown`.
- Legacy archived AWS values (`likely_true_positive`, `likely_false_positive`)
  map at portal read/list time until cases age out.
- SOC context header format matches on-prem:

```text
SOC_OPERATIONAL_CONTEXT
<retrieved advisory text>
```

When absent:

```text
SOC_OPERATIONAL_CONTEXT
(none)
```

Advisory semantics stay in shared `SOC_CONTEXT_RULES`; do not add AWS-only inline
suffixes on the header line.

### Structured Output Transport And Parsing

- Bedrock Converse (AWS) and OpenAI-compatible HTTP (on-prem) remain
  platform-specific adapters.
- Both paths must produce the same validated analysis dict before
  markdown/report/archive generation: same schema, validators, repair-once
  policy, and fallback behavior.

### Shipped Vs Planned (Post-Wave 3)

| Item | Status |
| --- | --- |
| Waves 1-3 and P3-1 code on `main` | Shipped |
| Real-AWS staging deploy validation | Planned (operator; not in repo) |
| Customer JWT/CORS/DNS/WAF front door | Planned (operator per environment) |
| Case-chunk reranker beyond BM25+vector+RRF | Not planned (parity with on-prem) |
| Freeform analyzer entrypoint on AWS | Not planned (batch structured path only) |

Intentional chat non-goals and SOTA backlog:
[`../../../PORTAL_CHATBOT_CAPABILITY_GAPS.md`](../../../PORTAL_CHATBOT_CAPABILITY_GAPS.md).
