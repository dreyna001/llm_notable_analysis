# AWS Operations Guide Index

Category index for commercial AWS operator runbooks (SAM parameters, Lambda
environment variables, validation). Profile mappings and constraints:
[`platform/CAPABILITY_PROFILES.md`](platform/CAPABILITY_PROFILES.md).

**Deploy navigation:** [`../../README.md`](../../README.md) contains the complete
Path A (core), Path B (customer-default), and Path C (custom profiles) journeys.

## Deployment

| Guide | Purpose |
|-------|---------|
| [`deployment/COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md`](deployment/COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md) | Product boundary and per-customer operationalization inputs. |
| [`deployment/CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md`](deployment/CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md) | Customer-provisioned vs stack-created resources. |
| [`deployment/DEPLOYMENT_IMAGE_STEPS.md`](deployment/DEPLOYMENT_IMAGE_STEPS.md) | Build, push, and deploy the Lambda image via SAM. |
| [`deployment/VPC_NETWORK_PREREQUISITES.md`](deployment/VPC_NETWORK_PREREQUISITES.md) | VPC, subnets, NAT/endpoints, Lambda security groups. |
| [`deployment/OPENSEARCH_PROVISIONING.md`](deployment/OPENSEARCH_PROVISIONING.md) | Customer-managed VPC OpenSearch before RAG/portal. |
| [`deployment/BEDROCK_ACCOUNT_ENABLEMENT.md`](deployment/BEDROCK_ACCOUNT_ENABLEMENT.md) | Bedrock model enablement and SAM ID/ARN mapping. |
| [`deployment/KMS_CUSTOMER_KEY.md`](deployment/KMS_CUSTOMER_KEY.md) | Customer CMK policies for stack-encrypted resources. |
| [`deployment/PORTAL_JWT_IDENTITY.md`](deployment/PORTAL_JWT_IDENTITY.md) | OIDC/JWT IdP setup and claim mapping. |
| [`deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`](deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md) | SAM preset for `core,rag,analyst_portal`. |
| [`../../README.md`](../../README.md) | Complete Path A/B/C deploy journeys and validation. |

## Platform

| Guide | Purpose |
|-------|---------|
| [`platform/CAPABILITY_PROFILES.md`](platform/CAPABILITY_PROFILES.md) | Feature bundles (`CapabilityProfiles` / `CAPABILITY_PROFILES`). |
| [`platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](platform/FILE_DROP_AND_RETENTION_OPERATIONS.md) | S3 prefixes, gzip, lifecycle, report artifacts. |
| [`platform/MITRE_TTP_OPERATIONS.md`](platform/MITRE_TTP_OPERATIONS.md) | Bundled TTP IDs and refresh workflow. |
| [`platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md) | Failure behavior, retries, ownership. |

## Analyst Portal

| Guide | Purpose |
|-------|---------|
| [`analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](analyst_portal/ANALYST_PORTAL_OPERATIONS.md) | Architecture, auth, readiness, day-two ops. |
| [`analyst_portal/ANALYST_PORTAL_THEME.md`](analyst_portal/ANALYST_PORTAL_THEME.md) | Federal SOC Dark theme reference. |
| [`../../frontend/analyst-portal/README.md`](../../frontend/analyst-portal/README.md) | SPA build, upload, Playwright E2E. |

## LLM Inference

| Guide | Purpose |
|-------|---------|
| [`llm/LLM_INFERENCE_OPERATIONS.md`](llm/LLM_INFERENCE_OPERATIONS.md) | Bedrock routing, timeouts, structured output. |

## RAG and OpenSearch

| Guide | Purpose |
|-------|---------|
| [`rag/KNOWLEDGE_BASE_OPERATIONS.md`](rag/KNOWLEDGE_BASE_OPERATIONS.md) | Corpus source, manifest, indexing lifecycle. |
| [`rag/RAG_OPERATIONS.md`](rag/RAG_OPERATIONS.md) | Retrieval enablement, failure mode, snippets, budgets. |

## Investigation

| Guide | Purpose |
|-------|---------|
| [`investigation/SPL_OPERATIONS.md`](investigation/SPL_OPERATIONS.md) | SPL generation and Splunk REST/MCP execution. |
| [`investigation/ELASTICSEARCH_OPERATIONS.md`](investigation/ELASTICSEARCH_OPERATIONS.md) | Query DSL and read-only `_search`. |

## Integrations

| Guide | Purpose |
|-------|---------|
| [`integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](integrations/SPLUNK_WRITEBACK_OPERATIONS.md) | Notable writeback (`action_gated`, `SplunkSinkMode=notable_rest`). |
| [`integrations/SERVICENOW_OPERATIONS.md`](integrations/SERVICENOW_OPERATIONS.md) | Incident draft/create and approval payload. |

## Security

| Guide | Purpose |
|-------|---------|
| [`security/SECURITY_OPERATIONS.md`](security/SECURITY_OPERATIONS.md) | IAM, Secrets Manager, endpoint validation. |

Deeper threat-model notes: [`../security/ATTACK_LLM_ANALYSIS.md`](../security/ATTACK_LLM_ANALYSIS.md).

## Testing

| Guide | Purpose |
|-------|---------|
| [`../testing/TESTING.md`](../testing/TESTING.md) | Unit, smoke, Wave 1, and staging commands. |
