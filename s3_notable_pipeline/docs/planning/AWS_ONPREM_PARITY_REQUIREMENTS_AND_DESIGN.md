# AWS / On-Prem Parity Requirements And Design

## Status

Planning and implementation-input artifact. Architecture decisions 1 through 35
are locked in this document. **Decision 35** aligns wave-2 Python dependencies
with the on-prem portal stack (Pydantic for `portal_api_models.py`). Implementation
may proceed once the technical spec and diff sequence below are accepted.

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
- no retrieval-bound Case Q&A over retained cases
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
- Add AWS runtime config, SAM/CloudFormation parameters, IAM, docs, and tests for
  archive and portal behavior.
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
- OpenSearch Serverless, Aurora Postgres, or Bedrock Knowledge Base ingestion for
  v1 archive browsing unless a later approved requirement proves DynamoDB/S3 is
  insufficient.
- Copying the on-prem FastAPI/Postgres implementation into AWS literally.
- Adding Python dependencies outside the wave-2 on-prem portal allowlist (Decision 35).
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
| Postgres `case_chunks` with pgvector | S3 case chunk objects plus in-Lambda lexical/vector/RRF retrieval |
| FastAPI portal bound to loopback | API Gateway plus portal Lambda; chat via Function URL (Decision 19) |
| nginx auth and trusted user header | JWT authorizer plus browser bearer token; IAM second-best |
| on-prem Mixedbread embedder in app code | Bedrock `amazon.titan-embed-text-v2:0` at chunk write and query |
| on-prem optional Mixedbread reranker | Bedrock rerank API (`cohere.rerank-v3-5:0`, Amazon fallback) |
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
-> when CASE_ARCHIVE_ENABLED=true, run post-archive chunk embed step
   (separate Lambda invoke; not inline in analyzer memory)
   -> Bedrock Titan Embed writes S3 case_chunks objects
   -> CaseIndex retrieval_status transitions pending -> ready|failed
