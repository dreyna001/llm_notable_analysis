# Documentation index

**Start here** after skimming the root [`README.md`](../README.md). This page is
the navigation hub for commercial AWS (`aws`, `us-east-1`).

## Choose your deploy path

Pick one trail and follow it in order. Do not skip Step 0 when the path lists it.

| Path | When to use | Follow in order |
| --- | --- | --- |
| **A — Core only** | First stack, analysis only, no RAG or portal | [1. Image + SAM](#path-a--core-only-first-stack) below |
| **B — Customer-default** | On-prem `core,rag,analyst_portal` parity on commercial AWS | [1. OpenSearch](#path-b--customer-default) -> [2. Preset SAM](#path-b--customer-default) -> [3. Post-deploy](#path-b--customer-default) |
| **C — Custom profiles** | Specific bundles (`spl_readonly`, `action_gated`, etc.) | [Capability profiles](operations/platform/CAPABILITY_PROFILES.md) -> prerequisites for each profile -> [DEPLOYMENT_IMAGE_STEPS.md](operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) |

Shared prerequisites for every path:

- Commercial account in `us-east-1`, ECR image published by digest
- [`BEDROCK_ACCOUNT_ENABLEMENT.md`](operations/deployment/BEDROCK_ACCOUNT_ENABLEMENT.md) — model access before SAM
- [`DEPLOYMENT_IMAGE_STEPS.md`](operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) (build/push before SAM)
- [`COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md`](operations/deployment/COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md) (customer values checklist)
- [`CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md`](operations/deployment/CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md) (what you own vs what the stack creates)
- Optional production: [`KMS_CUSTOMER_KEY.md`](operations/deployment/KMS_CUSTOMER_KEY.md)

### Path A — Core only (first stack)

1. [`DEPLOYMENT_IMAGE_STEPS.md`](operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) — ECR build, push, `CapabilityProfiles=core`
2. [`../README.md`](../README.md) sections 2-3 — `setup-and-deploy.*`, smoke test
3. [`TESTING.md`](testing/TESTING.md) — unit tests and optional Wave 1 checks

### Path B — Customer-default

1. [`VPC_NETWORK_PREREQUISITES.md`](operations/deployment/VPC_NETWORK_PREREQUISITES.md) — private subnets, NAT or VPC endpoints, Lambda security groups
2. [`OPENSEARCH_PROVISIONING.md`](operations/deployment/OPENSEARCH_PROVISIONING.md) — OpenSearch domain (stack does not create it)
3. [`KMS_CUSTOMER_KEY.md`](operations/deployment/KMS_CUSTOMER_KEY.md) — optional CMK before or after first deploy
4. [`BEDROCK_ACCOUNT_ENABLEMENT.md`](operations/deployment/BEDROCK_ACCOUNT_ENABLEMENT.md) — analysis + embedding model IDs/ARNs
5. [`PORTAL_JWT_IDENTITY.md`](operations/deployment/PORTAL_JWT_IDENTITY.md) — IdP issuer, audience, analyst grant, CORS
6. [`DEPLOYMENT_IMAGE_STEPS.md`](operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) — ECR image (same as Path A)
7. [`COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`](operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md) — copy [`../deploy/aws/presets/`](../deploy/aws/presets/), fill env, `sam deploy`
8. [`KNOWLEDGE_BASE_OPERATIONS.md`](operations/rag/KNOWLEDGE_BASE_OPERATIONS.md) — SOC + Splunk dictionary ingest
9. [`ANALYST_PORTAL_OPERATIONS.md`](operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md) — portal SPA upload, day-two ops
10. [`TESTING.md`](testing/TESTING.md) — OpenSearch preflight + customer-default staging row

### Path C — Custom profiles

1. [`CAPABILITY_PROFILES.md`](operations/platform/CAPABILITY_PROFILES.md) — select bundles; note mutual exclusions
2. If `rag`, `SplQueryRagEnabled`, or portal case Q&A: [`VPC_NETWORK_PREREQUISITES.md`](operations/deployment/VPC_NETWORK_PREREQUISITES.md) then [`OPENSEARCH_PROVISIONING.md`](operations/deployment/OPENSEARCH_PROVISIONING.md)
3. If `analyst_portal`: [`PORTAL_JWT_IDENTITY.md`](operations/deployment/PORTAL_JWT_IDENTITY.md) before portal cutover
4. [`DEPLOYMENT_IMAGE_STEPS.md`](operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) — ECR + SAM with profile-specific parameters
5. Profile ops guides (portal, RAG, investigation, integrations) linked from [`operations/README.md`](operations/README.md)
6. [`TESTING.md`](testing/TESTING.md) — Wave 1 / Wave 2 staging tables for your profile slice

## Context (optional, before deploy)

1. **[Executive AWS workflow](delivery_package/EXECUTIVE_AWS_WORKFLOW.md)** — stakeholder summary
2. **[End-to-end diagrams](delivery_package/end_to_end_diagrams/END_TO_END_DIAGRAMS.md)** — architecture visuals
3. **[Deployment readiness overview](delivery_package/AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_OVERVIEW.md)** and **[readiness checklist](delivery_package/AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_ASSESSMENT.md)** — production gate

## Operations index

**[Operations guide index](operations/README.md)** — all tuning guides by category
(deployment, platform, portal, LLM, RAG, investigation, integrations, security).

## Topic shortcuts

| Topic | Primary doc |
|-------|-------------|
| Deploy path hub (this page) | [`docs/README.md`](README.md) |
| Core SAM deploy | [DEPLOYMENT_IMAGE_STEPS.md](operations/deployment/DEPLOYMENT_IMAGE_STEPS.md), [`../README.md`](../README.md) |
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
| On-prem profile semantics | [`../../llm_notable_analysis_onprem_systemd/docs/operations/platform/CAPABILITY_PROFILES.md`](../../llm_notable_analysis_onprem_systemd/docs/operations/platform/CAPABILITY_PROFILES.md) |

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
