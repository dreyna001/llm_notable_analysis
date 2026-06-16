# Capability Profiles

Capability profiles are the operator-facing way to enable supported feature
bundles on AWS. Set `CAPABILITY_PROFILES` on the Lambda function (via SAM or
CloudFormation parameters), then configure only the endpoints, secret ARNs, and
tuning values required by that profile.

Low-level `*_ENABLED` flags remain supported for legacy lab configs when no
selected profile controls that capability, but profiles are the preferred
operator workflow. When a selected profile controls a capability, the profile
takes precedence.

## Supported Profiles

| Profile | Enables | Risk class |
|---------|---------|------------|
| `core` | S3-triggered ingest, Bedrock analysis, markdown + JSON reports under `reports/`. | Read/write within customer S3 buckets; Bedrock inference. |
| `html_reports` | Static HTML reports as a third S3 artifact next to markdown and JSON. | Additional S3 report artifact only. |
| `rag` | General SOC RAG context from a Bedrock Knowledge Base in the main analysis prompt. | Read-only KB retrieval; advisory context only. |
| `spl_readonly` | SPL query generation and bounded read-only Splunk investigation execution. | Read-only external Splunk or MCP queries. |
| `elastic_readonly` | Elasticsearch Query DSL generation and bounded read-only `_search` execution. | Read-only external Elasticsearch queries. |
| `ticket_draft` | ServiceNow incident draft payloads in JSON reports. | Report content only; no ServiceNow POST. |
| `action_gated` | Splunk notable writeback (when `SPLUNK_SINK_MODE=notable_rest`), ServiceNow draft/create, signed ServiceNow approval, and DynamoDB side-effect idempotency. | External write/action path. |
| `analyst_portal` | S3 case archive, DynamoDB CaseIndex, read-only portal API, and retrieval-bound pinned-case Q&A. | Read-only analyst browse/chat over retained case evidence. |

Profiles are additive. `core` is automatically included when omitted.
Profiles may be separated with commas or semicolons.

```bash
CAPABILITY_PROFILES=core
CAPABILITY_PROFILES=core,html_reports,rag
CAPABILITY_PROFILES=core,rag,spl_readonly
CAPABILITY_PROFILES=core,rag,elastic_readonly
CAPABILITY_PROFILES=core,ticket_draft
CAPABILITY_PROFILES=core,action_gated
CAPABILITY_PROFILES=core,analyst_portal
```

SAM parameter: `CapabilityProfiles`

## Operator Workflow

1. Start with `CAPABILITY_PROFILES=core` and `SplunkSinkMode=s3`.
2. Add one profile at a time in a non-production stack.
3. Configure required secret ARNs, URLs, Knowledge Base IDs, and tuning values
   for the selected profile.
4. Run the smoke steps in the relevant operations guide and `../testing/TESTING.md`.
5. Promote the same profile list after ownership, approval boundaries, and
   rollback expectations are documented.

## Profile Details

### `html_reports`

Use when operators want static HTML dashboards in addition to markdown and JSON
reports in S3.

Primary follow-up values:

- `HTML_REPORT_ENABLED` (set by profile)
- `OUTPUT_BUCKET_NAME`, `OUTPUT_PREFIX`

### `rag`

Use after the general Bedrock Knowledge Base source documents are curated and
owned. Retrieved content is advisory context, not direct alert evidence.

Primary follow-up values:

- `RAG_BEDROCK_KB_ID`
- `RAG_MAX_SNIPPETS`, `RAG_CONTEXT_BUDGET_CHARS`, `RAG_FAILURE_MODE`
- Lambda IAM permission for `bedrock:Retrieve` on that Knowledge Base

### `spl_readonly`

Use when Splunk owners approve generated SPL and bounded read-only execution.
This profile does not enable Splunk notable writeback.

Primary follow-up values:

- `INVESTIGATION_QUERY_EXECUTOR=rest|mcp`
- `SPLUNK_SEARCH_ALLOWED_INDEXES`, `SPLUNK_SEARCH_ALLOWED_COMMANDS`,
  `SPLUNK_SEARCH_DENIED_COMMANDS`, `SPLUNK_SEARCH_ALLOWED_FIELDS`
- `SPLUNK_SEARCH_MAX_TIME_RANGE`, `SPLUNK_SEARCH_MAX_ROWS`,
  `SPLUNK_SEARCH_TIMEOUT_SECONDS`
- `SPLUNK_BASE_URL` and `SPLUNK_API_TOKEN_SECRET_ARN` when executor is `rest`
- `SPLUNK_MCP_ENDPOINT` and `SPLUNK_MCP_AUTH_SECRET_ARN` when executor is `mcp`
- optional `SPL_QUERY_RAG_BEDROCK_KB_ID` for dedicated SPL grounding

`spl_readonly` and `elastic_readonly` are mutually exclusive. Choose one
read-only investigation backend per deployment.

### `elastic_readonly`

Use when Elasticsearch owners approve generated Query DSL and bounded read-only
`_search` execution.

Primary follow-up values:

- `ELASTICSEARCH_BASE_URL` (HTTPS required when execution is enabled)
- `ELASTICSEARCH_API_KEY_SECRET_ARN`
- `ELASTICSEARCH_INDEX_ALLOWLIST`, `ELASTICSEARCH_ALLOW_WILDCARD_INDEXES`
- `ELASTICSEARCH_TIMESTAMP_FIELD`, `ELASTICSEARCH_ALLOWED_FIELDS`
- `ELASTICSEARCH_MAX_TIME_RANGE`, `ELASTICSEARCH_MAX_ROWS`,
  `ELASTICSEARCH_TIMEOUT_SECONDS`
