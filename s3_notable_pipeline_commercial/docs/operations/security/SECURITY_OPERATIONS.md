# Security Operations

Customer decisions for IAM least privilege, Secrets Manager, outbound TLS,
external action gates, and portal exposure on AWS. LLM trust boundaries and
capability profile semantics are in
[`../../security/ATTACK_LLM_ANALYSIS.md`](../../security/ATTACK_LLM_ANALYSIS.md).

Implemented stack resources and IAM policies are defined in
[`../../../deploy/aws/template-sam.yaml`](../../../deploy/aws/template-sam.yaml).

Customer CMK provisioning and key policies:
[`../deployment/KMS_CUSTOMER_KEY.md`](../deployment/KMS_CUSTOMER_KEY.md).

## What This Controls

Runtime security posture for the S3-triggered Lambda stack: which AWS APIs and
customer HTTPS endpoints the functions may call, how integration secrets are
loaded, how outbound URLs are validated, and how external writes (Splunk notable
update, ServiceNow create) are gated and deduplicated.

## Recommended Starting Posture

- Keep `CapabilityProfiles=core` and `SplunkSinkMode=s3` until a customer-approved
  rollout plan exists for external actions.
- Prefer `action_gated` for production Splunk writeback and ServiceNow create;
  keep `ticket_draft` for draft-only JSON output when create is not approved.
- Store Splunk, Elasticsearch, MCP, ServiceNow API, and ServiceNow approval HMAC
  secrets in AWS Secrets Manager; pass only the secret ARN to the stack (default
  placeholder `*` grants no `GetSecretValue` IAM until a real ARN is supplied).
- Use HTTPS integration base URLs without userinfo. Private, loopback, link-local,
  or reserved IP targets require `AllowPrivateOutboundEndpoints=true` (maps to
  `ALLOW_PRIVATE_OUTBOUND_ENDPOINTS`).
- Treat generated SPL, Elasticsearch Query DSL, and ticket payloads as untrusted
  until policy validation passes.
- For the analyst portal, use `PortalAuthMode=jwt` with exact JWT issuer,
  audience, optional `PortalJwtTenantId`, analyst role or scope, and
  `PortalCorsAllowedOrigins`. Production Entra browsers use `VITE_PORTAL_AUTH_MODE=entra`
  (MSAL PKCE, no client secret) and API access tokens — not ID tokens. Do not put
  tokens in static assets or logs. `PortalAuthMode=iam` is for SigV4 API automation,
  not analyst browser sessions.

## IAM Least Privilege

The SAM template attaches scoped inline policies per function. There is no blanket
`secretsmanager:*` or `s3:*` grant.

### `notable-analyzer-s3` (main pipeline)

| Permission | Scope |
| --- | --- |
| S3 read | Input bucket only |
| S3 write | Output bucket (`reports/` and case archive prefixes when portal resources exist) |
| `bedrock:InvokeModel` | Customer-selected analysis and embedding model resources |
| OpenSearch HTTP | Customer OpenSearch domain indexes required by enabled retrieval lanes |
| `secretsmanager:GetSecretValue` | Only when the corresponding secret ARN parameter is not `*` |
| DynamoDB | `SideEffectIdempotencyTable` (Put/Get/Update/Delete); `CaseIndexTable` when portal enabled |
| `sqs:SendMessage` | Durable case-embed queue when case archive is enabled |
| CloudWatch Logs | Function log group only |

Secret IAM conditions in the template: `HasSplunkMcpSecret`, `HasServiceNowSecret`,
`HasServiceNowApprovalSecret`, `HasElasticsearchSecret`, and `IsNotableRest` for
`SplunkApiTokenSecretArn`. Leaving a secret ARN at `*` omits that statement.

### `notable-portal-api` (when `CaseIndexTableName` is set)

| Permission | Scope |
| --- | --- |
| DynamoDB | CaseIndex read (`Query`, `GetItem`, `DescribeTable`); optional chat history tables |
| S3 | Read-only on case archive, chunk, and report prefixes |
| `bedrock:InvokeModel` | Portal chat synthesis model ARN only |
| CloudWatch Logs | Portal function log group only |

Portal API Gateway routes use JWT authorizer (`PortalJwtIssuer`, `PortalJwtAudience`)
when configured, or `AWS_IAM` when `PortalAuthMode=iam`. Health and ready routes
are unauthenticated by design.

### S3 buckets

Input, output, and optional portal UI buckets block public access and use
AES256 default encryption in the template.

## Secrets Manager

| Secret ARN parameter | Used for | IAM granted when |
| --- | --- | --- |
| `SplunkApiTokenSecretArn` | Splunk REST token for `notable_rest` writeback and read-only search | `SplunkSinkMode=notable_rest` (required by deploy rule) |
| `SplunkMcpAuthSecretArn` | Bearer token for MCP-over-HTTPS investigation | ARN is not `*` |
| `ElasticsearchApiKeySecretArn` | Elasticsearch API key header | ARN is not `*` |
| `ServiceNowApiTokenSecretArn` | ServiceNow REST bearer token | ARN is not `*` |
| `ServiceNowApprovalHmacSecretArn` | HMAC key for signed create approvals | ARN is not `*` |

Runtime resolution (`resolve_secret_string` in `runtime_security.py`) accepts a
plain string secret or JSON with a configurable field (default `token` for Splunk;
approval key field per ServiceNow integration docs).

Operational expectations:

- Rotate secrets in Secrets Manager; update the ARN only when the secret resource
  changes.
