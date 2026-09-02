# Azure operations documentation

Category index for Azure Government operator runbooks (Bicep parameters, Function
environment variables, validation). Profile mappings and constraints:
[`platform/CAPABILITY_PROFILES.md`](platform/CAPABILITY_PROFILES.md).

**Deploy navigation:** [`../../README.md`](../../README.md) contains the complete
Path A (core), Path B (customer-default), and Path C (custom profiles) journeys.

## Deployment

| Guide | Purpose |
| --- | --- |
| [`deployment/AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md`](deployment/AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md) | Customer decisions and operationalization inputs. |
| [`deployment/DEPLOYMENT_IMAGE_STEPS.md`](deployment/DEPLOYMENT_IMAGE_STEPS.md) | Build, push, and deploy the immutable container image via Bicep. |
| [`deployment/AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md`](deployment/AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md) | Bicep preset for `core,rag,analyst_portal`. |
| [`deployment/AZURE_UPGRADE_AND_ROLLBACK.md`](deployment/AZURE_UPGRADE_AND_ROLLBACK.md) | Supported release upgrade, validation, and rollback contract. |
| [`ANALYST_PORTAL_DEPLOYMENT.md`](ANALYST_PORTAL_DEPLOYMENT.md) | Portal JWT, Entra, and Front Door private-link gate. |
| [`../../README.md`](../../README.md) | Complete Path A/B/C deploy journeys and validation. |

## Platform

| Guide | Purpose |
| --- | --- |
| [`platform/CAPABILITY_PROFILES.md`](platform/CAPABILITY_PROFILES.md) | Feature bundles (`CapabilityProfiles` / `CAPABILITY_PROFILES`). |

## Analyst Portal

| Guide | Purpose |
| --- | --- |
| [`analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](analyst_portal/ANALYST_PORTAL_OPERATIONS.md) | Architecture, auth, readiness, day-two ops. |
| [`analyst_portal/ANALYST_PORTAL_THEME.md`](analyst_portal/ANALYST_PORTAL_THEME.md) | Federal SOC Dark theme reference. |

## LLM Inference

| Guide | Purpose |
| --- | --- |
| [`llm/LLM_INFERENCE_OPERATIONS.md`](llm/LLM_INFERENCE_OPERATIONS.md) | Azure OpenAI routing, timeouts, structured output. |

## RAG and Azure AI Search

| Guide | Purpose |
| --- | --- |
| [`rag/KNOWLEDGE_BASE_OPERATIONS.md`](rag/KNOWLEDGE_BASE_OPERATIONS.md) | Index contract, corpus source, and lifecycle. |
| [`rag/AZURE_AI_SEARCH_RAG_INGESTION.md`](rag/AZURE_AI_SEARCH_RAG_INGESTION.md) | Ingestion queue path and manifest publishing. |

## Investigation

| Guide | Purpose |
| --- | --- |
| [`investigation/SPLUNK_ELASTICSEARCH_WRITEBACK.md`](investigation/SPLUNK_ELASTICSEARCH_WRITEBACK.md) | Splunk and Elasticsearch investigation and writeback. |

## Integrations

| Guide | Purpose |
| --- | --- |
| [`integrations/SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md`](integrations/SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md) | Read-only disposition sync timer. |
| [`integrations/SIEM_SOAR_PRIVATE_INTAKE_OPERATIONS.md`](integrations/SIEM_SOAR_PRIVATE_INTAKE_OPERATIONS.md) | Vendor-neutral private intake. |
| [`integrations/SERVICENOW_WRITEBACK_OPERATIONS.md`](integrations/SERVICENOW_WRITEBACK_OPERATIONS.md) | ServiceNow draft/create boundaries. |

## Security

| Guide | Purpose |
| --- | --- |
| [`security/AZURE_GOVERNMENT_SECURITY.md`](security/AZURE_GOVERNMENT_SECURITY.md) | Government cloud security posture. |
| [`security/MITRE_ATTACK_OPERATIONS.md`](security/MITRE_ATTACK_OPERATIONS.md) | Bundled TTP IDs and refresh workflow. |

## Retention and Recovery

| Guide | Purpose |
| --- | --- |
| [`retention/AZURE_RETENTION_AND_RECOVERY.md`](retention/AZURE_RETENTION_AND_RECOVERY.md) | Retention defaults, backup choices, recovery. |

## Monitoring and Resilience

| Guide | Purpose |
| --- | --- |
| [`AZURE_MONITORING_AND_RECOVERY.md`](AZURE_MONITORING_AND_RECOVERY.md) | Monitoring, poison replay, escalation. |
| [`AZURE_RESILIENCE_PROFILE.md`](AZURE_RESILIENCE_PROFILE.md) | Storage, Functions, and Cosmos resilience. |
| [`LOCAL_AZURE_PARITY.md`](LOCAL_AZURE_PARITY.md) | Account-free local parity lab. |

## Testing

| Guide | Purpose |
| --- | --- |
| [`testing/AZURE_GOVERNMENT_TESTING.md`](testing/AZURE_GOVERNMENT_TESTING.md) | Unit, local parity, and Government staging commands. |
| [`testing/GOLDEN_EVALUATION.md`](testing/GOLDEN_EVALUATION.md) | Verdict, evidence boundary, and report quality. |

The three poison paths are independent and never auto-replayed. Operators must
correct the cause, check for an already durable outcome, and replay one message
through its normal idempotent path.
