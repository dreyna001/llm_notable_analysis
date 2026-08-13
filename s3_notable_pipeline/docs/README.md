# Documentation index

**Start here** after skimming the root [`README.md`](../README.md). This page is
the navigation hub for AWS GovCloud (`aws-us-gov`, `us-gov-east-1`).

## Choose your deploy path

Pick one trail and follow it in order. Do not skip Step 0 when the path lists it.

| Path | When to use | Follow in order |
| --- | --- | --- |
| **A — Core only** | First stack, analysis only, no RAG or portal | [Path A steps](#path-a--core-only-first-stack) below |
| **B — RAG + portal bundle** | `core,rag,analyst_portal` (manual SAM parameters; no preset doc) | [Path B steps](#path-b--rag--portal) below |
| **C — Custom profiles** | Specific bundles (`spl_readonly`, `action_gated`, etc.) | [Capability profiles](operations/platform/CAPABILITY_PROFILES.md) -> prerequisites -> [DEPLOYMENT_IMAGE_STEPS.md](operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) |

Shared prerequisites for every path:

- GovCloud account in `us-gov-east-1`, ECR image published by digest
- [`BEDROCK_ACCOUNT_ENABLEMENT.md`](operations/deployment/BEDROCK_ACCOUNT_ENABLEMENT.md) — model access before SAM
- [`DEPLOYMENT_IMAGE_STEPS.md`](operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) (build/push before SAM)
- [`GOVCLOUD_CUSTOMER_CONFIGURATION.md`](operations/deployment/GOVCLOUD_CUSTOMER_CONFIGURATION.md) (customer values checklist)
- [`CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md`](operations/deployment/CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md) (what you own vs what the stack creates)
- Optional production: [`KMS_CUSTOMER_KEY.md`](operations/deployment/KMS_CUSTOMER_KEY.md)

### Path A — Core only (first stack)

1. [`DEPLOYMENT_IMAGE_STEPS.md`](operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) — ECR build, push, `CapabilityProfiles=core`
2. [`../README.md`](../README.md) sections 2-3 — `setup-and-deploy.*`, smoke test
3. [`TESTING.md`](testing/TESTING.md) — unit tests and optional Wave 1 checks

### Path B — RAG + portal

1. [`VPC_NETWORK_PREREQUISITES.md`](operations/deployment/VPC_NETWORK_PREREQUISITES.md) — private subnets, NAT or VPC endpoints, Lambda security groups
2. [`OPENSEARCH_PROVISIONING.md`](operations/deployment/OPENSEARCH_PROVISIONING.md) — OpenSearch domain (stack does not create it)
3. [`KMS_CUSTOMER_KEY.md`](operations/deployment/KMS_CUSTOMER_KEY.md) — optional CMK
4. [`BEDROCK_ACCOUNT_ENABLEMENT.md`](operations/deployment/BEDROCK_ACCOUNT_ENABLEMENT.md) — analysis + embedding model IDs/ARNs
5. [`PORTAL_JWT_IDENTITY.md`](operations/deployment/PORTAL_JWT_IDENTITY.md) — IdP issuer, audience, analyst grant, CORS
6. [`DEPLOYMENT_IMAGE_STEPS.md`](operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) — ECR image (same as Path A)
7. [`CAPABILITY_PROFILES.md`](operations/platform/CAPABILITY_PROFILES.md) — set `CapabilityProfiles=core,rag,analyst_portal` and matching `*_Enabled` SAM flags
8. [`KNOWLEDGE_BASE_OPERATIONS.md`](operations/rag/KNOWLEDGE_BASE_OPERATIONS.md) — SOC + Splunk dictionary ingest
9. [`ANALYST_PORTAL_OPERATIONS.md`](operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md) — portal SPA upload, day-two ops
10. [`TESTING.md`](testing/TESTING.md) — OpenSearch preflight + Wave 1/2 staging tables

Commercial AWS has a copy-and-fill preset for the same bundle:
[`../../s3_notable_pipeline_commercial/docs/operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`](../../s3_notable_pipeline_commercial/docs/operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md)
(partition `aws` only; do not deploy that tree into GovCloud).

### Path C — Custom profiles

1. [`CAPABILITY_PROFILES.md`](operations/platform/CAPABILITY_PROFILES.md) — select bundles; note mutual exclusions
2. If `rag`, `SplQueryRagEnabled`, or portal case Q&A: [`VPC_NETWORK_PREREQUISITES.md`](operations/deployment/VPC_NETWORK_PREREQUISITES.md) then [`OPENSEARCH_PROVISIONING.md`](operations/deployment/OPENSEARCH_PROVISIONING.md)
3. If `analyst_portal`: [`PORTAL_JWT_IDENTITY.md`](operations/deployment/PORTAL_JWT_IDENTITY.md) before portal cutover
4. [`DEPLOYMENT_IMAGE_STEPS.md`](operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) — ECR + SAM with profile-specific parameters
5. Profile ops guides linked from [`operations/README.md`](operations/README.md)
6. [`TESTING.md`](testing/TESTING.md) — Wave 1 / Wave 2 staging for your profile slice

## Context (optional, before deploy)

1. **[Executive AWS workflow](delivery_package/EXECUTIVE_AWS_WORKFLOW.md)** — stakeholder summary
2. **[End-to-end diagrams](delivery_package/end_to_end_diagrams/END_TO_END_DIAGRAMS.md)** — architecture visuals
3. **[Deployment readiness overview](delivery_package/AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_OVERVIEW.md)** and **[readiness checklist](delivery_package/AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_ASSESSMENT.md)** — production gate

## Operations index

**[Operations guide index](operations/README.md)** — all tuning guides by category.

## Topic shortcuts

| Topic | Primary doc |
|-------|-------------|
| Deploy path hub (this page) | [`docs/README.md`](README.md) |
| Core SAM deploy | [DEPLOYMENT_IMAGE_STEPS.md](operations/deployment/DEPLOYMENT_IMAGE_STEPS.md), [`../README.md`](../README.md) |
| VPC / network before RAG/portal | [VPC_NETWORK_PREREQUISITES.md](operations/deployment/VPC_NETWORK_PREREQUISITES.md) |
| OpenSearch before RAG/portal | [OPENSEARCH_PROVISIONING.md](operations/deployment/OPENSEARCH_PROVISIONING.md) |
| Bedrock model enablement | [BEDROCK_ACCOUNT_ENABLEMENT.md](operations/deployment/BEDROCK_ACCOUNT_ENABLEMENT.md) |
| Customer KMS key policies | [KMS_CUSTOMER_KEY.md](operations/deployment/KMS_CUSTOMER_KEY.md) |
| Portal JWT / IdP | [PORTAL_JWT_IDENTITY.md](operations/deployment/PORTAL_JWT_IDENTITY.md) |
| Customer ownership vs product scope | [CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md](operations/deployment/CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md) |
| Customer configuration inputs | [GOVCLOUD_CUSTOMER_CONFIGURATION.md](operations/deployment/GOVCLOUD_CUSTOMER_CONFIGURATION.md) |
| Capability profiles | [CAPABILITY_PROFILES.md](operations/platform/CAPABILITY_PROFILES.md), [`../config.env.example`](../config.env.example) |
| Analyst portal | [ANALYST_PORTAL_OPERATIONS.md](operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md) |
| RAG corpus + retrieval | [KNOWLEDGE_BASE_OPERATIONS.md](operations/rag/KNOWLEDGE_BASE_OPERATIONS.md), [RAG_OPERATIONS.md](operations/rag/RAG_OPERATIONS.md) |
| LLM inference (Bedrock) | [LLM_INFERENCE_OPERATIONS.md](operations/llm/LLM_INFERENCE_OPERATIONS.md) |
| Testing | [TESTING.md](testing/TESTING.md) |
| Security | [SECURITY_OPERATIONS.md](operations/security/SECURITY_OPERATIONS.md), [ATTACK_LLM_ANALYSIS.md](security/ATTACK_LLM_ANALYSIS.md) |
| AWS/on-prem parity contract | [AWS_ONPREM_PARITY_TECHNICAL_SPEC.md](technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md) |

## Optional deep dives

- **[AWS/on-prem parity technical spec](technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md)** — normative shipped contract
- **[AWS GovCloud readiness plan](planning/AWS_GOVCLOUD_READINESS_PLAN.md)** — validation plan for `us-gov-east-1`
- **[Portal chat capability gaps](../../PORTAL_CHATBOT_CAPABILITY_GAPS.md)** — intentional product gaps
- **[Planning todos](planning/TODOS.md)** — backlog register
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