- Do not log secret values, API tokens, or approval HMAC keys.
- Split Splunk read vs write tokens where governance allows, even though both
  may reference `SplunkApiTokenSecretArn` today.

## TLS And Outbound Endpoint Validation

All Splunk, Elasticsearch, ServiceNow, and MCP base URLs pass through
`validate_https_url` before outbound calls:

- Scheme must be `https`.
- URLs must not include embedded userinfo.
- Hostnames resolving to private, loopback, link-local, or reserved IPs are
  rejected unless `ALLOW_PRIVATE_OUTBOUND_ENDPOINTS=true`.
- `localhost` and `*.localhost` are rejected unless private endpoints are explicitly
  allowed.

Outbound HTTP clients use `verify=True` (system trust store). There is no
`SPLUNK_CA_BUNDLE` or custom CA path in the AWS runtime today.

The portal uses a regional API Gateway HTTPS endpoint. Commercial v1
intentionally excludes CloudFront and Lambda Function URLs. The private SPA bucket blocks
public access and is read through the portal Lambda with a scoped object-read
permission.

## External Action Gates

External writes should roll out only with explicit capability profiles and
deploy-time guards.

### Capability profiles

| Profile | External risk |
| --- | --- |
| `core` | S3 reports and Bedrock only |
| `spl_readonly` / `elastic_readonly` | Read-only HTTPS queries after allowlist validation |
| `ticket_draft` | ServiceNow draft fields in JSON; no POST |
| `action_gated` | Enables `SERVICENOW_CREATE_ENABLED`, `SIDE_EFFECT_IDEMPOTENCY_ENABLED`, and related flags; preferred for production creates |

Profile detail: [`../platform/CAPABILITY_PROFILES.md`](../platform/CAPABILITY_PROFILES.md).

### Splunk notable writeback

- Triggered when `SplunkSinkMode=notable_rest` (SAM parameter / `SPLUNK_SINK_MODE`).
- Requires `SplunkBaseUrl` and a real `SplunkApiTokenSecretArn` (deploy rules enforce
  this for `notable_rest`).
- Optional `SplunkRequirePayloadFindingId=true` requires a payload
  `finding_id` / `notable_id` / `sid` consistent with the S3 object key stem.
- Read-only Splunk investigation uses index, command, field, row, and timeout
  allowlists before execution; denied commands never run.

Writeback detail: [`../integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](../integrations/SPLUNK_WRITEBACK_OPERATIONS.md).

### ServiceNow create

- Requires `action_gated` (or explicit `SERVICENOW_CREATE_ENABLED=true` in lab
  configs) plus `ServiceNowApiTokenSecretArn`.
- When `SERVICENOW_CREATE_REQUIRES_APPROVAL=true` (default under `action_gated`),
  create requires `approved: true`, `approved_by`, and a valid HMAC-SHA256
  `signature` over the canonical approval payload and `correlation_id`.
- Config startup fails when create requires approval but
  `ServiceNowApprovalHmacSecretArn` is unset.
- Denied or malformed approvals do not make outbound calls.

Create detail: [`../integrations/SERVICENOW_OPERATIONS.md`](../integrations/SERVICENOW_OPERATIONS.md).

### DynamoDB side-effect idempotency

When `action_gated` enables `SIDE_EFFECT_IDEMPOTENCY_ENABLED`, the template
provisions `SideEffectIdempotencyTable` with TTL. Reservations apply to Splunk
notable update (`finding_id` key) and ServiceNow incident create
(`correlation_id` key). S3 report writes, read-only queries, and Bedrock calls
are not deduplicated.

## Data Handling

- Raw S3 input is size bounded by `MaxDecompressedInputBytes` before prompt
  construction.
- Case archive envelopes, chunks, and CaseIndex rows follow `CaseRetentionDays`
  lifecycle and TTL when the portal profile is enabled.
- Splunk result samples drop `_raw`; set `SplunkSearchAllowedFields` to restrict
  sample fields further.
- Elasticsearch result samples are restricted to `ElasticsearchAllowedFields`.

## Deployment Checks

1. Confirm S3 buckets have public access blocked and server-side encryption enabled.
2. Confirm `LambdaReservedConcurrentExecutions` is set to protect downstream systems.
3. Confirm IAM policies grant only required S3, Secrets Manager, Bedrock, DynamoDB,
   and Lambda invoke permissions (no wildcard secret ARNs in production).
4. Confirm denied query or action paths do not make outbound calls.
5. Confirm portal API CORS allows only approved browser origins and
   `POST /api/chat` returns `answer`, `answer_status` (`answered`, `unknown`, or
   `refused`), and optional `session_id` only — no tool execution from chat.
6. Confirm `CapabilityProfiles` matches the intended external-action posture before
   enabling `SplunkSinkMode=notable_rest` or ServiceNow create secrets.

## Related Docs

- [`../../security/ATTACK_LLM_ANALYSIS.md`](../../security/ATTACK_LLM_ANALYSIS.md) — LLM trust boundaries and profile semantics
- [`../platform/CAPABILITY_PROFILES.md`](../platform/CAPABILITY_PROFILES.md) — profile rollout
- [`../analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../analyst_portal/ANALYST_PORTAL_OPERATIONS.md) — portal auth and CORS
- [`../integrations/SERVICENOW_OPERATIONS.md`](../integrations/SERVICENOW_OPERATIONS.md) — approval payload and idempotency
- [`../integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](../integrations/SPLUNK_WRITEBACK_OPERATIONS.md) — notable REST writeback
- [`../../testing/TESTING.md`](../../testing/TESTING.md) — unit and integration validation
