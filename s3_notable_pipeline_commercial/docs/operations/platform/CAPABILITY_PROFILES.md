# Capability Profiles

Capability profiles are the operator-facing way to enable supported feature
bundles on AWS. Set `CapabilityProfiles` at deploy time (SAM or CloudFormation)
or `CAPABILITY_PROFILES` on the Lambda function environment, then configure only
the endpoints, secret ARNs, and tuning values required by that profile.

Low-level `*_ENABLED` flags remain supported for legacy lab configs when no
selected profile controls that capability, but profiles are the preferred
operator workflow. When a selected profile controls a capability, the profile
takes precedence.

SAM/CloudFormation parameters in `deploy/aws/template-sam.yaml` are the official
deployment path. Lambda environment variables are the runtime representation of
those parameters (`CapabilityProfiles` -> `CAPABILITY_PROFILES`,
`HtmlReportEnabled` -> `HTML_REPORT_ENABLED`, and so on).

## Supported Profiles

| Profile | Operator intent | Risk class |
|---------|-----------------|------------|
| `core` | S3-triggered ingest, Bedrock analysis, markdown + JSON reports under `reports/`. Sets no feature flags. | Read/write within customer S3 buckets; Bedrock inference. |
| `html_reports` | Static HTML reports as a third S3 artifact next to markdown and JSON. | Additional S3 report artifact only. |
| `rag` | General SOC RAG context from the tenant-scoped OpenSearch SOC index in the main analysis prompt. | Read-only retrieval; advisory context only. |
| `spl_readonly` | SPL query generation and bounded read-only Splunk investigation execution. | Read-only external Splunk or MCP queries. |
| `elastic_readonly` | Elasticsearch Query DSL generation and bounded read-only `_search` execution. | Read-only external Elasticsearch queries. |
| `ticket_draft` | ServiceNow incident draft payloads in JSON reports. | Report content only; no ServiceNow POST. |
| `action_gated` | Splunk notable writeback (when `SplunkSinkMode=notable_rest`), ServiceNow draft/create, signed ServiceNow approval, and DynamoDB side-effect idempotency. | External write/action path. |
| `analyst_portal` | S3 case archive, DynamoDB CaseIndex, read-only portal API, and retrieval-bound pinned-case Q&A. | Read-only analyst browse/chat over retained case evidence. |

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

Primary SAM parameter: `CapabilityProfiles` (default: `core`).

## Profile-to-Flag Mapping

Authoritative mapping from `src/s3_notable_pipeline/config.py`
(`_CAPABILITY_PROFILE_FLAGS` and backend selection in `_profile_flag_defaults`):

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

- `SPL_QUERY_RAG_ENABLED` (set explicitly with `SplQueryRagEnabled`)
- `ELASTICSEARCH_GROUNDING_ENABLED` (set explicitly with `ElasticsearchGroundingEnabled`)
- `QUERY_RESULT_INTERPRETATION_ENABLED` (no SAM parameter; env override only)
- `CASE_QA_CHAT_HISTORY_ENABLED` (default `false`; not enabled by `analyst_portal`)

## Operator Workflow

1. Start with `CapabilityProfiles=core` and `SplunkSinkMode=s3`.
2. Add one profile at a time in a non-production stack.
3. Configure required secret ARNs, URLs, OpenSearch indexes, and tuning values
   for the selected profile.
4. Run the smoke steps in the relevant operations guide and
   [`../../testing/TESTING.md`](../../testing/TESTING.md).

**Customer-default bundle (`core,rag,analyst_portal`):** use the SAM preset in
[`../deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`](../deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md)
instead of assembling flags manually.
5. Promote the same profile list after ownership, approval boundaries, and
   rollback expectations are documented.

## Profile Details

### `core`

Baseline Lambda behavior. No profile flags are set. Requires input/output bucket
settings from SAM and Bedrock model access from the template.

### `html_reports`

Use when operators want static HTML dashboards in addition to markdown and JSON
reports in S3.

