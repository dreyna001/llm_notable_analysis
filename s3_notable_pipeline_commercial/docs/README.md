# Documentation index

**Deployers:** start at the root [`README.md`](../README.md).

1. Section **2** — universal prerequisites (tools, account, mutation gate)
2. Section **3** — before you choose a path (ownership, customer checklist; Path B file prep in **3.4**)
3. Section **4** — pick Path A/B/C and follow each linked runbook in order through [`testing/TESTING.md`](testing/TESTING.md)

## Operations index

**[Operations guide index](operations/README.md)** — all tuning guides by category
(deployment, platform, portal, LLM, RAG, investigation, integrations, security).

## Topic shortcuts

| Topic | Primary doc |
|-------|-------------|
| Deploy journey (Path A/B/C) | [`../README.md`](../README.md) sections 2–4 |
| Image build + SAM parameters | [DEPLOYMENT_IMAGE_STEPS.md](operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) |
| Customer-default preset | [COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md](operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md), [`../deploy/aws/presets/`](../deploy/aws/presets/) |
| VPC / network before RAG/portal | [VPC_NETWORK_PREREQUISITES.md](operations/deployment/VPC_NETWORK_PREREQUISITES.md) |
| OpenSearch before RAG/portal | [OPENSEARCH_PROVISIONING.md](operations/deployment/OPENSEARCH_PROVISIONING.md) |
| Bedrock model enablement | [BEDROCK_ACCOUNT_ENABLEMENT.md](operations/deployment/BEDROCK_ACCOUNT_ENABLEMENT.md) |
| Customer KMS key policies | [KMS_CUSTOMER_KEY.md](operations/deployment/KMS_CUSTOMER_KEY.md) |
| Portal JWT / IdP | [PORTAL_JWT_IDENTITY.md](operations/deployment/PORTAL_JWT_IDENTITY.md) |
| Customer ownership vs product scope | [CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md](operations/deployment/CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md) |
| Customer configuration inputs | [COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md](operations/deployment/COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md) |
| Capability profiles | [CAPABILITY_PROFILES.md](operations/platform/CAPABILITY_PROFILES.md), [`../config.env.example`](../config.env.example) |
| Analyst portal | [ANALYST_PORTAL_OPERATIONS.md](operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md) |
| RAG corpus + retrieval | [KNOWLEDGE_BASE_OPERATIONS.md](operations/rag/KNOWLEDGE_BASE_OPERATIONS.md), [RAG_OPERATIONS.md](operations/rag/RAG_OPERATIONS.md) |
| LLM inference (Bedrock) | [LLM_INFERENCE_OPERATIONS.md](operations/llm/LLM_INFERENCE_OPERATIONS.md) |
| SPL / Elastic investigation | [SPL_OPERATIONS.md](operations/investigation/SPL_OPERATIONS.md), [ELASTICSEARCH_OPERATIONS.md](operations/investigation/ELASTICSEARCH_OPERATIONS.md) |
| Splunk writeback / ServiceNow | [SPLUNK_WRITEBACK_OPERATIONS.md](operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md), [SERVICENOW_OPERATIONS.md](operations/integrations/SERVICENOW_OPERATIONS.md) |
| Testing | [TESTING.md](testing/TESTING.md) |
| Security | [SECURITY_OPERATIONS.md](operations/security/SECURITY_OPERATIONS.md), [ATTACK_LLM_ANALYSIS.md](security/ATTACK_LLM_ANALYSIS.md) |
| AWS/on-prem parity contract | [AWS_ONPREM_PARITY_TECHNICAL_SPEC.md](technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md) |
| Monthly AWS cost estimate | [AWS_MONTHLY_COST_ESTIMATE.md](technical_specs/AWS_MONTHLY_COST_ESTIMATE.md) |
| On-prem profile semantics | [`../../llm_notable_analysis_onprem_systemd/docs/operations/platform/CAPABILITY_PROFILES.md`](../../llm_notable_analysis_onprem_systemd/docs/operations/platform/CAPABILITY_PROFILES.md) |

## Context (optional, before deploy)

1. **[Executive AWS workflow](delivery_package/EXECUTIVE_AWS_WORKFLOW.md)** — stakeholder summary
2. **[End-to-end diagrams](delivery_package/end_to_end_diagrams/END_TO_END_DIAGRAMS.md)** — architecture visuals
3. **[Deployment readiness overview](delivery_package/AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_OVERVIEW.md)** and **[readiness checklist](delivery_package/AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_ASSESSMENT.md)** — production gate

## Optional deep dives

- **[Commercial AWS fork plan](planning/COMMERCIAL_AWS_FORK_PLAN.md)** — implementation sequence and safety boundaries
- **[AWS commercial readiness plan](planning/AWS_COMMERCIAL_READINESS_PLAN.md)** — validation plan for `us-east-1`
- **[Commercial approved differences](internal/COMMERCIAL_AWS_APPROVED_DIFFERENCES.md)** — deliberate architecture decisions
- **[Planning todos](planning/TODOS.md)** — backlog register
- **[Portal chat capability gaps](../../PORTAL_CHATBOT_CAPABILITY_GAPS.md)** — intentional product gaps vs consumer chat UIs
- **[Azure/AWS parity plan](planning/AZURE_AWS_PARITY_PLAN.md)** — Azure mirror (planning only)

## Doc folders

| Folder | Contents |
|--------|----------|
| [`delivery_package/`](delivery_package/) | Executive workflow, readiness, diagrams |
| [`operations/`](operations/) | Customer tuning guides by area |
| [`integrations/`](integrations/) | SOAR / Phantom S3 upload pattern |
| [`technical_specs/`](technical_specs/) | Normative shipped contracts |
| [`planning/`](planning/) | Parity and readiness plans |
| [`security/`](security/) | ATT&CK and trust-boundary reference |
| [`testing/`](testing/) | Unit, smoke, and staging validation |
| [`contracts/`](contracts/) | Portal OpenAPI schema |
