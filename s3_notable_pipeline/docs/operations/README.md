# AWS Operations Guide Index

Customer-facing AWS tuning guides: SAM/CloudFormation parameters, Lambda environment
variables, and validation steps without code changes.

**Deploy navigation:** start at [`../../README.md`](../../README.md) for Path A (core),
then [`../README.md`](../README.md) for Path B (RAG + portal) or Path C (custom profiles).

Start with [`platform/CAPABILITY_PROFILES.md`](platform/CAPABILITY_PROFILES.md) and
[`../../README.md`](../../README.md) deploy parameters when tuning an existing stack.
Set SAM `CapabilityProfiles` (Lambda `CAPABILITY_PROFILES`); profiles are additive and
`core` is included when omitted. Then open the category that matches your task.

## Common Guide Shape

- **What This Controls** — runtime behavior on AWS.
- **Recommended Starting Posture** — conservative defaults for first rollout.
- **Customer Decisions** — per-environment choices.
- **Config Quick Reference** — SAM parameters and Lambda env vars.
- **Validation And Rollout** — safe proof steps.
- **Related Docs** — deployment, security, parity, and testing context.

## Deployment

- [`deployment/GOVCLOUD_CUSTOMER_CONFIGURATION.md`](deployment/GOVCLOUD_CUSTOMER_CONFIGURATION.md) — reusable product boundary and per-customer operationalization inputs for `us-gov-east-1`.
- [`deployment/CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md`](deployment/CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md) — what customers provision vs what the SAM stack creates.

Lambda container image, ECR, and SAM deploy flow.

| Guide | Purpose |
|-------|---------|
| [`deployment/DEPLOYMENT_IMAGE_STEPS.md`](deployment/DEPLOYMENT_IMAGE_STEPS.md) | Build, push, and deploy the Lambda image via SAM. |
| [`deployment/VPC_NETWORK_PREREQUISITES.md`](deployment/VPC_NETWORK_PREREQUISITES.md) | VPC, subnets, NAT/endpoints, Lambda security groups before RAG/portal. |
| [`deployment/OPENSEARCH_PROVISIONING.md`](deployment/OPENSEARCH_PROVISIONING.md) | Provision customer-managed VPC OpenSearch before RAG/portal deploy. |
| [`deployment/BEDROCK_ACCOUNT_ENABLEMENT.md`](deployment/BEDROCK_ACCOUNT_ENABLEMENT.md) | Enable Bedrock models and map IDs/ARNs to SAM before deploy. |
| [`deployment/KMS_CUSTOMER_KEY.md`](deployment/KMS_CUSTOMER_KEY.md) | Customer CMK key policies for stack-encrypted resources. |
| [`deployment/PORTAL_JWT_IDENTITY.md`](deployment/PORTAL_JWT_IDENTITY.md) | OIDC/JWT IdP setup and claim mapping for analyst portal. |
| [`../../README.md`](../../README.md) | Fast-path deploy and test scripts. |

## Platform

Capability profiles (`core` default, optional `html_reports`), S3 intake/retention,
MITRE validation, recovery.

| Guide | Purpose |
|-------|---------|
| [`platform/CAPABILITY_PROFILES.md`](platform/CAPABILITY_PROFILES.md) | Supported feature bundles (`CapabilityProfiles` / `CAPABILITY_PROFILES`). |
| [`platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](platform/FILE_DROP_AND_RETENTION_OPERATIONS.md) | S3 prefixes, gzip, lifecycle, size limits, report artifacts. |
| [`platform/MITRE_TTP_OPERATIONS.md`](platform/MITRE_TTP_OPERATIONS.md) | Bundled TTP IDs and refresh workflow. |
| [`platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md) | Failure behavior, retries, ownership. |

## Analyst Portal

Requires `analyst_portal` and non-empty `CaseIndexTableName`. S3 case archive,
DynamoDB CaseIndex, read-only portal API, pinned-case Q&A, optional static SPA.

| Guide | Purpose |
|-------|---------|
| [`analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](analyst_portal/ANALYST_PORTAL_OPERATIONS.md) | Portal stack, archive, chat, and day-two ops. |
| [`analyst_portal/ANALYST_PORTAL_THEME.md`](analyst_portal/ANALYST_PORTAL_THEME.md) | Federal SOC Dark theme: palette, fonts, radius, WCAG notes, visual reference. |

## LLM Inference

Part of `core` on every stack: Bedrock model id, Lambda timeout, inference budgets.

| Guide | Purpose |
|-------|---------|
| [`llm/LLM_INFERENCE_OPERATIONS.md`](llm/LLM_INFERENCE_OPERATIONS.md) | Bedrock routing, timeouts, structured output, rollout. |

## RAG and OpenSearch

Requires `rag` profile. S3 manifest ingestion, Bedrock embeddings, and OpenSearch retrieval tuning.

| Guide | Purpose |
|-------|---------|
| [`rag/KNOWLEDGE_BASE_OPERATIONS.md`](rag/KNOWLEDGE_BASE_OPERATIONS.md) | Source content, manifest, and OpenSearch indexing lifecycle. |
| [`rag/RAG_OPERATIONS.md`](rag/RAG_OPERATIONS.md) | RAG enablement, failure mode, snippets, budgets. |

## Investigation

Requires `spl_readonly` or `elastic_readonly` (mutually exclusive).

| Guide | Purpose |
|-------|---------|
| [`investigation/SPL_OPERATIONS.md`](investigation/SPL_OPERATIONS.md) | SPL generation, SIEM-dictionary grounding, Splunk REST/MCP execution. |
| [`investigation/ELASTICSEARCH_OPERATIONS.md`](investigation/ELASTICSEARCH_OPERATIONS.md) | Query DSL generation and read-only `_search`. |

## Integrations

`ticket_draft` for ServiceNow drafts in JSON reports (no POST); `action_gated` for
Splunk writeback when `SplunkSinkMode=notable_rest`, approval-gated ServiceNow
create, and DynamoDB side-effect idempotency.

| Guide | Purpose |
|-------|---------|
| [`integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](integrations/SPLUNK_WRITEBACK_OPERATIONS.md) | Notable comment writeback when `action_gated` and `SplunkSinkMode=notable_rest`. |
| [`integrations/SERVICENOW_OPERATIONS.md`](integrations/SERVICENOW_OPERATIONS.md) | Incident draft/create and approval payload. |

## Security

IAM, secrets, TLS, and action gates regardless of profiles.

| Guide | Purpose |
|-------|---------|
| [`security/SECURITY_OPERATIONS.md`](security/SECURITY_OPERATIONS.md) | IAM, Secrets Manager, endpoint validation, hardening. |

Deeper threat-model notes: [`../security/ATTACK_LLM_ANALYSIS.md`](../security/ATTACK_LLM_ANALYSIS.md).

## Testing

| Guide | Purpose |
|-------|---------|
| [`../testing/TESTING.md`](../testing/TESTING.md) | Unit, smoke, and optional integration commands. |