Primary follow-up values:

- `HtmlReportEnabled` / `HTML_REPORT_ENABLED` (set by profile)
- `OutputBucketName` / `OUTPUT_BUCKET_NAME`
- Report prefix is fixed to `reports` in `template-sam.yaml` (`OUTPUT_PREFIX`)

### `rag`

Use after the general SOC OpenSearch corpus is curated and
owned. Retrieved content is advisory context, not direct alert evidence.

Primary follow-up values:

- `RagTenantId`, `OpenSearchEndpoint`, `OpenSearchDomainArn`, index names, and private VPC settings
- `RagMaxSnippets` / `RAG_MAX_SNIPPETS`, `RagContextBudgetChars` /
  `RAG_CONTEXT_BUDGET_CHARS`, `RagFailureMode` / `RAG_FAILURE_MODE`
- Lambda IAM permission for signed, read-only access to the SOC index

### `spl_readonly`

Use when Splunk owners approve generated SPL and bounded read-only execution.
This profile does not enable Splunk notable writeback (`SPLUNK_SINK_ENABLED`).
Profile sets `INVESTIGATION_QUERY_BACKEND=splunk`; do not also select
`elastic_readonly`.

Primary follow-up values:

- `InvestigationQueryExecutor` / `INVESTIGATION_QUERY_EXECUTOR=rest|mcp`
- `SplunkSearchAllowedIndexes` / `SPLUNK_SEARCH_ALLOWED_INDEXES`,
  `SplunkSearchAllowedCommands` / `SPLUNK_SEARCH_ALLOWED_COMMANDS`,
  `SplunkSearchDeniedCommands` / `SPLUNK_SEARCH_DENIED_COMMANDS`,
  `SplunkSearchAllowedFields` / `SPLUNK_SEARCH_ALLOWED_FIELDS`
- `SplunkSearchMaxTimeRange` / `SPLUNK_SEARCH_MAX_TIME_RANGE`,
  `SplunkSearchMaxRows` / `SPLUNK_SEARCH_MAX_ROWS`,
  `SplunkSearchTimeoutSeconds` / `SPLUNK_SEARCH_TIMEOUT_SECONDS`
- `SplunkBaseUrl` / `SPLUNK_BASE_URL` and `SplunkApiTokenSecretArn` /
  `SPLUNK_API_TOKEN_SECRET_ARN` when executor is `rest`
- `SplunkMcpEndpoint` / `SPLUNK_MCP_ENDPOINT` and `SplunkMcpAuthSecretArn` /
  `SPLUNK_MCP_AUTH_SECRET_ARN` when executor is `mcp`
- optional `SplQueryRagEnabled` / `SPL_QUERY_RAG_ENABLED` after the Splunk dictionary is ingested

### `elastic_readonly`

Use when Elasticsearch owners approve generated Query DSL and bounded read-only
`_search` execution. Profile sets `INVESTIGATION_QUERY_BACKEND=elasticsearch`;
do not also select `spl_readonly`.

Primary follow-up values:

- `ElasticsearchBaseUrl` / `ELASTICSEARCH_BASE_URL` (HTTPS required when
  execution is enabled)
- `ElasticsearchApiKeySecretArn` / `ELASTICSEARCH_API_KEY_SECRET_ARN`
- `ElasticsearchIndexAllowlist` / `ELASTICSEARCH_INDEX_ALLOWLIST`,
  `ElasticsearchAllowWildcardIndexes` / `ELASTICSEARCH_ALLOW_WILDCARD_INDEXES`
- `ElasticsearchTimestampField` / `ELASTICSEARCH_TIMESTAMP_FIELD`,
  `ElasticsearchAllowedFields` / `ELASTICSEARCH_ALLOWED_FIELDS`
- `ElasticsearchMaxTimeRange` / `ELASTICSEARCH_MAX_TIME_RANGE`,
  `ElasticsearchMaxRows` / `ELASTICSEARCH_MAX_ROWS`,
  `ElasticsearchTimeoutSeconds` / `ELASTICSEARCH_TIMEOUT_SECONDS`
