# Azure Government Notable Pipeline

Azure Government-native sibling of `s3_notable_pipeline`, built to preserve
product and operator-visible behavior without reproducing AWS SDK, event, or
persistence interfaces. The deployment target is `AzureUSGovernment`, with
`usgovvirginia` as the default qualified region.

**Deployers start here.** Pick one path in section 2, follow the linked documents in
order, and finish at validation. Topic shortcuts and the documentation index live in
[`docs/README.md`](docs/README.md).

The locked private intake path is a polling Blob trigger on
`input/incoming/{name}`. Application code publishes a strict v1 job to
`notable-analysis-jobs` in the output storage account, and the analyzer queue
wrapper validates that job before orchestration. All storage public network
access remains disabled.

## 1) Prerequisites

- Azure Government subscription in `usgovvirginia` (or customer-qualified `usgovarizona`) with approved Azure OpenAI model access and quota
- Azure CLI configured for Government cloud (`az cloud set --name AzureUSGovernment`, `az login`)
- Docker running (required for container image build)
- Customer-owned ACR in Government cloud (`.azurecr.us`) with an immutable digest recorded as `CONTAINER_IMAGE_URI`
- Required deployment environment variables from [`config.env.example`](config.env.example) (subscription, resource group, storage, Cosmos, Azure OpenAI)

Quick checks:

```bash
az cloud show --query name -o tsv
az account show --query "{subscription:id, tenant:tenantId}" -o json
docker --version
az bicep version
```

**Before any live Azure mutation** (ACR push, `az deployment group create`, role
assignment, Front Door private-link approval, Key Vault secret write):

1. Confirm `az account show` subscription ID matches the approved Azure Government subscription
2. Confirm cloud `AzureUSGovernment` and region `usgovvirginia` (or qualified alternative)
3. Confirm active CLI identity, target resource group, and deployment name
4. Review intended Bicep changes (`az deployment group what-if` or equivalent)
5. Obtain explicit customer approval for that mutation

## 2) Deploy — pick one path

Read [`docs/operations/deployment/AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md`](docs/operations/deployment/AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md) first on any path — defines customer decisions, Government endpoint families, and evidence required outside this repository.

| Path | When to use |
| --- | --- |
| **A — Core only** | First deployment, analysis only, no RAG or portal |
| **B — Customer-default** | On-prem `core,rag,analyst_portal` parity on Azure Government |
| **C — Custom profiles** | Specific bundles such as `spl_readonly` or `action_gated` |

Each runbook ends with a **Next** line for path navigation. Stay on one path until you reach [`docs/operations/testing/AZURE_GOVERNMENT_TESTING.md`](docs/operations/testing/AZURE_GOVERNMENT_TESTING.md).

### Path A — Core only

Follow in order:

1. [`docs/operations/deployment/AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md`](docs/operations/deployment/AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md) — subscription, region, naming, and private networking decisions
2. [`docs/operations/llm/LLM_INFERENCE_OPERATIONS.md`](docs/operations/llm/LLM_INFERENCE_OPERATIONS.md) — record customer approval for Azure OpenAI analysis deployments
3. [`docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md`](docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) — build, push, and record immutable `CONTAINER_IMAGE_URI` before Bicep
4. **Deploy** with `CapabilityProfiles=core` using `setup-and-deploy.*` (commands below)
5. [`docs/operations/testing/AZURE_GOVERNMENT_TESTING.md`](docs/operations/testing/AZURE_GOVERNMENT_TESTING.md) — unit tests and core staging validation

Deploy commands:

```powershell
$env:AZURE_CLOUD_ENVIRONMENT = "AzureUSGovernment"
$env:AZURE_LOCATION = "usgovvirginia"
$env:CAPABILITY_PROFILES = "core"
# set remaining required vars from config.env.example
.\scripts\setup-and-deploy.ps1
```

```bash
export AZURE_CLOUD_ENVIRONMENT=AzureUSGovernment
export AZURE_LOCATION=usgovvirginia
export CAPABILITY_PROFILES=core
# set remaining required vars from config.env.example
chmod +x ./scripts/setup-and-deploy.sh
./scripts/setup-and-deploy.sh
```

The setup scripts run prerequisite checks, Bicep compile, and `az deployment group create`.
They do not build or push the container image. Build and push first per
[`DEPLOYMENT_IMAGE_STEPS.md`](docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md),
then pass `CONTAINER_IMAGE_URI` and `CONTAINER_REGISTRY_RESOURCE_ID` via environment.

Infrastructure template: [`deploy/azure/main.bicep`](deploy/azure/main.bicep).
Runtime env reference: [`config.env.example`](config.env.example).

### Path B — Customer-default

Bundle: `core,rag,analyst_portal`. Follow in order — do not skip Search, JWT, or image
steps ahead of Bicep deploy.

