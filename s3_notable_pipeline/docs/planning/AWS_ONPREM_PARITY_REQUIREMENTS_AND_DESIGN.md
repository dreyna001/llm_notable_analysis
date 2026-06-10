# AWS / On-Prem Parity Requirements And Design

## Status

Planning and implementation-input artifact. Architecture decisions 1 through 35
are locked in this document. **Decision 7, Decision 20, Decision 10, and
Decision 26 were amended** for on-prem parity: Aurora Postgres plus pgvector
for Case Q&A search (#1) and inline chunk embed in the analyzer Lambda (#2).
**Decision 2 was amended** for portal hosting: Lambda plus provisioned
concurrency and RDS Proxy (#4). **Decision 28 was amended** for analyzer LLM
defaults (#7): **GPT-5.4 at medium effort** as the v1 default preset, with
**Sonnet 4.6 at medium effort** as the customer-selectable alternate preset
(Decision 28). **Decision 35** locks the v1 deployment target to **AWS
GovCloud (`us-gov-west-1`)**. The technical spec is synced to this document;
code and SAM/CFN templates catch up in Diff 1 onward.

This is the next parity block for `s3_notable_pipeline`. It extends the earlier
parity plan in `docs/planning/AWS_ONPREM_PARITY_PLAN.md`, which covered
capability profiles, HTML reports, Bedrock Knowledge Base RAG, SPL and
Elasticsearch read-only investigation, query-result enrichment, ServiceNow, and
side-effect idempotency.

The remaining major parity gap is the maturity added in
`llm_notable_analysis_onprem_systemd`: the `analyst_portal` capability, case
archive, read-only portal API/UI, and retrieval-bound Case Q&A.

## Goal

Bring `s3_notable_pipeline` as close as practical to the current
`llm_notable_analysis_onprem_systemd` capability surface while preserving the AWS
pipeline shape:

```text
S3 incoming object -> Lambda -> Bedrock analysis -> S3 reports -> optional gated integrations
```

New AWS behavior must be additive, optional, default-off, and AWS-native. The
implementation must not replace the S3 trigger, the Lambda analyzer, the Bedrock
analysis path, or the existing report/writeback flow.

## Current Parity Snapshot

### Already close enough for this block

`s3_notable_pipeline` already has AWS equivalents for the first on-prem parity
wave:

- `CAPABILITY_PROFILES` with `core`, `html_reports`, `rag`, `spl_readonly`,
  `elastic_readonly`, `ticket_draft`, and `action_gated`.
- Bounded gzip S3 intake with `MAX_DECOMPRESSED_INPUT_BYTES`.
- Bedrock base analysis with validated structured output and one repair path.
- Bedrock Knowledge Base retrieval for general advisory RAG.
- SPL generation, SPL grounding, and bounded read-only Splunk REST/MCP
  investigation.
- Elasticsearch Query DSL generation, grounding, and bounded read-only `_search`
  investigation.
- Deterministic query-result enrichment and optional query-result interpretation.
- ServiceNow draft and approval-gated create.
- DynamoDB idempotency for external side effects.
- AWS operations docs for the existing shipped parity features.

Do not rework those features in this block except where the archive or portal
needs a stable artifact or metadata contract from them.

### Not yet on par

AWS does not yet have the on-prem `analyst_portal` profile surface:

- no first-class case archive write after successful analysis
- no canonical case envelope separate from the per-run JSON report
- no DynamoDB or other case index for list/filter/pagination
- no read-only portal API equivalent to the on-prem FastAPI service
- no AWS operations guide for archive, portal, and Case Q&A ownership
- no Aurora Postgres case-chunk index for retrieval-bound Case Q&A
- no IAM split between analyzer writer permissions and portal reader permissions

This document is scoped to those gaps.

## Scope Contract

### In scope

- Add an AWS `analyst_portal` capability profile matching the on-prem operator
  semantics as closely as AWS permits.
- Add a case archive write path after successful analysis using S3 case envelopes
  plus a DynamoDB case index.
- Preserve existing markdown, JSON, and optional HTML report outputs under
  `reports/`.
- Add a read-only portal API using API Gateway plus a separate portal Lambda
  handler, with a long-timeout chat integration as defined in Decision 19.
- Reuse the on-prem analyst portal React UI unchanged in layout and behavior;
  host it on S3 plus CloudFront with JWT browser auth and a configurable API
  base URL.
- Add selected-case, retrieval-bound Case Q&A using Bedrock answer synthesis over
  retrieved case/archive sources. Portal chat requires a pinned case; cross-case
  archive search is out of scope for v1 on both AWS and on-prem.
- Add AWS runtime config, SAM/CloudFormation parameters, IAM, VPC/Aurora wiring,
  docs, and tests for archive and portal behavior.
- Keep unit tests deterministic with mocked AWS, Bedrock, and HTTP clients.

### Out of scope

- Replacing the S3/Lambda/Bedrock analyzer with Step Functions, ECS, or a long
  running web service.
- Moving existing analyzer orchestration into the portal API.
- Making the portal a write path for cases, notes, reruns, Splunk searches,
  ServiceNow creates, SOAR playbooks, suppressions, or remediation.
- Enterprise archive hardening: multi-tenant RBAC, legal hold, deterministic
  audit export, large-scale full-text search, eDiscovery, or long-retention case
  warehouse semantics.
- OpenSearch Serverless or Bedrock Knowledge Base ingestion for v1 case-chunk
  retrieval unless a later approved requirement proves Aurora Postgres plus
  pgvector is insufficient.
- Running the on-prem FastAPI portal service literally on EC2/ECS instead of
  the portal Lambda shape.
- Copying the on-prem FastAPI/Postgres implementation into AWS literally.
- Adding new Python dependencies by default.
- Live AWS, Bedrock, Splunk, Elastic, ServiceNow, or IdP calls in unit tests.

## Design Principles

### Preserve the AWS shape

The analyzer Lambda remains the writer for new case archive records. The portal
is a separate read-only surface. This mirrors the on-prem split between the
systemd analyzer and `notable-portal.service` without turning AWS into a Linux
host model.

### Use AWS-native substitutions only where needed

| On-prem surface | AWS parity surface |
| --- | --- |
| Postgres `notable_cases.cases` | S3 canonical case envelope plus DynamoDB metadata index |
| Postgres `case_chunks` with pgvector | Aurora Postgres `notable_cases.case_chunks` with GIN FTS plus HNSW pgvector; portal runs the same hybrid SQL retrieval as on-prem `case_chat.py` |
| FastAPI portal bound to loopback | API Gateway plus portal Lambda with provisioned concurrency and RDS Proxy to Aurora; chat via Function URL (Decisions 2, 19) |
| nginx auth and trusted user header | JWT authorizer plus browser bearer token; IAM second-best |
| on-prem BGE embedder in app code | Bedrock `amazon.titan-embed-text-v2:0` at chunk write and query |
| on-prem optional BGE reranker | Bedrock rerank API (`cohere.rerank-v3-5:0`, Amazon fallback) |
| local vLLM/LiteLLM answer synthesis | Bedrock model invocation scoped to portal Q&A only |
| filesystem report paths | S3 report and case object keys |

Second-best portal hosting option: internal ALB plus ECS/Fargate portal service.
Use it only if a customer requires ECS for internal web tools; it is heavier
than the v1 serverless path and not the default implementation.

### Keep the source of truth explicit

For AWS v1, the canonical archive body is the S3 case envelope. DynamoDB stores
queryable metadata, pointers, and lifecycle fields only. Do not store full alert
payloads or full model analysis in DynamoDB unless a later technical spec
approves it.

### Keep Q&A retrieval-bound

The portal Q&A endpoint may synthesize an answer only from retrieved case
envelope content, case chunks, report snippets, and approved advisory context.
It must cite sources and return `unknown` or a no-match answer when retrieval is
weak. It must not answer from broad model memory.

### Keep failure behavior visible

Archive and portal failures must not silently disappear. Every skipped, denied,
failed, or partial path needs structured status in logs and, where appropriate,
in the S3 report JSON metadata.

## Locked Architecture

### Write path

```text
S3 incoming object
-> analyzer Lambda
-> parse and normalize input
-> Bedrock analysis and optional parity enrichments
-> validate structured output
-> render markdown, JSON, optional HTML reports
-> when CASE_ARCHIVE_ENABLED=true, write case envelope to S3
-> when CASE_ARCHIVE_ENABLED=true, upsert case metadata into DynamoDB CaseIndex
-> when CASE_ARCHIVE_ENABLED=true, upsert Aurora notable_cases.cases parent row
   with retrieval_status=pending
-> when CASE_ARCHIVE_ENABLED=true, inline post-archive chunk embed in the same
   analyzer Lambda invocation (Decision 10)
   -> Bedrock Titan Embed writes Aurora Postgres case_chunks rows
   -> Postgres cases.retrieval_status and CaseIndex retrieval_status transition
      pending -> ready|failed before the analyzer returns
-> optional gated Splunk/ServiceNow side effects
```

Archive writes run after the validated analysis object exists and after report
object keys are known. The archive must never require parsing markdown or HTML.
Chunk embedding runs inline in the analyzer completion path, matching on-prem
`archive_case_for_portal()` -> `store_case_chunks()` timing. Deployments with
`CASE_ARCHIVE_ENABLED=true` must use analyzer Lambda timeout and memory sized
for analysis plus bounded chunk embed (recommended starting point when
`analyst_portal` is enabled: `900` seconds and `1024` MB, tuned from
CloudWatch).

### Read path

```text
Analyst/browser/client
-> API Gateway authorizer
-> portal Lambda
-> DynamoDB CaseIndex query or GetItem
-> S3 GetObject for selected case/report objects
-> bounded JSON response
```

The portal Lambda has no write permissions to the case index, input bucket,
writeback secrets, ServiceNow, Splunk, Elastic, or SOAR.

### Case Q&A path

```text
question
-> authenticated portal API
-> lexical + vector + RRF retrieval over Aurora Postgres case_chunks (ported
   on-prem SQL from case_chat.py)
-> optionally retrieve advisory KB context when capability flags allow
-> Bedrock answer synthesis with internal citation validation
-> on-prem chat response shape: answer, answer_status, session_id
```

Case Q&A supports pinned-case chat only (`selected_case`), matching on-prem.
Every chat request requires `selected_case_id`. General technology / TTP answers
still use `CASE_QA_GENERAL_KNOWLEDGE_ENABLED` and optional advisory KB context;
they do not search other archived cases.

## Runtime Contract Additions

Add these settings to `config.env.example`, `config.py`, `template-sam.yaml`,
`template-cfn.yaml`, operations docs, and tests in the same implementation
slices.

```env
BEDROCK_ANALYZER_MODEL_PRESET=gpt-5.4-medium
BEDROCK_MANTLE_REGION=
CASE_ARCHIVE_ENABLED=false
CASE_ARCHIVE_FAILURE_MODE=suppress
CASE_ARCHIVE_BUCKET=
CASE_ARCHIVE_PREFIX=cases
CASE_INDEX_TABLE=
CASE_POSTGRES_DSN=
CASE_POSTGRES_SECRET_ARN=
CASE_POSTGRES_SCHEMA=notable_cases
CASE_POSTGRES_STATEMENT_TIMEOUT_MS=5000
CASE_ARCHIVE_WRITE_MAX_ATTEMPTS=3
CASE_RETENTION_DAYS=30
CASE_SCHEMA_VERSION=1
CASE_ANALYSIS_SCHEMA_VERSION=1
CASE_ARCHIVE_MAX_ALERT_BYTES=262144
CASE_ARCHIVE_MAX_ANALYSIS_BYTES=524288

PORTAL_ENABLED=false
PORTAL_AUTH_MODE=jwt
PORTAL_PAGE_SIZE=50
PORTAL_MAX_DETAIL_BYTES=262144
PORTAL_JWT_ISSUER=
PORTAL_JWT_AUDIENCE=
PORTAL_CORS_ALLOWED_ORIGINS=
PORTAL_CHAT_TIMEOUT_SEC=300
PORTAL_CHAT_FUNCTION_URL_ENABLED=true
PORTAL_CHAT_MAX_CONCURRENCY=4
PORTAL_LAMBDA_PROVISIONED_CONCURRENCY=2
PORTAL_CHAT_BEDROCK_MODEL_ID=
CASE_POSTGRES_RDS_PROXY_ENDPOINT=

CASE_QA_ENABLED=false
CASE_QA_GENERAL_KNOWLEDGE_ENABLED=true
CASE_QA_MAX_INDEX_CHUNKS_PER_CASE=200
CASE_QA_MAX_CHUNKS_PER_LANE=6
CASE_QA_MAX_TOTAL_CHUNKS=18
CASE_QA_LEXICAL_TOP_K=30
CASE_QA_VECTOR_TOP_K=30
CASE_QA_RRF_K=60
CASE_QA_CONTEXT_BUDGET_CHARS=12000
CASE_QA_MAX_QUESTION_CHARS=2000
CASE_QA_MAX_ANSWER_TOKENS=800
CASE_QA_EMBEDDING_MODEL=amazon.titan-embed-text-v2:0
CASE_QA_VECTOR_DIMENSIONS=1024
CASE_QA_EMBED_NORMALIZE=true
CASE_QA_CHAT_HISTORY_ENABLED=false
CASE_QA_CHAT_HISTORY_RETENTION_DAYS=30
CASE_QA_MAX_SESSIONS_PER_USER=10
CASE_QA_MAX_MESSAGES_PER_SESSION=30
CASE_QA_MAX_STORED_MESSAGE_BYTES=4000
CHAT_SESSIONS_TABLE=
CHAT_MESSAGES_TABLE=

RAG_RERANK_ENABLED=false
RAG_RERANK_MODEL=cohere.rerank-v3-5:0
RAG_RERANK_MODEL_FALLBACK=amazon.rerank-v1:0
```

Profile behavior:

- `analyst_portal` enables `CASE_ARCHIVE_ENABLED`, `PORTAL_ENABLED`, and
  `CASE_QA_ENABLED`.
- `analyst_portal` does not enable `HTML_REPORT_ENABLED`.
- `analyst_portal` does not enable Splunk, Elasticsearch, ServiceNow, SOAR, or
  any external write/action path.
- `core` remains the default and must preserve current behavior exactly.

Validation rules:

- Unknown capability profiles fail startup validation.
- `CASE_RETENTION_DAYS` must be positive and bounded.
- `CASE_ARCHIVE_FAILURE_MODE` must be `suppress` or `fail_closed`.
- `CASE_INDEX_TABLE` is required when `CASE_ARCHIVE_ENABLED=true` or
  `PORTAL_ENABLED=true`.
- `CASE_POSTGRES_DSN` or `CASE_POSTGRES_SECRET_ARN` is required when
  `CASE_ARCHIVE_ENABLED=true` or `CASE_QA_ENABLED=true`.
- `CASE_ARCHIVE_BUCKET` defaults to `OUTPUT_BUCKET_NAME` when unset.
- `PORTAL_AUTH_MODE` must be `jwt` or `iam`.
- `PORTAL_JWT_ISSUER` and `PORTAL_JWT_AUDIENCE` are required when
  `PORTAL_AUTH_MODE=jwt`.
- `CASE_QA_ENABLED=true` requires `PORTAL_ENABLED=true`.
- `selected_case` chat mode requires `selected_case_id` in the request payload.
- `CASE_QA_CHAT_HISTORY_ENABLED=true` requires `CHAT_SESSIONS_TABLE` and
  `CHAT_MESSAGES_TABLE`.
- `CASE_QA_VECTOR_DIMENSIONS` must match the configured Titan embed output size.
- `PORTAL_CHAT_MAX_CONCURRENCY` must be a positive integer, default `4`, max `64`.
- `PORTAL_LAMBDA_PROVISIONED_CONCURRENCY` must be a non-negative integer,
  default `2`, max `64`. Set `0` only in lab environments that accept cold
  starts. When `PORTAL_ENABLED=true`, provisioned concurrency must be less than
  or equal to the portal Lambda account concurrency headroom.
- `CASE_POSTGRES_RDS_PROXY_ENDPOINT` is required when `PORTAL_ENABLED=true` or
  `CASE_ARCHIVE_ENABLED=true`. Analyzer and portal Lambdas connect to Aurora
  through RDS Proxy, not direct cluster endpoints.
- `BEDROCK_ANALYZER_MODEL_PRESET` must be `gpt-5.4-medium` or
  `sonnet-4.6-medium` (Decision 28). Default `gpt-5.4-medium`.
- When `BEDROCK_ANALYZER_MODEL_PRESET=gpt-5.4-medium`, the analyzer uses Bedrock
  Mantle OpenAI Responses API with model ID `openai.gpt-5.4` and
  `reasoning.effort=medium`. Bedrock-supported efforts are `minimal`, `low`,
  `medium`, and `high`; `xhigh` is not available on Bedrock.
- When `BEDROCK_ANALYZER_MODEL_PRESET=sonnet-4.6-medium`, the analyzer uses
  Bedrock Runtime Converse with the regional Sonnet 4.6 inference profile,
  `thinking.type=adaptive`, and `output_config.effort=medium`. `max` effort is
  not valid for Sonnet on Bedrock.
- `BEDROCK_MANTLE_REGION` defaults to `us-gov-west-1` for v1 GovCloud
  deployments (Decision 35). It must match a region where `openai.gpt-5.4` is
  available on Bedrock Mantle when the GPT preset is selected.
- Explicit `BEDROCK_MODEL_ID` override remains supported for operator
  experiments (Haiku, Nova, Opus, legacy Sonnet 4.5). Overrides must document
  the matching API path (Mantle Responses vs Converse) and effort settings in
  operator runbooks; preset validation may be bypassed only when override is
  non-empty.
- `PORTAL_CHAT_BEDROCK_MODEL_ID` is optional; when set, it must be non-empty and
  is used only for portal answer synthesis (Decision 29).
- `RAG_RERANK_MODEL_FALLBACK` is used only when the primary rerank model is
  unavailable in the deployment region.

## Case Envelope Contract

Write one JSON envelope per completed case:

```text
s3://{CASE_ARCHIVE_BUCKET}/{CASE_ARCHIVE_PREFIX}/{yyyy}/{mm}/{dd}/{case_id}.json
```

Required top-level shape:

```json
{
  "case_schema_version": 1,
  "analysis_schema_version": 1,
  "case_id": "string",
  "finding_id": "string",
  "source": {
    "input_bucket": "string",
    "input_key": "string",
    "source_filename": "string",
    "content_type": "json|text",
    "was_compressed": false
  },
  "processed_at": "UTC ISO-8601 string",
  "expires_at": "UTC ISO-8601 string",
  "correlation_id": "string",
  "capability_snapshot": {},
  "artifacts": {
    "report_markdown_key": "reports/example.md",
    "report_json_key": "reports/example.json",
    "report_html_key": "reports/example.html"
  },
  "archive_metadata": {
    "source_completeness": "complete|missing_alert|missing_analysis|markdown_only",
    "retrieval_status": "pending|ready|failed|not_indexed",
    "archive_failure_mode": "suppress|fail_closed"
  },
  "alert_payload": {},
  "analysis": {}
}
```

Rules:

- `case_id` is deterministic from the validated payload identifier when present,
  otherwise from the S3 source key stem.
- `finding_id` follows the same validation used for Splunk writeback.
- `processed_at` and `expires_at` are UTC.
- `alert_payload` is the normalized alert payload, not prompt text.
- `analysis` is the validated structured analysis object used for reports.
- Oversized `alert_payload` or `analysis` values must be bounded by config and
  marked through `source_completeness`; do not silently truncate without
  metadata.
- Full raw model text should not be archived unless it is already part of the
  existing validated report JSON contract and is explicitly bounded.

## Aurora Postgres Case Archive Contract

When `CASE_ARCHIVE_ENABLED=true` or `CASE_QA_ENABLED=true`, provision Aurora
Postgres (Serverless v2 or provisioned) with the `vector` and `pg_trgm`
extensions. Port the on-prem schema from
`llm_notable_analysis_onprem_systemd/deploy/postgres/notable_cases_schema.sql`
with these AWS-specific adjustments:

- `case_chunks.embedding` uses `vector(1024)` to match Bedrock Titan V2 (Decision
  6), not on-prem `vector(768)`.
- Schema name defaults to `notable_cases` via `CASE_POSTGRES_SCHEMA`.
- Lambdas that read or write case archive data run in the same VPC subnets as
  Aurora with security groups that allow Postgres traffic only from analyzer and
  portal Lambda security groups.

**`notable_cases.cases` table** (retrieval and archive metadata mirror):

- Holds the same core columns as on-prem for browse joins, retrieval gating, and
  retention: `case_id`, `finding_id`, `source_filename`, `processed_at`,
  `expires_at`, `correlation_id`, `verdict`, `confidence`, `search_name`,
  `risk_score`, `retrieval_status`, `source_completeness`, `capability_snapshot`,
  `archive_metadata`, `alert_payload`, `analysis`, artifact path fields, and
  schema version columns.
- `retrieval_status` follows the same enum as on-prem and DynamoDB CaseIndex.
- Retention deletes use bounded batch deletes aligned to `CASE_RETENTION_DAYS`.

**`notable_cases.case_chunks` table** (indexed retrieval store):

- One row per chunk with the same shape as on-prem: `chunk_id`, `case_id`,
  `source_lane`, `section`, `field_path`, `text`, `embedding`, generated
  `search_vector` tsvector, `metadata`, `chunk_schema_version`,
  `embedding_model`.
- Required indexes (match on-prem):
  - `case_chunks_case_id_idx`
  - `case_chunks_search_vector_gin_idx` (GIN on `search_vector`)
  - `case_chunks_embedding_hnsw_idx` (HNSW on `embedding vector_cosine_ops`)

Chunk rules:

- Port on-prem `build_chunk_id()` and chunk citation metadata from `case_search.py`.
- Re-embed deletes all `case_chunks` rows for the case before rewrite.
- Titan embeddings are L2-normalized at write; dimensions must match
  `CASE_QA_VECTOR_DIMENSIONS`.
- Stop deterministically at `CASE_QA_MAX_INDEX_CHUNKS_PER_CASE` before embedding.

Case Q&A retrieval rules:

- Portal Lambda runs the same hybrid retrieval as on-prem `case_chat.py`:
  parameterized Postgres FTS up to `CASE_QA_LEXICAL_TOP_K`, pgvector similarity
  up to `CASE_QA_VECTOR_TOP_K`, merge with `_merge_rrf` using `CASE_QA_RRF_K`.
- Scope retrieval to the pinned `selected_case_id` only.
- Do not load all case chunks into Lambda memory for scoring.
- Do not use OpenSearch, Kendra, or Bedrock Knowledge Base for case-archive
  retrieval.

Dual-write consistency:

- S3 case envelope remains the durable full-fidelity artifact for detail reads.
- DynamoDB CaseIndex remains the v1 case-list index for portal pagination.
- Aurora `notable_cases.cases` holds retrieval gating columns and chunk FK
  parent rows; keep `retrieval_status` in sync with CaseIndex on embed completion
  or failure.

## DynamoDB CaseIndex Contract

Create a DynamoDB table for metadata and portal queries.

Table:

- Name: configured by `CASE_INDEX_TABLE`.
- Primary key: `case_id` string.
- TTL attribute: `expires_at_epoch`.
- GSI `ProcessedAtIndex`:
  - partition key: `archive_partition` string, default `default`
  - sort key: `processed_at_case_id` string, formatted
    `{processed_at}#{case_id}`
- Do not add `VerdictProcessedAtIndex` in v1 (Decision 32). Verdict filtering uses
  `ProcessedAtIndex` queries plus portal-side filtering until scale proves otherwise.

Each item contains only metadata and pointers:

- `case_id`
- `finding_id`
- `archive_partition`
- `processed_at`
- `processed_at_case_id`
- `expires_at`
- `expires_at_epoch`
- `verdict`
- `confidence`
- `search_name`
- `risk_score`
- `source_filename`
- `source_key`
- `case_envelope_key`
- `report_markdown_key`
- `report_json_key`
- `report_html_key`
- `capability_snapshot`
- `source_completeness`
- `retrieval_status`

Rules:

- Use conditional writes for first insert and deterministic updates for replay.
- Treat a replay as the same case when at least one of these is true:
  `source_filename` matches, non-empty `correlation_id` matches, or non-empty
  `finding_id` matches (port on-prem identity contract).
- If `case_id` already exists but source identity does not match, suppress the
  archive update: log the conflict, leave the existing row and envelope
  unchanged, and do not overwrite an unrelated case (Decision 25).
- Replayed S3 events for the same case must be idempotent.
- DynamoDB TTL is best-effort expiration; S3 lifecycle remains the artifact
  deletion mechanism.
- Partial failure after S3 case envelope write but before index write must be
  visible in logs. If `CASE_ARCHIVE_FAILURE_MODE=fail_closed`, fail the Lambda
  record so S3 event retry can repair the index.

## DynamoDB Chat History Contract

Create two DynamoDB tables when `CASE_QA_CHAT_HISTORY_ENABLED=true`. This is the
AWS equivalent of on-prem Postgres `chat_sessions` and `chat_messages`.

**ChatSessions table** (`CHAT_SESSIONS_TABLE`):

- Primary key: `session_id` string.
- Attributes: `user_id`, `mode`, `selected_case_id`, `created_at`, `updated_at`,
  `expires_at`, `expires_at_epoch`.
- TTL attribute: `expires_at_epoch`.
- Global secondary index `UserUpdatedIndex`:
  - partition key: `user_id`
  - sort key: `updated_at_session_id` formatted `{updated_at}#{session_id}`

**ChatMessages table** (`CHAT_MESSAGES_TABLE`):

- Primary key: `session_id` string.
- Sort key: `created_at_message_id` formatted `{created_at}#{message_id}`.
- Attributes: `message_id`, `role`, `content`, `answer_status`, `cited_sources`,
  `expires_at_epoch` (copied from parent session for TTL cleanup).

Rules:

- Portal Lambda has read/write access only when chat history is enabled.
- Analyzer Lambda has no chat-history permissions.
- Retention, per-user session caps, and per-session message caps match on-prem
  config semantics.
- When chat history is disabled, chat session routes return the same empty or
  disabled responses as on-prem.

## AWS Storage Summary

| Service | Data |
| --- | --- |
| S3 | Incoming notables, reports, canonical case envelopes |
| Aurora Postgres | `notable_cases.cases` and `notable_cases.case_chunks` for retrieval-bound Case Q&A |
| DynamoDB CaseIndex | Case browse metadata and pointers only |
| DynamoDB ChatSessions / ChatMessages | Optional portal chat history |
| S3 plus CloudFront | Static analyst portal UI assets |

## Portal API Contract

The read-only API should be a separate Lambda handler, not the analyzer handler.
The HTTP contract must match on-prem
`llm_notable_analysis_onprem_systemd/frontend/analyst-portal/openapi/portal.openapi.json`
and `onprem_service/portal_api_models.py`. Do not invent alternate field names
for the browser UI.

Routes:

| Route | Method | Purpose |
| --- | --- | --- |
| `/health` | `GET` | Liveness, no sensitive metadata |
| `/ready` | `GET` | DynamoDB, S3, and Aurora Postgres readiness check |
| `/api/capabilities` | `GET` | Enabled portal flags, retention, limits |
| `/api/diagnostics/chat-readiness` | `GET` | Optional chat dependency probe |
| `/api/cases` | `GET` | Paginated case list |
| `/api/cases/{case_id}` | `GET` | Bounded case detail from S3 envelope |
| `/api/cases/{case_id}/raw/{section}` | `GET` | Bounded raw `alert_payload` or `analysis` section |
| `/api/chat` | `POST` | Retrieval-bound Q&A |
| `/api/chat/sessions` | `GET` | List chat sessions when history enabled |
| `/api/chat/sessions/{session_id}/messages` | `GET` | Load one session |
| `/api/chat/sessions/{session_id}` | `DELETE` | Delete one session |
| `/api/chat/sessions/{session_id}/turns/last` | `DELETE` | Delete last user/assistant turn |

Rules:

- No mutating case routes exist.
- `POST /api/chat` is allowed only as query transport and must not write case
  state.
- Reject unknown methods with a generic 405.
- Case list supports cursor pagination, UTC date filters, verdict filter, and
  optional `search_name` filter.
- Date filters use UTC calendar days end-to-end.
- Detail responses omit or bound oversized fields and return `content_bounds`
  metadata plus raw-section links.
- Raw section reads are paginated by top-level key and max byte budget.
- Portal responses must not expose input bucket objects.
- Case detail uses on-prem field names `report_md_path` and `report_html_path`
  at the API boundary. Map internal S3 artifact keys to those response fields.
- FastAPI-style error bodies with a top-level `detail` string must be preserved
  for UI error handling.

Authentication:

- `PORTAL_AUTH_MODE=jwt` is the v1 default because analysts may not have AWS
  accounts. Use enterprise OIDC through API Gateway JWT authorizers in production
  (Decision 30). Cognito is a supported lab/small-team configuration example,
  not a required SAM resource.
- Browser clients cannot use AWS IAM credentials. The reused on-prem React UI
  must send `Authorization: Bearer <jwt>` on API calls instead of on-prem nginx
  proxy headers.
- `PORTAL_AUTH_MODE=iam` is the second-best path for AWS-admin, lab, or
  machine-to-machine access where callers already have AWS identities.
- Anonymous public portal access is never valid.
- The portal Lambda must validate identity claims from API Gateway or, for the
  chat Function URL path, directly from JWT, and log only stable, non-secret
  identity metadata.

CORS and routing:

- CloudFront serves the static SPA from S3.
- API requests from the browser target the configured API base URL.
- `PORTAL_CORS_ALLOWED_ORIGINS` must include the CloudFront distribution
  origin(s).
- Locked v1 routing (Decision 31):
  - CloudFront default behavior -> S3 for static UI assets.
  - CloudFront `/api/chat` and `/api/chat/*` -> portal Lambda Function URL for
    long-running chat (Decision 19).
  - CloudFront `/api/*` -> API Gateway for standard portal routes.
  - Local dev may call API Gateway or Function URL directly without CloudFront.
- Local development may keep the on-prem Vite proxy pattern; production builds
  use `VITE_PORTAL_API_BASE_URL`.

## Case Q&A Contract

`CASE_QA_ENABLED` enables a bounded answer-synthesis step from the portal API.

Supported chat mode (matches on-prem):

| Mode | Requires | Retrieval scope |
| --- | --- | --- |
| `selected_case` | `selected_case_id` | pinned case envelope and case chunks only, plus optional advisory KB context |

Allowed inputs to the model:

- the analyst question
- authenticated user metadata needed for audit, not authorization decisions
- selected case envelope fields
- bounded case chunks or report snippets from the active mode
- optional approved advisory context when the corresponding capability flags are
  enabled (`rag`, `spl_readonly`, `elastic_readonly`), using Bedrock KB retrieve
  and the same grounding semantics as on-prem portal chat

The model is allowed to:

- summarize the selected case
- answer questions about the selected case or bounded retained archive matches
- point to cited case/report sections
- explain when evidence is insufficient

The model is not allowed to:

- invent source facts
- answer from broad model memory
- change case state
- execute SPL or Elasticsearch queries
- call Splunk, ServiceNow, SOAR, or AWS write APIs
- decide authorization
- override deterministic verdict, confidence, query status, or source metadata

External response shape (must match on-prem UI contract):

```json
{
  "answer": "string",
  "answer_status": "answered|unknown|refused",
  "session_id": "string|null"
}
```

Internal validation rules before mapping to `answer_status`:

- Retrieved sources must be bounded and citation-checked inside the portal
  Lambda before answer synthesis.
- Unknown, malformed, or uncited model output gets one repair attempt.
- If repair fails, return `answer_status=unknown` with the on-prem insufficient
  archive message, not a malformed model answer.
- `CASE_QA_GENERAL_KNOWLEDGE_ENABLED=true` follows on-prem fallback semantics:
  empty retrieval or the on-prem insufficient-archive phrase may trigger a
  bounded general-knowledge answer.
- Cited sources may be persisted in chat history when enabled, but are not
  required in the external chat response payload.

## IAM Requirements

Analyzer Lambda role (always, for notable analysis):

- When `BEDROCK_ANALYZER_MODEL_PRESET=gpt-5.4-medium`: Mantle OpenAI Responses
  invoke permission for `openai.gpt-5.4` in `BEDROCK_MANTLE_REGION`.
- When `BEDROCK_ANALYZER_MODEL_PRESET=sonnet-4.6-medium` or explicit Sonnet
  `BEDROCK_MODEL_ID`: `bedrock:InvokeModel` on the Sonnet 4.6 inference profile.

Analyzer Lambda role additions when `CASE_ARCHIVE_ENABLED=true`:

- `s3:PutObject` on `cases/` in the archive bucket.
- `s3:GetObject` only where needed to read existing report objects for chunk
  construction.
- `dynamodb:PutItem`, `dynamodb:UpdateItem`, and `dynamodb:GetItem` on
  `CASE_INDEX_TABLE`.
- VPC access to Aurora Postgres through **RDS Proxy** for case-chunk read/write
  during inline embed. Do not connect directly to the Aurora cluster endpoint.
- `bedrock:InvokeModel` on `CASE_QA_EMBEDDING_MODEL` for inline chunk embed.
- `secretsmanager:GetSecretValue` on `CASE_POSTGRES_SECRET_ARN` when configured.
- No portal read API permissions or chat-history permissions on the analyzer role.
- No separate post-archive embed Lambda invoke permission.

Portal Lambda role:

- `dynamodb:Query` on `ProcessedAtIndex`.
- `dynamodb:GetItem` on `CASE_INDEX_TABLE`.
- `s3:GetObject` on `cases/` and `reports/` prefixes needed for portal rendering.
- VPC access to Aurora Postgres through **RDS Proxy** read-only for case-chunk
  hybrid retrieval and chat readiness probes when `CASE_QA_ENABLED=true`.
- `secretsmanager:GetSecretValue` on `CASE_POSTGRES_SECRET_ARN` when configured.
- `bedrock:InvokeModel` for answer synthesis when `CASE_QA_ENABLED=true`.
- `bedrock:InvokeModel` on `CASE_QA_EMBEDDING_MODEL` for query embedding.
- `bedrock:Retrieve` on configured Knowledge Bases when advisory context flags
  are enabled.
- `bedrock:Rerank` or equivalent rerank API permission only when
  `RAG_RERANK_ENABLED=true`.
- DynamoDB read/write on `CHAT_SESSIONS_TABLE` and `CHAT_MESSAGES_TABLE` only
  when `CASE_QA_CHAT_HISTORY_ENABLED=true`.
- No `s3:GetObject` on the input bucket.
- No `s3:PutObject`, `dynamodb:PutItem` on `CASE_INDEX_TABLE`,
  `secretsmanager:GetSecretValue` for Splunk/ServiceNow, or external writeback
  permissions.

## Deployment Requirements

- Update both `deploy/aws/template-sam.yaml` and
  `deploy/aws/template-cfn.yaml` together.
- Create the DynamoDB CaseIndex table conditionally when archive or portal
  support is enabled by deployment parameter.
- Provision Aurora Postgres with pgvector when `analyst_portal` archive or Case
  Q&A is enabled. Provision **RDS Proxy** in the same VPC for analyzer and
  portal Lambda database access.
- Document VPC subnets, security groups, Secrets Manager DSN injection, RDS Proxy
  endpoint wiring, optional VPC interface endpoints for AWS APIs (GovCloud /
  FedRAMP egress reduction), and operator migration/bootstrap from
  `notable_cases_schema.sql`.
- Attach analyzer and portal Lambdas to the Aurora VPC when archive or Case Q&A
  is enabled.
- Configure portal Lambda **provisioned concurrency** from
  `PORTAL_LAMBDA_PROVISIONED_CONCURRENCY` when `PORTAL_ENABLED=true`.
- Add S3 lifecycle configuration for `cases/` prefix aligned to
  `CASE_RETENTION_DAYS`.
- Keep current `core` deployment parameters valid.
- Keep `scripts/test-pipeline.ps1` a core smoke test by default.
- Add optional archive/portal smoke validation steps that require explicit
  parameters and never assume live AWS credentials in unit tests.
- Do not require Step Functions, ECS, OpenSearch, Cognito, CloudFront, or a
  separate embed Lambda for the first archive write slice. Aurora Postgres is
  required for the Case Q&A retrieval slice (Diff 2 onward).

## Planned Diff Sequence

### Diff 1: Config, profile, and technical spec

Objective:

- Add `analyst_portal` profile parsing and runtime config validation.
- Add this block to the AWS technical spec.
- Add deployment parameters without changing default runtime behavior.

Files:

- `src/s3_notable_pipeline/config.py`
- `config.env.example`
- `deploy/aws/template-sam.yaml`
- `deploy/aws/template-cfn.yaml`
- `docs/technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md`
- `docs/operations/CAPABILITY_PROFILES.md`
- `tests/test_config.py`

Acceptance criteria:

- `CAPABILITY_PROFILES=core` behavior is unchanged.
- `CAPABILITY_PROFILES=core,analyst_portal` validates when required archive,
  Aurora, and CaseIndex settings are present.
- Invalid auth mode, retention, table names, embed dimensions, chat-history
  table config, or unknown `BEDROCK_ANALYZER_MODEL_PRESET` fails fast.

### Diff 2: Case archive, inline chunk embed, and Aurora index writer

Objective:

- Write canonical S3 case envelopes, DynamoDB CaseIndex metadata, Aurora
  `notable_cases.cases` parent rows, and inline Bedrock chunk embed to Aurora
  `notable_cases.case_chunks` from the analyzer Lambda in one completion path.

Files:

- `src/s3_notable_pipeline/case_archive.py`
- `src/s3_notable_pipeline/case_embed.py`
- `src/s3_notable_pipeline/case_postgres.py`
- `src/s3_notable_pipeline/lambda_handler.py`
- `src/s3_notable_pipeline/aws_clients.py`
- `deploy/postgres/notable_cases_schema_aws.sql` (ported schema; `vector(1024)`)
- `deploy/aws/template-sam.yaml`
- `deploy/aws/template-cfn.yaml`
- `tests/test_case_archive.py`
- `tests/test_case_embed.py`
- `tests/test_lambda_handler.py`

Acceptance criteria:

- Archive is skipped when disabled.
- Archive writes do not parse markdown or HTML.
- Replayed events for the same case are idempotent.
- `CASE_ARCHIVE_FAILURE_MODE=suppress` preserves report output and records
  archive failure status.
- `CASE_ARCHIVE_FAILURE_MODE=fail_closed` fails the Lambda record on archive
  write/index/embed failure.
- Identity collision on an existing `case_id` suppresses the archive write and
  does not fail the completed analysis run.
- Analyzer writes envelope, CaseIndex row, and Postgres parent row with
  `retrieval_status=pending`, then embeds chunks inline and transitions
  `retrieval_status` to `ready` or `failed` before returning.
- Writes one Postgres `case_chunks` row per chunk with Titan embeddings and
  generated `search_vector`.
- Re-embed deletes all `case_chunks` rows for the case before rewrite.
- No separate async embed Lambda is deployed or invoked in v1.

### Diff 3: Read-only portal API Lambda

Objective:

- Add the portal read API over DynamoDB and S3 with no mutating case operations.

Files:

- `src/s3_notable_pipeline/portal_handler.py`
- `src/s3_notable_pipeline/case_index.py`
- `src/s3_notable_pipeline/portal_api_models.py`
- `src/s3_notable_pipeline/case_archive_notices.py` (ported verbatim from on-prem)
- `docs/contracts/portal.openapi.json` (vendored from on-prem)
- `deploy/aws/template-sam.yaml`
- `deploy/aws/template-cfn.yaml`
- `tests/test_portal_handler.py`
- `tests/test_case_index.py`
- `tests/test_case_archive_notices.py`
- `tests/test_portal_openapi_contract.py`

Acceptance criteria:

- `/health`, `/ready`, `/api/capabilities`, `/api/cases`,
  `/api/cases/{case_id}`, and raw section reads return bounded responses.
- Case list and detail include `archive_notices` when archive or indexing is
  degraded (Decision 21).
- When `CASE_QA_ENABLED=true`, `/api/capabilities` exposes full
  `chat_dependency_status` (`embeddings`, `archive_retrieval`, `llm_gateway`)
  and `chat_degraded_reason` via live dependency probes (Decision 22).
- Response shapes match the vendored on-prem OpenAPI contract (Decision 27).
- Portal Lambda reserved concurrency matches `PORTAL_CHAT_MAX_CONCURRENCY`;
  excess chat requests return HTTP 429 with the on-prem message (Decision 23).
- Portal Lambda provisioned concurrency matches
  `PORTAL_LAMBDA_PROVISIONED_CONCURRENCY` when `PORTAL_ENABLED=true`.
- Portal Lambda has no writeback, input-bucket, or case mutation permissions.
- Unauthenticated or malformed auth context fails closed.
- Mutating methods are rejected.
- Case detail assembly lives in `case_index.py` and `portal_handler.py`; no
  separate `portal_case_detail.py` module (Decision 24).

### Diff 4: Pinned-case Q&A

Objective:

- Add retrieval-bound pinned-case Q&A through the portal API.

Files:

- `src/s3_notable_pipeline/case_chat.py` (port hybrid Postgres retrieval from
  on-prem)
- `src/s3_notable_pipeline/case_postgres.py`
- `src/s3_notable_pipeline/portal_handler.py`
- `src/s3_notable_pipeline/portal_chat.py` (Decision 33; no `ttp_analyzer.py`
  import for portal answer synthesis)
- `tests/test_case_chat.py`
- `tests/test_portal_handler.py`

Acceptance criteria:

- Q&A is disabled by default.
- Q&A requires `selected_case_id` and retrieves that case's chunks from Aurora
  Postgres before model invocation.
- Chunk retrieval uses indexed Postgres FTS plus pgvector queries, not in-Lambda
  full-case scans.
- Chunk retrieval requires `retrieval_status=ready`; cases should reach `ready`
  in the same analyzer run under normal success (Decision 26).
- The answer schema is validated and requires citations for answered responses.
- Malformed or uncited model output fails soft to `insufficient_context`.
- The model cannot mutate deterministic case fields or call external tools.

### Diff 5: Portal frontend, operations, and validation

Objective:

- Reuse the on-prem analyst portal UI with AWS-only auth and API wiring.
- Finish operator docs and validation commands.

Files:

- reuse or vendor `llm_notable_analysis_onprem_systemd/frontend/analyst-portal`
  into the AWS deployment path without visual changes
- add `VITE_PORTAL_API_BASE_URL` and JWT bearer support in the portal API client
- `docs/operations/ANALYST_PORTAL_OPERATIONS.md`
- `docs/operations/README.md`
- `docs/operations/FILE_DROP_AND_RETENTION_OPERATIONS.md`
- `docs/operations/SECURITY_OPERATIONS.md`
- `docs/testing/TESTING.md`
- `README.md`
- CloudFront, S3 static hosting, CORS, and chat Function URL deployment assets

Acceptance criteria:

- UI exposes the same three routes as on-prem: `/`, `/cases`, `/cases/{case_id}`.
- Browser auth uses JWT bearer tokens; nginx proxy headers are not required.
- Docs explain profile enablement, IAM, auth mode, Aurora bootstrap, VPC wiring,
  S3 lifecycle, DynamoDB TTL, retention, chat timeout routing, failure behavior,
  and rollback.
- Local tests do not call real AWS.
- Optional real AWS validation is clearly labeled as dev/staging/prod only.

## Testing Strategy

Unit tests:

- config parsing and validation
- case id derivation and finding id validation
- envelope construction and size bounds
- DynamoDB conditional write/replay behavior with fake clients
- archive failure modes
- portal pagination and UTC date filtering
- portal detail/raw response bounding
- `archive_notices` derivation from retrieval status and source completeness
- `chat_dependency_status` readiness probes
- OpenAPI contract shape checks against vendored `portal.openapi.json`
- auth-context rejection paths
- Q&A schema validation, citation enforcement, repair failure, and no-match

Integration tests:

- LocalStack may validate S3 and DynamoDB archive flow.
- Aurora-backed retrieval tests may use a local Postgres/pgvector container in CI
  when explicitly enabled; they must not require live AWS in the default unit
  test path.
- Real AWS validation is explicit and outside the default unit test path.

Primary local command:

```bash
python -m unittest discover -s s3_notable_pipeline/tests -p "test_*.py" -v
```

## Implementation Hard Stops

Stop and ask before coding if any of these become necessary:

- replacing Lambda analyzer orchestration with Step Functions, ECS, or another
  workflow host
- adding OpenSearch or Bedrock Knowledge Base case ingestion instead of Aurora
  Postgres plus pgvector for case-chunk retrieval
- loading local sentence-transformers, BGE embedders, or BGE rerankers into Lambda
- exposing portal routes without IAM or JWT authorization
- storing full alert payloads in DynamoDB instead of S3 envelopes
- adding new third-party Python dependencies beyond the existing Postgres driver
  already used elsewhere in the repo, if one is required for Aurora access
- adding cross-case / global archive chat
- adding analyst write actions from the portal

## Locked Decisions

### Decision 1: Case archive store (v1)

**Locked:** S3 canonical case envelope plus DynamoDB metadata index plus Aurora
Postgres case archive tables for indexed retrieval.

- S3 holds full-fidelity `alert_payload`, `analysis`, artifact pointers, and
  archive metadata at `cases/yyyy/mm/dd/{case_id}.json`.
- DynamoDB holds browse/query metadata and pointers only.
- Aurora Postgres holds `notable_cases.cases` and `notable_cases.case_chunks`
  for on-prem-equivalent hybrid retrieval (Decision 7).
- OpenSearch remains out of scope for v1 case-chunk retrieval.

### Decision 2: Portal hosting (v1)

**Locked:** API Gateway plus a separate portal Lambda, with **provisioned
concurrency** and **RDS Proxy** to Aurora (Option B).

- Portal API stays serverless Lambda; do not use ECS/Fargate for v1 unless a
  later approved customer platform standard requires it.
- Configure `PORTAL_LAMBDA_PROVISIONED_CONCURRENCY` (default `2`) to avoid cold
  starts for browse and chat under normal 4–10 analyst load.
- Analyzer and portal Lambdas connect to Aurora through
  `CASE_POSTGRES_RDS_PROXY_ENDPOINT`, not the cluster endpoint.
- Portal Lambda has read-only S3/DynamoDB/Aurora access and no analyzer/writeback
  permissions.
- Chat long-timeout routing remains Function URL plus CloudFront (Decision 19).
- GovCloud / FedRAMP: deploy portal Lambda in private subnets with controlled
  egress; prefer VPC interface endpoints for AWS APIs where available.

### Decision 3: Portal authentication (v1)

**Locked:** JWT authorizer as the v1 default, IAM as the second-best path.

- JWT fits analysts who do not have AWS accounts.
- Use Cognito or enterprise OIDC through API Gateway JWT authorizers.
- IAM remains valid for AWS-admin, lab, or machine-to-machine access.

### Decision 4: Case Q&A mode (v1)

**Locked:** Implement pinned-case chat only (`selected_case`).

- Every `POST /api/chat` request requires `selected_case_id`.
- Cross-case / global archive chat is removed on both AWS and on-prem.
- General technology / TTP fallback remains via `CASE_QA_GENERAL_KNOWLEDGE_ENABLED=true`.
- Optional advisory KB context still applies when `rag`, `spl_readonly`, or
  `elastic_readonly` profiles are also enabled.

### Decision 5: Archive write failure mode (v1)

**Locked:** `CASE_ARCHIVE_FAILURE_MODE=suppress` as the default.

- Archive/index failures are logged and surfaced in metadata, but do not fail the
  completed analysis run.
- Second-best option: `fail_closed`, which fails the Lambda record so S3 event
  retry can repair the archive/index write.

### Decision 6: Case-chunk embeddings (v1)

**Locked:** Bedrock Titan Text Embeddings V2 via API.

- Model: `amazon.titan-embed-text-v2:0`
- Output: `1024` dimensions with `normalize=true`
- Use the same model at chunk write and chat query time.
- Do not load on-prem `BAAI/bge-base-en-v1.5` into Lambda.
- This is the embedding **model** decision. It is separate from Decision 7
  (where indexed retrieval runs) and Decision 10 (when chunk embed runs).

### Decision 7: Case retrieval (v1)

**Locked:** Portal Lambda performs lexical plus vector plus RRF retrieval in Aurora
Postgres `notable_cases.case_chunks`, porting on-prem `case_chat.py` SQL and
merge behavior for `selected_case` only.

- Lexical lane: Postgres full-text search on generated `search_vector` up to
  `CASE_QA_LEXICAL_TOP_K`.
- Vector lane: pgvector cosine similarity on Bedrock Titan embeddings up to
  `CASE_QA_VECTOR_TOP_K`.
- Merge with `_merge_rrf` using `CASE_QA_RRF_K=60`.
- Retrieval requires `cases.retrieval_status=ready` and respects case expiry,
  matching on-prem gating.
- No in-Lambda full-case chunk scans, OpenSearch, Kendra, or Bedrock Knowledge
  Base for case-archive retrieval.

### Decision 8: Chat history (v1)

**Locked:** Implement on-prem chat history behind
`CASE_QA_CHAT_HISTORY_ENABLED=false` by default.

- Storage: DynamoDB `CHAT_SESSIONS_TABLE` and `CHAT_MESSAGES_TABLE`.
- Portal Lambda read/write only.

### Decision 9: Portal UI hosting (v1)

**Locked:** Thin static SPA on S3 plus CloudFront.

- Reuse the on-prem analyst portal React app with the same screens and layout.

### Decision 10: Embed timing (v1)

**Locked:** Inline post-archive chunk embed in the analyzer Lambda (Option A).

- After envelope, CaseIndex, and Aurora parent-row write, the analyzer embeds case
  chunks, writes `notable_cases.case_chunks` rows, and updates
  `retrieval_status` to `ready` or `failed` before the invocation completes.
- Matches on-prem `archive_case_for_portal()` -> `store_case_chunks()` in one
  worker completion path.
- Do not deploy or invoke a separate async embed Lambda in v1.
- Deployments with `CASE_ARCHIVE_ENABLED=true` must size analyzer Lambda timeout
  and memory for analysis plus bounded chunk embed. Recommended starting point
  when `analyst_portal` is enabled: `900` seconds and `1024` MB.

### Decision 11: General-knowledge fallback (v1)

**Locked:** Match on-prem default `CASE_QA_GENERAL_KNOWLEDGE_ENABLED=true`.

- Fallback triggers on empty retrieval or the on-prem insufficient-archive
  answer phrase, not on an embedding score threshold.

### Decision 12: Advisory context in portal chat (v1)

**Locked:** Match on-prem gating.

- `analyst_portal` alone does not pull KB context into chat.
- When `rag`, `spl_readonly`, or `elastic_readonly` are also enabled, portal chat
  may add the same advisory grounding paths as on-prem using Bedrock KB retrieve.

### Decision 13: Retrieval tuning knobs (v1)

**Locked:** Match on-prem retrieval config names and defaults.

- `CASE_QA_LEXICAL_TOP_K=30`
- `CASE_QA_VECTOR_TOP_K=30`
- `CASE_QA_RRF_K=60`
- `CASE_QA_MAX_CHUNKS_PER_LANE=6`
- `CASE_QA_MAX_TOTAL_CHUNKS=18`
- Do not use a separate `CASE_QA_MAX_SOURCES` knob.

### Decision 14: Reranker (v1)

**Locked:** Implement `RAG_RERANK_ENABLED=false` by default.

- When enabled, rerank applies only to advisory KB snippets, never case chunks.
- AWS primary model: `cohere.rerank-v3-5:0`
- AWS fallback model: `amazon.rerank-v1:0` in regions where Cohere is unavailable
- Do not load `BAAI/bge-reranker-base` into Lambda.

### Decision 15: Vector dimensions config (v1)

**Locked:** `CASE_QA_VECTOR_DIMENSIONS=1024` for Titan V2.

- Validation must reject mismatches between stored chunk vectors and configured
  embed dimensions.

### Decision 16: `analyst_portal` and HTML reports (v1)

**Locked:** Keep profiles separate.

- `analyst_portal` does not enable `HTML_REPORT_ENABLED`.
- Operators compose `core,html_reports,analyst_portal` when they want both.

### Decision 17: Chat history storage shape (v1)

**Locked:** Two DynamoDB tables matching on-prem session/message semantics.

- See DynamoDB Chat History Contract above.

### Decision 18: Portal UI scope (v1)

**Locked:** Exact reuse of on-prem analyst portal UI.

- Routes: `/`, `/cases`, `/cases/{case_id}`
- AWS-only client changes: JWT bearer auth and `VITE_PORTAL_API_BASE_URL`
- API responses must match on-prem OpenAPI models

### Decision 19: Chat route timeout (v1)

**Locked:** Do not serve long-running `POST /api/chat` through the 30-second API
Gateway integration limit alone.

- Portal Lambda timeout: `PORTAL_CHAT_TIMEOUT_SEC` default `300`
- Expose chat through a portal Lambda Function URL integrated behind CloudFront
  or equivalent direct HTTPS path with JWT validation inside the handler
- Keep standard portal routes on API Gateway with the JWT authorizer
- Browser client keeps the on-prem long chat timeout behavior

### Decision 20: Case chunk storage (v1)

**Locked:** Aurora Postgres `notable_cases.case_chunks` rows with GIN FTS and HNSW
pgvector indexes, ported from on-prem `notable_cases_schema.sql`.

- One row per chunk with generated `search_vector` for lexical retrieval.
- Embed with Bedrock Titan during inline analyzer embed (Decision 10).
- Portal queries indexed rows for the pinned case only; do not store retrieval
  chunks in S3.

### Decision 21: Archive notices (v1)

**Locked:** Port on-prem `case_archive_notices.py` verbatim.

- Populate `archive_notices` on `/api/cases` and `/api/cases/{case_id}` from
  `retrieval_status`, `source_completeness`, and envelope `archive_metadata`.
- Notices cover `pending`, `failed`, `not_indexed`, incomplete sources, and
  `poc_unstructured_output` the same way as on-prem.

### Decision 22: Chat dependency status (v1)

**Locked:** Full `chat_dependency_status` in `/api/capabilities` when
`CASE_QA_ENABLED=true`.

- Keys: `embeddings`, `archive_retrieval`, `llm_gateway` with values `ready` or
  `unavailable`.
- Use live probes matching on-prem: Bedrock embed, Aurora Postgres hybrid
  retrieval path, and Bedrock chat gateway reachability.
- Expose `chat_degraded_reason` when `chat_ready=false`.

### Decision 23: Portal chat concurrency (v1)

**Locked:** Match on-prem `PORTAL_CHAT_MAX_CONCURRENCY` default `4`, max `64`.

- Set Lambda reserved concurrency on the chat-capable portal Lambda to this
  value.
- Return HTTP 429 with *"Too many chat requests are already running. Try again
  shortly."* when concurrency is exceeded.

### Decision 24: Diff sequence and module layout (v1)

**Locked:** Inline archive plus chunk embed live in **Diff 2** (no separate Diff
2b embed Lambda).

- Embed logic in `case_embed.py` with Aurora helpers in `case_postgres.py`.
- Case detail assembly stays in `case_index.py` and `portal_handler.py`; no
  separate `portal_case_detail.py` module.

### Decision 25: Case identity collision (v1)

**Locked:** Suppress on identity mismatch; match on-prem runtime behavior.

- Conditional DynamoDB write allows replay only when source identity matches.
- On mismatch: log the conflict, skip archive update, leave the existing case
  row unchanged, and do not fail the completed analysis run.

### Decision 26: Inline embed pending window (v1)

**Locked:** Match on-prem brief `pending` semantics during inline embed in the
same analyzer run.

- Analyzer writes CaseIndex and Postgres `cases` with `retrieval_status=pending`,
  embeds inline, then moves to `ready` or `failed` before returning.
- `archive_notices` for `pending` apply only if a client reads the case mid-run;
  normal success should expose `ready` as soon as the analyzer completes.
- Chat requires `retrieval_status=ready`; empty retrieval on `failed` or
  `not_indexed` may trigger general-knowledge fallback when enabled.
- No separate async embed worker and no blocking poll in the portal API.

### Decision 27: OpenAPI contract tests (v1)

**Locked:** Vendor on-prem `portal.openapi.json` and enforce parity in Diff 3.

- Copy `llm_notable_analysis_onprem_systemd/frontend/analyst-portal/openapi/portal.openapi.json`
  into `s3_notable_pipeline/docs/contracts/`.
- Reuse on-prem Pydantic models in `portal_api_models.py`.
- Add contract tests for capabilities, case list, and case detail response shapes.

### Decision 28: Analyzer Bedrock model default (v1)

**Locked (amended #7):** Default analyzer preset is **`gpt-5.4-medium`**. The
supported v1 alternate is **`sonnet-4.6-medium`**, selected **per customer
decision** at deploy time (not the product default). Both use **medium**
reasoning/thinking effort as the production starting point — not vendor
headline benchmark settings (`xhigh` / `max`).

**Default preset — `gpt-5.4-medium`:**

- `BEDROCK_ANALYZER_MODEL_PRESET=gpt-5.4-medium`
- Model ID `openai.gpt-5.4` on **Bedrock Mantle** OpenAI Responses API
  (`https://bedrock-mantle.{region}.api.aws/openai/v1/responses`).
- Request `reasoning.effort=medium`.
- SAM/CloudFormation default `BEDROCK_MODEL_ID=openai.gpt-5.4` when the GPT
  preset is selected.
- Analyzer Lambda IAM must allow Mantle invoke for `openai.gpt-5.4` in the
  configured region.

**Alternate preset — `sonnet-4.6-medium`:**

- `BEDROCK_ANALYZER_MODEL_PRESET=sonnet-4.6-medium`
- Bedrock Runtime **Converse** with the regional Sonnet 4.6 inference profile
  ARN. For GovCloud (Decision 35), use
  `arn:aws-us-gov:bedrock:us-gov-west-1:${AwsAccountId}:inference-profile/us.anthropic.claude-sonnet-4-6`.
- Pass `additionalModelRequestFields`:
  `thinking.type=adaptive`, `output_config.effort=medium`.
- Implementation must resolve Converse `temperature` interaction with adaptive
  thinking (current analyzer uses low temperature for tool-call stability).

**Operator overrides:**

- Nova Pro, Claude Haiku 4.5, Opus tiers, and legacy Sonnet 4.5 remain
  supported via explicit `BEDROCK_MODEL_ID` for cost, latency, or quality
  experiments.
- Claude Sonnet 4.5 is deprecated for new defaults.

**Implementation notes:**

- `ttp_analyzer.py` must support both API paths behind the preset selector; a
  Converse-only `BEDROCK_MODEL_ID` swap is insufficient for the default.
- Portal chat inherits the active analyzer preset unless
  `PORTAL_CHAT_BEDROCK_MODEL_ID` is set (Decision 29); `portal_chat.py` needs
  the same Mantle vs Converse branching when GPT-5.4 is inherited.
- Before first GovCloud deploy, confirm model access for Sonnet inference
  profile, Titan embed, Aurora Postgres, and `openai.gpt-5.4` on Mantle in
  `us-gov-west-1`.

### Decision 35: Deployment target region (v1)

**Locked:** v1 portal and analyzer parity deploys target **AWS GovCloud
(`us-gov-west-1`)**.

- SAM/CloudFormation examples and operator runbooks use GovCloud partition ARNs
  (`arn:aws-us-gov:...`) and `us-gov-west-1` unless a customer explicitly
  requests a commercial region.
- Portal and analyzer Lambdas run in private subnets with controlled egress;
  prefer VPC interface endpoints for AWS APIs where available (Decision 2).
- Commercial-region examples in older templates remain valid for lab use but are
  not the v1 production default.

### Decision 29: Portal chat Bedrock model (v1)

**Locked:** Portal answer synthesis uses a separate optional model config.

- Add `PORTAL_CHAT_BEDROCK_MODEL_ID`.
- When unset or empty, portal chat inherits `BEDROCK_MODEL_ID`.
- When chat volume materially exceeds analysis volume, operators may set
  `PORTAL_CHAT_BEDROCK_MODEL_ID` to a cheaper chat-suitable model such as Claude
  Haiku 4.5 while keeping the analyzer on the active preset (default GPT-5.4
  medium).
- Portal chat must not reuse analyzer prompts, tool schemas, or repair paths from
  `ttp_analyzer.py`.

### Decision 30: JWT identity provider pattern (v1)

**Locked:** Enterprise OIDC-first JWT validation; Cognito optional.

- Production portal auth uses API Gateway JWT authorizers with operator-supplied
  `PORTAL_JWT_ISSUER`, `PORTAL_JWT_AUDIENCE`, and IdP JWKS metadata.
- Cognito may be documented as a lab or small-team fast path, but the default
  SAM/CloudFormation templates must not require Cognito resources.
- Browser clients continue to send `Authorization: Bearer <jwt>` only.

### Decision 31: CloudFront routing shape (v1)

**Locked:** Use explicit path-based routing for chat vs standard portal API.

- CloudFront default behavior serves the static SPA from S3.
- CloudFront behavior `/api/chat` and `/api/chat/*` forwards to the portal
  Lambda Function URL.
- CloudFront behavior `/api/*` forwards to API Gateway for all other portal API
  routes.
- The portal Lambda validates JWT claims on Function URL chat requests inside the
  handler when API Gateway is not the front door for that path.

### Decision 32: CaseIndex verdict filtering (v1)

**Locked:** Defer `VerdictProcessedAtIndex` for v1.

- Case list verdict filtering uses `ProcessedAtIndex` plus portal-side verdict
  filtering.
- Do not add a second GSI in v1 unless measured portal list latency or query cost
  at customer scale proves the first access pattern is insufficient.

### Decision 33: Portal chat Bedrock module boundary (v1)

**Locked:** Implement portal chat synthesis in `portal_chat.py`.

- Diff 4 adds a small Bedrock converse helper dedicated to portal Q&A.
- `portal_chat.py` owns chat prompts, bounded synthesis, citation validation,
  and general-knowledge fallback orchestration.
- `ttp_analyzer.py` remains analyzer-only and must not be imported by portal
  chat code.

### Decision 34: Recommended v1 portal deploy bundle (v1)

**Locked:** Default portal deployments to the minimal parity profile bundle.

- Recommended production portal parameter set:
  `CAPABILITY_PROFILES=core,analyst_portal`
- Default-off for v1 portal rollouts: `rag`, `spl_readonly`, `elastic_readonly`,
  `html_reports`, `ticket_draft`, and `action_gated`.
- Enable additional profiles only when a named customer integration requires them.
- Keep `CASE_QA_CHAT_HISTORY_ENABLED=false` and `RAG_RERANK_ENABLED=false` unless
  a customer explicitly opts in.

## Portal Frontend Contract

Reuse `llm_notable_analysis_onprem_systemd/frontend/analyst-portal` without
visual changes.

Production-only AWS additions:

```env
VITE_PORTAL_API_BASE_URL=https://<portal-api-host>
```

Client behavior:

- Attach `Authorization: Bearer <jwt>` on API calls.
- Use the configured API base URL instead of same-origin relative fetches.
- Preserve existing response parsers and UI banners driven by
  `/api/capabilities`.

Do not require analysts to use AWS IAM credentials in the browser.

## Build-Readiness Gate

This plan is ready to feed Cursor for implementation when:

- [x] `analyst_portal` profile semantics are accepted for AWS.
- [x] S3 envelope plus DynamoDB index plus Aurora Postgres pgvector retrieval is
  accepted as the v1 AWS equivalent of on-prem case archive storage and Case Q&A
  search.
- [x] Portal Lambda plus provisioned concurrency and RDS Proxy (Decision 2) is
  accepted, with Decision 19 chat timeout routing.
- [x] Pinned-case Q&A (`selected_case` only) is accepted for AWS and on-prem.
- [x] Decisions 6 through 27 are accepted.
- [x] Decisions 28 through 35 are accepted for deploy defaults, auth, routing,
  model selection, GovCloud target region, and Diff 4 module boundaries.
- [x] Inline analyzer chunk embed (Decision 10) is accepted in Diff 2; no
  separate embed Lambda in v1.
- The hard stops above are treated as plan changes, not implementation details.