- optional `ElasticsearchGroundingEnabled` / `ELASTICSEARCH_GROUNDING_ENABLED`
  after the Elasticsearch dictionary is ingested

### `ticket_draft`

Use when operators want ServiceNow incident drafts in JSON reports without
creating incidents.

Primary follow-up values:

- `ServiceNowAssignmentGroup` / `SERVICENOW_ASSIGNMENT_GROUP`

### `action_gated`

Use only after owners approve external write/action behavior.

This profile enables:

- Splunk notable comment writeback when `SplunkSinkMode=notable_rest`
- ServiceNow incident create (still approval-gated and signature-required)
- DynamoDB side-effect idempotency

Side-effect idempotency applies only to:

- Splunk notable update (`finding_id` key)
- ServiceNow incident create (draft `correlation_id` key)

It does not deduplicate S3 report writes, read-only Splunk or Elastic queries,
or Bedrock calls.

Primary follow-up values:

- `SideEffectIdempotencyTableName` / `SIDE_EFFECT_IDEMPOTENCY_TABLE`,
  `SideEffectIdempotencyRetentionDays` / `SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS`,
  `SideEffectIdempotencyLockSeconds` / `SIDE_EFFECT_IDEMPOTENCY_LOCK_SECONDS`
- `SplunkBaseUrl` / `SPLUNK_BASE_URL`, `SplunkApiTokenSecretArn` /
  `SPLUNK_API_TOKEN_SECRET_ARN`, `SplunkNotableUpdatePath` /
  `SPLUNK_NOTABLE_UPDATE_PATH`
- `SplunkRequirePayloadFindingId` / `SPLUNK_REQUIRE_PAYLOAD_FINDING_ID`
  (optional stricter writeback control)
- `ServiceNowBaseUrl` / `SERVICENOW_BASE_URL`,
  `ServiceNowApiTokenSecretArn` / `SERVICENOW_API_TOKEN_SECRET_ARN`,
  `ServiceNowApprovalHmacSecretArn` / `SERVICENOW_APPROVAL_HMAC_SECRET_ARN`,
  `ServiceNowAssignmentGroup` / `SERVICENOW_ASSIGNMENT_GROUP`,
  `ServiceNowTimeoutSeconds` / `SERVICENOW_TIMEOUT_SECONDS`

ServiceNow create requires a signed `servicenow_create_approval` object in the
incoming alert payload. See
[`../integrations/SERVICENOW_OPERATIONS.md`](../integrations/SERVICENOW_OPERATIONS.md).

### `analyst_portal`

Use when operators want the AWS read-only analyst portal and pinned-case Q&A
over retained case evidence. This profile enables `CASE_ARCHIVE_ENABLED`,
`PORTAL_ENABLED`, and `CASE_QA_ENABLED`.

This profile does not enable HTML reports, Splunk writeback, Elasticsearch
queries, ServiceNow actions, SOAR, or any other external write path.

Primary follow-up values:

- `CaseIndexTableName` / `CASE_INDEX_TABLE` (required; SAM/CloudFormation
  creates CaseIndex when non-empty)
- `CaseEmbedLambdaName` / `CASE_EMBED_LAMBDA_NAME` (SAM wires the embed Lambda
  from this parameter when CaseIndex resources are enabled)
- `CaseArchiveBucketName` / `CASE_ARCHIVE_BUCKET` (defaults to
  `OutputBucketName`), `CaseArchivePrefix` / `CASE_ARCHIVE_PREFIX`,
  `CaseArchiveChunksPrefix` / `CASE_ARCHIVE_CHUNKS_PREFIX`,
  `CaseRetentionDays` / `CASE_RETENTION_DAYS`
