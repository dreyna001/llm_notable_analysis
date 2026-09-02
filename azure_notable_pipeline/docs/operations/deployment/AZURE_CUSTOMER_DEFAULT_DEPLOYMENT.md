# Azure Government customer-default deployment

One-shot Bicep preset for the on-prem **customer-default** bundle on Azure
Government (`AzureUSGovernment`, `usgovvirginia` default):

- `CapabilityProfiles=core,rag,analyst_portal`
- General SOC RAG + pinned-case Q&A through Azure AI Search
- Case archive, CaseIndex, read-only portal API
- **No** first-pass SPL generation or live SIEM queries
- **No** closed-ticket RAG by default (enable P1-P8 Bicep parameters when ready)

On-prem normative reference:
[`../../../../llm_notable_analysis_onprem_systemd/docs/operations/deployment/CUSTOMER_DEFAULT_DEPLOYMENT.md`](../../../../llm_notable_analysis_onprem_systemd/docs/operations/deployment/CUSTOMER_DEFAULT_DEPLOYMENT.md)

**Path B step 7** (Bicep deploy):
[`../../../README.md`](../../../README.md#path-b-customer-default).

## Preset files (copy and fill)

| File | Purpose |
| --- | --- |
| [`../../../deploy/azure/presets/customer-default.env.example`](../../../deploy/azure/presets/customer-default.env.example) | Placeholder env file; source before `./scripts/setup-and-deploy.sh` |

Image build and ACR push still follow
[`DEPLOYMENT_IMAGE_STEPS.md`](DEPLOYMENT_IMAGE_STEPS.md) before deploy.

## Step 0: Customer prerequisites (required for this preset)

Complete these runbooks **before** `az deployment group create` (Path B order:
[`../../../README.md`](../../../README.md#path-b-customer-default)):

| Order | Runbook | Purpose |
| --- | --- | --- |
| 1 | [`AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md`](AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md) | Subscription, region, naming, private networking |
| 2 | Customer Azure AI Search runbook (same guide) | Customer-provisioned Search service and indexes |
| 3 | Customer Azure OpenAI enablement | Analysis, embeddings, and portal chat deployments |
| 4 | Portal JWT / Entra configuration | Issuer, audience, analyst grant |

Copy into `customer-default.env` from
[`AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md`](AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md)
and the Bicep parameter comments. Search indexes for RAG and case Q&A are
customer-provisioned with the 1024-dimension vector contract.

## Why both profiles and explicit Bicep flags

`CapabilityProfiles` drives runtime behavior in the Function image. Bicep also
uses explicit `*_Enabled` parameters to create Cosmos containers, app settings,
timer isolation, and RBAC. For customer-default, set **both** to the same intent:

| Bicep parameter | Customer-default value |
| --- | --- |
| `CapabilityProfiles` | `core,rag,analyst_portal` |
| `ServiceNowDispositionSyncEnabled` | `false` |
| `ServiceNowClosedTicketSyncEnabled` | `false` |
| `ClosedTicketRagEnabled` | `false` |
| `ImageIngestEnabled` | `false` |
| `RagRerankEnabled` | `false` |
| `CaseQaClosedTicketEnabled` | `false` |
| `CaseQaChatImagesEnabled` | `false` |
| `CaseQaChatHistoryEnabled` | `false` (enable after chat containers are provisioned) |

Full customer values checklist:
[`AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md`](AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md).

## Deploy (fast path)

```bash
cp deploy/azure/presets/customer-default.env.example customer-default.env
# edit customer-default.env

set -a && source customer-default.env && set +a
./scripts/setup-and-deploy.sh
```

The deploy script runs tests, compiles Bicep, builds the container image, asks
Azure Resource Manager to validate the exact template and parameters, deploys,
and then runs identity, private-network, Function-host, monitoring, and portal
checks. It writes a sanitized JSON result to
`deployment-results/<deployment-name>.json`; set `DEPLOYMENT_REPORT_PATH` to
choose another location. The report is created only after all automated checks
pass and contains no bearer tokens, keys, or connection strings.

Archive that report in the customer's approved evidence system. It records the
deployment name, cloud, region, immutable image, capability profiles, safe
Bicep outputs, and the checks completed by the script. It does not replace the
live staging acceptance record described below.

## Post-deploy (required for full customer-default)

1. **Portal SPA** -- build `frontend/analyst-portal`, upload `dist/` to the
   portal UI storage account. See
   [`../analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../analyst_portal/ANALYST_PORTAL_OPERATIONS.md).
2. **SOC KB ingest** -- load approved general SOC corpus to RAG source storage,
   publish manifest through the analyzer `rag_ingest_queue` path.
3. **Smoke** -- run Wave 1 + portal staging checks in
   [`../testing/AZURE_GOVERNMENT_TESTING.md`](../testing/AZURE_GOVERNMENT_TESTING.md).

Before changing an existing environment, follow
[`AZURE_UPGRADE_AND_ROLLBACK.md`](AZURE_UPGRADE_AND_ROLLBACK.md). Keep the last
qualified image digest and portal artifact until the new release passes the
live staging gate.

## Intentional gaps vs on-prem customer-default

| On-prem setting | Azure Government customer-default preset |
| --- | --- |
| `SPL_QUERY_GENERATION_ENABLED=true` (no live Splunk) | **Off** -- no `spl_readonly` profile |
| `CLOSED_TICKET_RAG_ENABLED` / ServiceNow closed-ticket sync | **Off** -- enable via P3-P8 Bicep parameters |
| Postgres + Granite embed/rerank | Azure AI Search + Azure OpenAI embeddings |
| nginx Basic Auth front door | Front Door + JWT or Entra portal auth |

Track remaining parity work in
[`../../planning/TODOS.md`](../../planning/TODOS.md).

## Next

- **Path B steps (post-deploy):** [`../../../README.md`](../../../README.md#path-b-customer-default) (portal SPA, KB ingest, smoke)
- **Path C:** optional profile rollout — [`../../../README.md`](../../../README.md#path-c-custom-profiles)