-> optional gated Splunk/ServiceNow side effects
```

Archive writes run after the validated analysis object exists and after report
object keys are known. The archive must never require parsing markdown or HTML.
Chunk embedding must not run inside the analyzer Lambda process.

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
-> lexical + vector + RRF retrieval over S3 case chunks
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
CASE_ARCHIVE_ENABLED=false
CASE_ARCHIVE_FAILURE_MODE=suppress
CASE_ARCHIVE_BUCKET=
CASE_ARCHIVE_PREFIX=cases
CASE_ARCHIVE_CHUNKS_PREFIX=case_chunks
CASE_INDEX_TABLE=
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
PORTAL_CHAT_MAX_CONCURRENCY=18
PORTAL_CHAT_BEDROCK_MODEL_ID=

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
- `CASE_ARCHIVE_BUCKET` defaults to `OUTPUT_BUCKET_NAME` when unset.
- `PORTAL_AUTH_MODE` must be `jwt` or `iam`.
- `PORTAL_JWT_ISSUER` and `PORTAL_JWT_AUDIENCE` are required when
  `PORTAL_AUTH_MODE=jwt`.
- `CASE_QA_ENABLED=true` requires `PORTAL_ENABLED=true`.
- `selected_case` chat mode requires `selected_case_id` in the request payload.
- `CASE_QA_CHAT_HISTORY_ENABLED=true` requires `CHAT_SESSIONS_TABLE` and
  `CHAT_MESSAGES_TABLE`.
- `CASE_QA_VECTOR_DIMENSIONS` must match the configured Titan embed output size.
- `PORTAL_CHAT_MAX_CONCURRENCY` must be a positive integer, default `18`, max `64`.
  Same default on AWS and on-prem.
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

## S3 Case Chunk Object Contract

Write one JSON object per chunk:

```text
s3://{CASE_ARCHIVE_BUCKET}/{CASE_ARCHIVE_CHUNKS_PREFIX}/{case_id}/{chunk_id}.json
```

Required shape:

```json
{
  "chunk_schema_version": 1,
  "chunk_id": "{case_id}:{source_lane}:{section}:{ordinal}",
  "case_id": "string",
  "source_lane": "alert_payload|case_analysis|legacy_summary",
  "section": "string",
  "field_path": "string",
  "text": "string",
  "search_text": "section field_path text",
  "embedding": [1024 floats],
  "embedding_model": "amazon.titan-embed-text-v2:0",
  "metadata": {}
}
```

Rules:

- Port on-prem `build_chunk_id()` and chunk citation metadata from `case_search.py`.
- `search_text` matches on-prem FTS input: `section + " " + field_path + " " + text`.
- Re-embed deletes all objects under `{prefix}/{case_id}/` before rewrite.
- Titan embeddings are L2-normalized at write; dimensions must match
  `CASE_QA_VECTOR_DIMENSIONS`.

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
| S3 | Incoming notables, reports, case envelopes, case chunk objects |
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
| `/ready` | `GET` | DynamoDB/S3 readiness check |
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

Analyzer Lambda role additions when `CASE_ARCHIVE_ENABLED=true`:

- `s3:PutObject` on `cases/` in the archive bucket.
- `s3:GetObject` only where needed to read existing report objects for chunk
  construction.
- `dynamodb:PutItem`, `dynamodb:UpdateItem`, and `dynamodb:GetItem` on
  `CASE_INDEX_TABLE`.
- Permission to invoke the post-archive embed Lambda when chunk indexing is
  enabled.
- No portal read API permissions, Bedrock embed, or chat-history permissions on
  the analyzer role.

Post-archive embed Lambda role:

- `s3:PutObject` and `s3:GetObject` on `case_chunks/` and read access to case
  envelopes as needed.
- `dynamodb:UpdateItem` on `CASE_INDEX_TABLE` for `retrieval_status`.
- `bedrock:InvokeModel` on `CASE_QA_EMBEDDING_MODEL`.

Portal Lambda role:

- `dynamodb:Query` on `ProcessedAtIndex`.
- `dynamodb:GetItem` on `CASE_INDEX_TABLE`.
- `s3:GetObject` on `cases/`, `case_chunks/`, and `reports/` prefixes needed for
  portal rendering.
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
- Add S3 lifecycle configuration for `cases/` and `case_chunks/` prefixes aligned
  to `CASE_RETENTION_DAYS`.
- Keep current `core` deployment parameters valid.
- Keep `scripts/test-pipeline.ps1` a core smoke test by default.
- Add optional archive/portal smoke validation steps that require explicit
  parameters and never assume live AWS credentials in unit tests.
- Do not require Step Functions, ECS, OpenSearch, Aurora, Cognito, or CloudFront
  for the first archive write slice.

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
- `CAPABILITY_PROFILES=core,analyst_portal` validates when required archive
  settings are present.
- Invalid auth mode, retention, table names, embed dimensions, or chat-history
  table config fails fast.

### Diff 2: Case envelope and DynamoDB index writer

Objective:

- Write canonical S3 case envelopes and DynamoDB CaseIndex metadata from the
  analyzer Lambda.

Files:

- `src/s3_notable_pipeline/case_archive.py`
- `src/s3_notable_pipeline/lambda_handler.py`
- `src/s3_notable_pipeline/aws_clients.py`
- `tests/test_case_archive.py`
- `tests/test_lambda_handler.py`

Acceptance criteria:

- Archive is skipped when disabled.
- Archive writes do not parse markdown or HTML.
- Replayed events for the same case are idempotent.
- `CASE_ARCHIVE_FAILURE_MODE=suppress` preserves report output and records
  archive failure status.
- `CASE_ARCHIVE_FAILURE_MODE=fail_closed` fails the Lambda record on archive
  write/index failure.
- Identity collision on an existing `case_id` suppresses the archive write and
  does not fail the completed analysis run.
- Analyzer sets `retrieval_status=pending` and asynchronously invokes the embed
  Lambda when chunk indexing is enabled.

### Diff 2b: Post-archive embed Lambda

Objective:

- Embed case chunks in a separate Lambda after the analyzer writes the envelope
  and CaseIndex row.

Files:

- `src/s3_notable_pipeline/case_embed.py`
- `src/s3_notable_pipeline/embed_handler.py`
- `deploy/aws/template-sam.yaml`
- `deploy/aws/template-cfn.yaml`
- `tests/test_case_embed.py`
- `tests/test_embed_handler.py`

Acceptance criteria:

- Invoked asynchronously from the analyzer after envelope and CaseIndex write.
- CaseIndex starts at `retrieval_status=pending`; transitions to `ready` or
  `failed` when embed completes.
- Writes one S3 chunk object per chunk with Titan embeddings and `search_text`.
- Re-embed deletes all objects under `{CASE_ARCHIVE_CHUNKS_PREFIX}/{case_id}/`
  before rewrite.
- Embed failures do not fail the analyzer run when
  `CASE_ARCHIVE_FAILURE_MODE=suppress`.
- Embedding does not run inside the analyzer Lambda process.

### Diff 3: Read-only portal API Lambda

Objective:

- Add the portal read API over DynamoDB and S3 with no mutating case operations.

Files:

- `src/s3_notable_pipeline/portal_handler.py`
- `src/s3_notable_pipeline/case_index.py`
- `src/s3_notable_pipeline/portal_api_models.py` (vendored from on-prem; Pydantic)
- `src/s3_notable_pipeline/case_archive_notices.py` (ported verbatim from on-prem)
- `docs/contracts/portal.openapi.json` (vendored from on-prem)
- `requirements.txt` (add `pydantic` pin per Decision 35)
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
- In-handler chat concurrency matches `PORTAL_CHAT_MAX_CONCURRENCY`; excess
  chat requests return HTTP 429 with the on-prem message (Decision 23).
- Portal Lambda has no writeback, input-bucket, or case mutation permissions.
- Unauthenticated or malformed auth context fails closed.
- Mutating methods are rejected.
- Case detail assembly lives in `case_index.py` and `portal_handler.py`; no
  separate `portal_case_detail.py` module (Decision 24).

### Diff 4: Pinned-case Q&A

Objective:

- Add retrieval-bound pinned-case Q&A through the portal API.

Files:

- `src/s3_notable_pipeline/case_chat.py`
- `src/s3_notable_pipeline/portal_handler.py`
- `src/s3_notable_pipeline/portal_chat.py` (Decision 33; no `ttp_analyzer.py`
  import for portal answer synthesis)
- `tests/test_case_chat.py`
- `tests/test_portal_handler.py`

Acceptance criteria:

- Q&A is disabled by default.
- Q&A requires `selected_case_id` and retrieves that case's chunks before model
  invocation.
- Chunk retrieval requires `retrieval_status=ready`; cases in `pending` may be
  chatted but return empty retrieval until embed completes (Decision 26).
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
- Docs explain profile enablement, IAM, auth mode, S3 lifecycle, DynamoDB TTL,
  retention, chat timeout routing, failure behavior, and rollback.
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
- Real AWS validation is explicit and outside the default unit test path.

Primary local command:

```bash
python -m unittest discover -s s3_notable_pipeline/tests -p "test_*.py" -v
```

## Dependency Posture (Wave 2)

Reuse on-prem portal packages where they directly support API contract parity.
Do not reimplement `portal_api_models.py` with ad-hoc dataclasses when Pydantic
is already the on-prem contract.

**Allowed without extra approval (wave 2 portal block):**

- `requests==2.32.5` (existing; Splunk, Elastic, ServiceNow, HTTP clients)
- Lambda-provided `boto3` / botocore (Bedrock, S3, DynamoDB, Secrets Manager)
- **`pydantic`** — pin to the same resolved version as on-prem
  `fastapi==0.115.12` in `llm_notable_analysis_onprem_systemd/pyproject.toml`;
  record the pin in `s3_notable_pipeline/requirements.txt` during Diff 3
  (Decision 35)

**Explicitly not ported to AWS Lambdas (use Bedrock or AWS-native substitutes):**

- `onprem-llm-sdk`, `onprem-rag-notable-analysis`
- `sentence-transformers`, `transformers`, `huggingface-hub`, `faiss-cpu`,
  `numpy` (local embedders / rerankers — Decision 6)
- `psycopg`, `pgvector` (v1 case chunks live in S3, not Postgres — Decision 7)
- `fastapi`, `uvicorn` (on-prem web server; AWS uses `portal_handler.py` behind
  API Gateway / Function URL — Pydantic models only, not the FastAPI app)

**Default posture:**

- Prefer packages already pinned in on-prem when they solve the current slice.
- Do not add other third-party packages for wave 2 unless a hard stop is lifted
  by an explicit new decision.

## Implementation Hard Stops

Stop and ask before coding if any of these become necessary:

- replacing Lambda analyzer orchestration with Step Functions, ECS, or another
  workflow host
- adding OpenSearch, Aurora, Bedrock Knowledge Base case ingestion, or a new
  vector database for v1 case-archive storage
- loading local sentence-transformers, Mixedbread embedders, or Mixedbread rerankers into Lambda
- exposing portal routes without IAM or JWT authorization
- storing full alert payloads in DynamoDB instead of S3 envelopes
- adding third-party Python dependencies **outside** the Decision 35 on-prem
  portal allowlist
- adding cross-case / global archive chat
- adding analyst write actions from the portal

## Locked Decisions

### Decision 1: Case archive store (v1)

**Locked:** S3 canonical case envelope plus DynamoDB metadata index.

- S3 holds full-fidelity `alert_payload`, `analysis`, artifact pointers, and
  archive metadata at `cases/yyyy/mm/dd/{case_id}.json`.
- DynamoDB holds browse/query metadata and pointers only.
- Aurora Postgres and OpenSearch are out of scope for v1 archive storage.

### Decision 2: Portal hosting (v1)

**Locked:** API Gateway plus a separate portal Lambda.

- This preserves the lightweight serverless AWS shape.
- The portal Lambda has read-only S3/DynamoDB access and no analyzer/writeback
  permissions.
- Second-best option: internal ALB plus ECS/Fargate portal service, only when a
  customer platform standard requires ECS for internal web apps.

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
- Do not load on-prem `mixedbread-ai/mxbai-embed-large-v1` into Lambda.

### Decision 7: Case retrieval (v1)

**Locked:** Portal Lambda performs lexical plus vector plus RRF retrieval over S3
`case_chunks/` objects, porting on-prem `case_chat.py` behavior for
`selected_case` only.

- Lexical lane: in-memory BM25 over stored `search_text` (stdlib only).
- Vector lane: cosine similarity on Bedrock Titan embeddings at query time.
- Merge with `_merge_rrf` using `CASE_QA_RRF_K=60`.
- No OpenSearch, Kendra, or Bedrock Knowledge Base for case-archive retrieval.

### Decision 8: Chat history (v1)

**Locked:** Implement on-prem chat history behind
`CASE_QA_CHAT_HISTORY_ENABLED=false` by default.

- Storage: DynamoDB `CHAT_SESSIONS_TABLE` and `CHAT_MESSAGES_TABLE`.
- Portal Lambda read/write only.

### Decision 9: Portal UI hosting (v1)

**Locked:** Thin static SPA on S3 plus CloudFront.

- Reuse the on-prem analyst portal React app with the same screens and layout.

### Decision 10: Embed timing (v1)

**Locked:** Post-archive embed step in a separate Lambda invocation.

- Analyzer writes envelope and CaseIndex metadata, then triggers chunk embed.
- Do not increase analyzer Lambda memory for embedding.

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
- Do not load `mixedbread-ai/mxbai-rerank-large-v2` into Lambda.

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

### Decision 20: S3 case chunk storage (v1)

**Locked:** One S3 JSON object per chunk at
`{CASE_ARCHIVE_CHUNKS_PREFIX}/{case_id}/{chunk_id}.json`.

- Store `search_text` explicitly for BM25 lexical retrieval in the portal Lambda.
- Embed with Bedrock Titan at write; portal loads chunks for the pinned case only.

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
- Use live probes matching on-prem: Bedrock embed, BM25+vector retrieval path,
  and Bedrock chat gateway reachability.
- Expose `chat_degraded_reason` when `chat_ready=false`.

### Decision 23: Portal chat concurrency (v1)

**Locked:** Enforce `PORTAL_CHAT_MAX_CONCURRENCY` in the portal Lambda handler,
matching on-prem semaphore behavior. Default **`18`** (max `64`) on AWS and on-prem.

- Count active chat requests in-handler for the full synthesis duration; do **not**
  use Lambda reserved concurrency as the chat limit (browse routes must stay
  unconstrained).
- Return HTTP 429 with *"Too many chat requests are already running. Try again
  shortly."* when concurrency is exceeded.
- Scope is **per execution environment** (in-process), not account-wide; see
  Decision 36.

### Decision 24: Diff sequence and module layout (v1)

**Locked:** Explicit **Diff 2b** for the post-archive embed Lambda between Diff
2 and Diff 3.

- Embed logic in `case_embed.py` and `embed_handler.py`.
- Case detail assembly stays in `case_index.py` and `portal_handler.py`; no
  separate `portal_case_detail.py` module.

### Decision 25: Case identity collision (v1)

**Locked:** Suppress on identity mismatch; match on-prem runtime behavior.

- Conditional DynamoDB write allows replay only when source identity matches.
- On mismatch: log the conflict, skip archive update, leave the existing case
  row unchanged, and do not fail the completed analysis run.

### Decision 26: Async embed pending window (v1)

**Locked:** Accept the async `pending` window matching on-prem.

- Analyzer writes CaseIndex with `retrieval_status=pending`; embed Lambda moves
  to `ready` or `failed`.
- `archive_notices` warn analysts during `pending`.
- Chat is allowed on pending cases, but chunk retrieval requires `ready`; empty
  retrieval may trigger general-knowledge fallback when enabled.
- No blocking poll in the portal API.

### Decision 27: OpenAPI contract tests (v1)

**Locked:** Vendor on-prem `portal.openapi.json` and enforce parity in Diff 3.

- Copy `llm_notable_analysis_onprem_systemd/frontend/analyst-portal/openapi/portal.openapi.json`
  into `s3_notable_pipeline/docs/contracts/`.
- Vendor on-prem `portal_api_models.py` **unchanged** (Pydantic `BaseModel` shapes).
- Serialize responses with `.model_dump()` / `.model_dump_json()` in
  `portal_handler.py`; do not hand-roll alternate field names.
- Add `pydantic` to `s3_notable_pipeline/requirements.txt` per Decision 35.
- Add contract tests for capabilities, case list, and case detail response shapes.

### Decision 28: Analyzer Bedrock model default (v1)

**Locked:** Default analyzer and portal-chat inheritance to **Claude Sonnet 4.6**
on Amazon Bedrock unless the customer explicitly overrides `BEDROCK_MODEL_ID`.

- SAM/CloudFormation default `BEDROCK_MODEL_ID` must use the regional Sonnet 4.6
  inference profile ARN for the deployment region. For `us-east-1`, use
  `arn:aws:bedrock:us-east-1:${AwsAccountId}:inference-profile/us.anthropic.claude-sonnet-4-6`.
- Sonnet 4.6 is the AWS-side peer/upgrade to on-prem `gemma-4-31B-it` for
  structured notable analysis, reasoning over alert JSON, and data synthesis.
- Nova Pro and Claude Haiku 4.5 remain supported operator overrides for cost or
  latency experiments; Claude Sonnet 4.5 is deprecated for new defaults.

### Decision 29: Portal chat Bedrock model (v1)

**Locked:** Portal answer synthesis uses a separate optional model config.

- Add `PORTAL_CHAT_BEDROCK_MODEL_ID`.
- When unset or empty, portal chat inherits `BEDROCK_MODEL_ID`.
- When chat volume materially exceeds analysis volume, operators may set
  `PORTAL_CHAT_BEDROCK_MODEL_ID` to a cheaper chat-suitable model such as Claude
  Haiku 4.5 while keeping Sonnet 4.6 on the analyzer.
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

### Decision 35: Wave-2 Python dependencies (v1)

**Locked:** Use on-prem portal contract packages; do not substitute dataclasses
for Pydantic in `portal_api_models.py`.

- Add **`pydantic`** to `s3_notable_pipeline/requirements.txt` when the portal
  API slice ships (Diff 3). Pin to the same resolved version as on-prem
  `fastapi==0.115.12` in `llm_notable_analysis_onprem_systemd/pyproject.toml`.
- Vendor or copy `portal_api_models.py` from on-prem with Pydantic models intact.
- Do **not** deploy `fastapi` or `uvicorn` on the portal Lambda; the handler is
  plain Lambda + API Gateway, not a FastAPI app.
- Do **not** port on-prem ML/RAG stack packages (`sentence-transformers`,
  `faiss-cpu`, `onprem-llm-sdk`, etc.); AWS uses Bedrock for embed and chat.
- Any dependency outside `requests`, Lambda `boto3`, and the Pydantic pin above
  requires a new locked decision.

### Decision 36: Portal chat concurrency scope (v1)

**Locked:** Per portal Lambda **execution environment** (in-process semaphore),
matching on-prem per-process behavior.

- The semaphore limits concurrent in-flight chat requests within one warm Lambda
  execution environment only.
- Approximate fleet-wide concurrency is
  `PORTAL_CHAT_MAX_CONCURRENCY` times the number of concurrent warm portal
  execution environments (scales with traffic; provisioned concurrency sets a
  floor, not a hard global cap).
- Do **not** implement a DynamoDB, ElastiCache, or other cross-instance chat
  counter in v1.
- If a customer requires a hard account-wide chat cap across all warm instances,
  that requires a new locked decision and is out of v1 scope.

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
- [x] S3 envelope plus DynamoDB index is accepted as the v1 AWS-native equivalent of
  on-prem Postgres archive storage.
- [x] API Gateway plus portal Lambda is accepted as the v1 AWS-native equivalent of
  on-prem FastAPI/nginx, with Decision 19 chat timeout routing.
- [x] Pinned-case Q&A (`selected_case` only) is accepted for AWS and on-prem.
- [x] Decisions 6 through 27 are accepted.
- [x] Decisions 28 through 35 are accepted for deploy defaults, auth, routing,
  model selection, Diff 4 module boundaries, and on-prem Pydantic dependency parity.
- [x] Diff 2b (post-archive embed Lambda) is accepted between archive write and
  portal API slices.
- The hard stops above are treated as plan changes, not implementation details.