- optional `ELASTICSEARCH_GROUNDING_BEDROCK_KB_ID`

### `ticket_draft`

Use when operators want ServiceNow incident drafts in JSON reports without
creating incidents.

Primary follow-up values:

- `SERVICENOW_ASSIGNMENT_GROUP`

### `action_gated`

Use only after owners approve external write/action behavior.

This profile enables:

- Splunk notable comment writeback when `SPLUNK_SINK_MODE=notable_rest`
- ServiceNow incident create (still approval-gated and signature-required)
- DynamoDB side-effect idempotency

Side-effect idempotency applies only to:

- Splunk notable update (`finding_id` key)
- ServiceNow incident create (draft `correlation_id` key)

It does not deduplicate S3 report writes, read-only Splunk or Elastic queries,
or Bedrock calls.

Primary follow-up values:

- `SIDE_EFFECT_IDEMPOTENCY_TABLE`, `SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS`,
  `SIDE_EFFECT_IDEMPOTENCY_LOCK_SECONDS`
- `SPLUNK_BASE_URL`, `SPLUNK_API_TOKEN_SECRET_ARN`, `SPLUNK_NOTABLE_UPDATE_PATH`
- `SPLUNK_REQUIRE_PAYLOAD_FINDING_ID` (optional stricter writeback control)
- `SERVICENOW_BASE_URL`, `SERVICENOW_API_TOKEN_SECRET_ARN`,
  `SERVICENOW_APPROVAL_HMAC_SECRET_ARN`, `SERVICENOW_ASSIGNMENT_GROUP`,
  `SERVICENOW_TIMEOUT_SECONDS`

ServiceNow create requires a signed `servicenow_create_approval` object in the
incoming alert payload. See `SERVICENOW_OPERATIONS.md`.

### `analyst_portal`

Use when operators want the AWS read-only analyst portal and pinned-case Q&A
over retained case evidence. This profile enables `CASE_ARCHIVE_ENABLED`,
`PORTAL_ENABLED`, and `CASE_QA_ENABLED`.

This profile does not enable HTML reports, Splunk writeback, Elasticsearch
queries, ServiceNow actions, SOAR, or any other external write path.

Primary follow-up values:

- `CASE_INDEX_TABLE` (required; SAM/CloudFormation creates CaseIndex when
  `CaseIndexTableName` is non-empty)
- `CASE_ARCHIVE_BUCKET` (defaults to `OUTPUT_BUCKET_NAME`), `CASE_ARCHIVE_PREFIX`,
  `CASE_ARCHIVE_CHUNKS_PREFIX`, `CASE_RETENTION_DAYS`
- `PORTAL_AUTH_MODE=jwt|iam`
- `PORTAL_JWT_ISSUER` and `PORTAL_JWT_AUDIENCE` when `PORTAL_AUTH_MODE=jwt`
- `PORTAL_PAGE_SIZE`, `PORTAL_MAX_DETAIL_BYTES`, `PORTAL_CHAT_TIMEOUT_SEC`,
  `PORTAL_CHAT_MAX_CONCURRENCY`
- `CASE_QA_EMBEDDING_MODEL`, `CASE_QA_VECTOR_DIMENSIONS`,
  `CASE_QA_CONTEXT_BUDGET_CHARS`, `CASE_QA_MAX_ANSWER_TOKENS`
- `CHAT_SESSIONS_TABLE` and `CHAT_MESSAGES_TABLE` only when
  `CASE_QA_CHAT_HISTORY_ENABLED=true`

Diff 1 only adds the profile, validation, environment contract, and deployment
scaffolding. Archive writes, portal API routes, and chat synthesis are delivered
by the later Wave 2 diffs.

## Advanced Overrides

Use low-level flags only for legacy or lab configs when the capability is not
controlled by a selected profile. Examples:

- enabling `HTML_REPORT_ENABLED` without selecting `html_reports`
- enabling `SPL_QUERY_RAG_ENABLED` after the dedicated SPL Knowledge Base is curated
- enabling `ELASTICSEARCH_GROUNDING_ENABLED` after the dedicated Elastic Knowledge Base is curated
- enabling `CASE_QA_CHAT_HISTORY_ENABLED` after chat-history DynamoDB tables are provisioned

Unknown profile names fail startup validation. Invalid boolean overrides also
fail startup validation.

## Related Docs

- [`RAG_OPERATIONS.md`](RAG_OPERATIONS.md)
- [`SPL_OPERATIONS.md`](SPL_OPERATIONS.md)
- [`ELASTICSEARCH_OPERATIONS.md`](ELASTICSEARCH_OPERATIONS.md)
- [`SPLUNK_WRITEBACK_OPERATIONS.md`](SPLUNK_WRITEBACK_OPERATIONS.md)
- [`SERVICENOW_OPERATIONS.md`](SERVICENOW_OPERATIONS.md)
- [`FILE_DROP_AND_RETENTION_OPERATIONS.md`](FILE_DROP_AND_RETENTION_OPERATIONS.md)
- [`../../config.env.example`](../../config.env.example)