1. [`docs/operations/deployment/AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md`](docs/operations/deployment/AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md) — subscription, region, naming, and private networking
2. [`docs/operations/llm/LLM_INFERENCE_OPERATIONS.md`](docs/operations/llm/LLM_INFERENCE_OPERATIONS.md) — enable analysis, embeddings, and portal chat deployments
3. [`docs/operations/rag/KNOWLEDGE_BASE_OPERATIONS.md`](docs/operations/rag/KNOWLEDGE_BASE_OPERATIONS.md) — customer-provisioned Azure AI Search indexes and vector contract
4. [`docs/operations/ANALYST_PORTAL_DEPLOYMENT.md`](docs/operations/ANALYST_PORTAL_DEPLOYMENT.md) — portal JWT, Entra, Front Door private-link gate before deploy
5. [`docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md`](docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) — build, push, and record `CONTAINER_IMAGE_URI` before Bicep
6. [`docs/operations/deployment/AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md`](docs/operations/deployment/AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md) and [`deploy/azure/presets/`](deploy/azure/presets/) — copy preset, fill env, and deploy
7. [`docs/operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](docs/operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md) — build and upload the analyst portal SPA
8. [`docs/operations/rag/AZURE_AI_SEARCH_RAG_INGESTION.md`](docs/operations/rag/AZURE_AI_SEARCH_RAG_INGESTION.md) — ingest SOC and Splunk dictionary corpora
9. [`docs/operations/testing/AZURE_GOVERNMENT_TESTING.md`](docs/operations/testing/AZURE_GOVERNMENT_TESTING.md) — Wave 1 and portal staging validation

### Path C — Custom profiles

1. [`docs/operations/platform/CAPABILITY_PROFILES.md`](docs/operations/platform/CAPABILITY_PROFILES.md) — select profile bundles and note mutual exclusions
2. [`docs/operations/deployment/AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md`](docs/operations/deployment/AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md) — customer decisions for enabled profiles
3. If analysis or embeddings: [`docs/operations/llm/LLM_INFERENCE_OPERATIONS.md`](docs/operations/llm/LLM_INFERENCE_OPERATIONS.md)
4. If `rag` or case Q&A: [`docs/operations/rag/KNOWLEDGE_BASE_OPERATIONS.md`](docs/operations/rag/KNOWLEDGE_BASE_OPERATIONS.md)
5. If `analyst_portal`: [`docs/operations/ANALYST_PORTAL_DEPLOYMENT.md`](docs/operations/ANALYST_PORTAL_DEPLOYMENT.md)
6. [`docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md`](docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) — build ACR image, then Bicep deploy with profile-specific parameters
7. **Deploy** with chosen `CAPABILITY_PROFILES` using `setup-and-deploy.*` and [`config.env.example`](config.env.example)
8. Profile ops guides from [`docs/operations/README.md`](docs/operations/README.md) — day-two tuning for enabled profiles
9. [`docs/operations/testing/AZURE_GOVERNMENT_TESTING.md`](docs/operations/testing/AZURE_GOVERNMENT_TESTING.md) — staging matrix for your profile slice

Customer values checklist: [`docs/operations/deployment/AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md`](docs/operations/deployment/AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md).

## 3) Validate (all paths end here)

Path-specific checklists live in [`docs/operations/testing/AZURE_GOVERNMENT_TESTING.md`](docs/operations/testing/AZURE_GOVERNMENT_TESTING.md).

Unit tests (no live Azure calls):

```bash
python -m pytest tests -m 'not integration' -q
az bicep build --file deploy/azure/main.bicep
```

Government staging gate (isolated non-production subscription; set `STAGING_SUBSCRIPTION_ID`,
`STAGING_CHAOS_CONFIRMATION=isolated-nonproduction`, and related vars first):

```bash
export AZURE_RESOURCE_GROUP=<staging-resource-group>
export AZURE_DEPLOYMENT_NAME=<deployment-name>
export STAGING_SUBSCRIPTION_ID=<dedicated-staging-subscription-id>
export STAGING_CHAOS_CONFIRMATION=isolated-nonproduction
./scripts/test-pipeline.sh --staging-gate
```

PowerShell equivalent: [`scripts/test-pipeline.ps1`](scripts/test-pipeline.ps1).

Account-free integration coverage: [`docs/operations/LOCAL_AZURE_PARITY.md`](docs/operations/LOCAL_AZURE_PARITY.md)
with [`deploy/local/bootstrap.sh`](deploy/local/bootstrap.sh) or
[`deploy/local/bootstrap.ps1`](deploy/local/bootstrap.ps1). Emulators validate application
contracts only; production acceptance requires Government staging.

## 4) Rollback and teardown

**Rollback (failed release, not teardown):** redeploy a previous immutable
`CONTAINER_IMAGE_URI` digest with the same configuration — see
[`docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md`](docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md)
(Rollback).

**Teardown (destructive - approval required):** resource-group deletion, storage
emptying, and Cosmos account removal are **irreversible** and are not rollback.
After explicit customer approval, use the resource inventory and retention guidance in
[`docs/operations/deployment/AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md`](docs/operations/deployment/AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md)
and [`docs/operations/retention/AZURE_RETENTION_AND_RECOVERY.md`](docs/operations/retention/AZURE_RETENTION_AND_RECOVERY.md)
with customer-approved procedures. No automated bulk deletion workflow is provided.

## 5) Further reading

| Topic | Doc |
| --- | --- |
| Capability profiles and Bicep parameters | [`docs/operations/platform/CAPABILITY_PROFILES.md`](docs/operations/platform/CAPABILITY_PROFILES.md) |
| Functions runtime env contract | [`config.env.example`](config.env.example) |
| Splunk/Elastic writeback and investigation | [`docs/operations/investigation/SPLUNK_ELASTICSEARCH_WRITEBACK.md`](docs/operations/investigation/SPLUNK_ELASTICSEARCH_WRITEBACK.md) |
| Operations guides by area | [`docs/operations/README.md`](docs/operations/README.md) |
| Documentation index and topic shortcuts | [`docs/README.md`](docs/README.md) |
| Production readiness checklist | [`docs/delivery_package/AZURE_READINESS.md`](docs/delivery_package/AZURE_READINESS.md) |
| Implementation status | [`docs/planning/AZURE_IMPLEMENTATION_TRACKER.md`](docs/planning/AZURE_IMPLEMENTATION_TRACKER.md) |