- `PortalAuthMode` / `PORTAL_AUTH_MODE=jwt|iam`
- `PortalJwtIssuer` / `PORTAL_JWT_ISSUER` and `PortalJwtAudience` /
  `PORTAL_JWT_AUDIENCE` when `PortalAuthMode=jwt`
- `PortalPageSize` / `PORTAL_PAGE_SIZE`, `PortalMaxDetailBytes` /
  `PORTAL_MAX_DETAIL_BYTES`, `PortalChatTimeoutSec` / `PORTAL_CHAT_TIMEOUT_SEC`,
  `PortalChatMaxConcurrency` / `PORTAL_CHAT_MAX_CONCURRENCY`
- `CaseQaEmbeddingModel` / `CASE_QA_EMBEDDING_MODEL`,
  `CaseQaVectorDimensions` / `CASE_QA_VECTOR_DIMENSIONS`,
  `CaseQaContextBudgetChars` / `CASE_QA_CONTEXT_BUDGET_CHARS`,
  `CaseQaMaxAnswerTokens` / `CASE_QA_MAX_ANSWER_TOKENS`
- `ChatSessionsTableName` / `CHAT_SESSIONS_TABLE` and `ChatMessagesTableName` /
  `CHAT_MESSAGES_TABLE` only when `CaseQaChatHistoryEnabled=true` /
  `CASE_QA_CHAT_HISTORY_ENABLED=true`

Diff 1 through Diff 5 deliver archive writes, portal API routes, embed Lambda,
and pinned-case chat synthesis when `analyst_portal` is enabled. Operator detail:
[`../analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../analyst_portal/ANALYST_PORTAL_OPERATIONS.md).

## Advanced Overrides

Use low-level flags only for legacy or lab configs when the capability is not
controlled by a selected profile. Profile-controlled flags (see mapping table):
`HTML_REPORT_ENABLED`, `RAG_ENABLED`, `SPL_QUERY_GENERATION_ENABLED`,
`INVESTIGATION_QUERY_EXECUTION_ENABLED`, `INVESTIGATION_QUERY_BACKEND`,
`ELASTIC_QUERY_GENERATION_ENABLED`, `SERVICENOW_DRAFT_ENABLED`,
`SPLUNK_SINK_ENABLED`, `SERVICENOW_CREATE_ENABLED`,
`SERVICENOW_CREATE_REQUIRES_APPROVAL`, `SIDE_EFFECT_IDEMPOTENCY_ENABLED`,
`CASE_ARCHIVE_ENABLED`, `PORTAL_ENABLED`, `CASE_QA_ENABLED`.

Examples of safe legacy-only overrides:

- enabling `HTML_REPORT_ENABLED` without selecting `html_reports`
- enabling `SPL_QUERY_RAG_ENABLED` after the dedicated Splunk dictionary index is curated
- enabling `ELASTICSEARCH_GROUNDING_ENABLED` after the dedicated Elastic dictionary index is curated
- enabling `QUERY_RESULT_INTERPRETATION_ENABLED` for optional query-result LLM synthesis
- enabling `CASE_QA_CHAT_HISTORY_ENABLED` after chat-history DynamoDB tables are provisioned

Unknown profile names fail startup validation. Invalid boolean overrides also
fail startup validation.

## Related Docs

- [`../rag/RAG_OPERATIONS.md`](../rag/RAG_OPERATIONS.md)
- [`../investigation/SPL_OPERATIONS.md`](../investigation/SPL_OPERATIONS.md)
- [`../investigation/ELASTICSEARCH_OPERATIONS.md`](../investigation/ELASTICSEARCH_OPERATIONS.md)
- [`../integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](../integrations/SPLUNK_WRITEBACK_OPERATIONS.md)
- [`../integrations/SERVICENOW_OPERATIONS.md`](../integrations/SERVICENOW_OPERATIONS.md)
- [`FILE_DROP_AND_RETENTION_OPERATIONS.md`](FILE_DROP_AND_RETENTION_OPERATIONS.md)
- [`../../../config.env.example`](../../../config.env.example)
