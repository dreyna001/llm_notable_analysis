# AWS Operations Guide Index

Customer-facing AWS tuning guides: SAM/CloudFormation parameters, Lambda environment
variables, and validation steps without code changes.

**Deploy navigation:** [`../../README.md`](../../README.md) contains the complete
Path A (core), Path B (customer-default), and Path C (custom profiles) journeys.

## Deployment

| Guide | Purpose |
|-------|---------|
| [`deployment/GOVCLOUD_CUSTOMER_CONFIGURATION.md`](deployment/GOVCLOUD_CUSTOMER_CONFIGURATION.md) | GovCloud product boundary and per-customer operationalization inputs. |
| [`deployment/CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md`](deployment/CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md) | What customers provision vs what the SAM stack creates. |
| [`deployment/GOVCLOUD_CUSTOMER_DEFAULT_DEPLOYMENT.md`](deployment/GOVCLOUD_CUSTOMER_DEFAULT_DEPLOYMENT.md) | Copy-and-fill preset for `core,rag,analyst_portal`. |
| [`deployment/DEPLOYMENT_IMAGE_STEPS.md`](deployment/DEPLOYMENT_IMAGE_STEPS.md) | Build, push, deploy Lambda image; rollback guidance. |
| [`deployment/VPC_NETWORK_PREREQUISITES.md`](deployment/VPC_NETWORK_PREREQUISITES.md) | VPC, subnets, NAT/endpoints, Lambda security groups. |
| [`deployment/OPENSEARCH_PROVISIONING.md`](deployment/OPENSEARCH_PROVISIONING.md) | Customer-managed VPC OpenSearch; Phase A/B access policy. |
| [`deployment/BEDROCK_ACCOUNT_ENABLEMENT.md`](deployment/BEDROCK_ACCOUNT_ENABLEMENT.md) | Bedrock model enablement and ID/ARN mapping. |
| [`deployment/KMS_CUSTOMER_KEY.md`](deployment/KMS_CUSTOMER_KEY.md) | Customer CMK key policies for stack-encrypted resources. |
| [`deployment/PORTAL_JWT_IDENTITY.md`](deployment/PORTAL_JWT_IDENTITY.md) | OIDC/JWT IdP setup and claim mapping for analyst portal. |

## Platform

Capability profiles (`core` default, optional bundles), S3 intake/retention, MITRE
validation, recovery.

| Guide | Purpose |
|-------|---------|
| [`platform/CAPABILITY_PROFILES.md`](platform/CAPABILITY_PROFILES.md) | Supported feature bundles (`CapabilityProfiles` / `CAPABILITY_PROFILES`). |
| [`platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](platform/FILE_DROP_AND_RETENTION_OPERATIONS.md) | S3 prefixes, gzip, lifecycle, size limits, report artifacts. |
| [`platform/MITRE_TTP_OPERATIONS.md`](platform/MITRE_TTP_OPERATIONS.md) | Bundled TTP IDs and refresh workflow. |
| [`platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md) | Failure behavior, retries, ownership. |

## Analyst Portal

Requires `analyst_portal` and non-empty `CaseIndexTableName`.

| Guide | Purpose |
|-------|---------|
| [`analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](analyst_portal/ANALYST_PORTAL_OPERATIONS.md) | Portal stack, archive, chat, and day-two ops. |
| [`frontend/analyst-portal/README.md`](../../frontend/analyst-portal/README.md) | SPA local dev, build, upload, and Playwright E2E. |
| [`analyst_portal/ANALYST_PORTAL_THEME.md`](analyst_portal/ANALYST_PORTAL_THEME.md) | Federal SOC Dark theme reference. |

## LLM Inference

| Guide | Purpose |
|-------|---------|
| [`llm/LLM_INFERENCE_OPERATIONS.md`](llm/LLM_INFERENCE_OPERATIONS.md) | Bedrock routing, timeouts, structured output, rollout. |

## RAG and OpenSearch

Requires `rag` profile. Application-managed OpenSearch retrieval in GovCloud.

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

| Guide | Purpose |
|-------|---------|
| [`integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](integrations/SPLUNK_WRITEBACK_OPERATIONS.md) | Notable comment writeback when `action_gated` and `SplunkSinkMode=notable_rest`. |
| [`integrations/SERVICENOW_OPERATIONS.md`](integrations/SERVICENOW_OPERATIONS.md) | Incident draft/create and approval payload. |

## Security

| Guide | Purpose |
|-------|---------|
| [`security/SECURITY_OPERATIONS.md`](security/SECURITY_OPERATIONS.md) | IAM, Secrets Manager, endpoint validation, hardening. |

Deeper threat-model notes: [`../security/ATTACK_LLM_ANALYSIS.md`](../security/ATTACK_LLM_ANALYSIS.md).

## Testing

| Guide | Purpose |
|-------|---------|
| [`../testing/TESTING.md`](../testing/TESTING.md) | Unit, smoke, and optional integration commands. |
