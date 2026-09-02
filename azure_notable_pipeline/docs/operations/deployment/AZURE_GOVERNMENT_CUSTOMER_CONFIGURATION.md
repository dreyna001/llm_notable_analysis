# Azure Government customer configuration

Customer decisions and acceptance evidence for Azure Government deployment.
Keep tenant IDs, resource IDs, endpoints, quotas, secrets, and approval records
in the customer's approved deployment system — not in this repository.

Deploy path order: [`../../../README.md`](../../../README.md).

## Operating rule

This guide defines the values a customer must decide and the evidence required
to enable them. It is not a place to record live values. Keep tenant IDs,
resource IDs, object IDs, private DNS names, endpoints, quotas, secrets, and
approval records in the customer's approved deployment system.

The target cloud is `AzureUSGovernment`; the default region is
`usgovvirginia`. Customer qualification must confirm the selected Azure OpenAI
models, Azure AI Search vector features, private networking, quota, and
availability in that region. Azure Government uses Government endpoint families,
including `openai.azure.us`, `search.azure.us`, `azurewebsites.us`, and storage
endpoints under `core.usgovcloudapi.net`; derive exact resource URLs from the
customer deployment rather than hardcoding them.

## Required customer decisions

| Decision | Record outside this repository | Acceptance evidence |
| --- | --- | --- |
| Subscription and region | Subscription, tenant, resource group, naming prefix, `usgovvirginia` or qualified alternative | Azure CLI/portal context and approved architecture record |
| Resource endpoints | Blob, Queue, Cosmos, Key Vault, ACR, Search, Azure OpenAI, Function, Front Door | Government suffix validation and private DNS resolution |
| Identities | Function UAMI object IDs, deployer identity, synthetic monitor identity, SOAR identity | RBAC export with least-privilege scopes |
| AI | Azure OpenAI analyzer/chat/embedding deployment names, API version, model versions, quota, filters | Model smoke test and quota approval with synthetic data |
| Search | Index names, schema, vector dimensions, semantic rerank decision, corpus owners | Index contract and ingestion/retrieval test |
| Data | Container names, prefixes, retention, case/chat history, legal hold process | Data-owner and privacy approval |
| Network | VNet, private endpoints, private DNS zones, egress allowlist, Front Door/Function path | Direct-origin denial and private connectivity test |
| Integrations | Splunk/Elastic/ServiceNow URLs, mode, allowlists, secret names, owners | Fake contract tests and isolated live smoke where approved |
| Operations | Action group, thresholds, on-call, escalation, rollback digest, evidence store | Completed readiness record |

## Who owns what

| Customer owns | Product deployment owns |
| --- | --- |
| Azure Government subscription, tenant, region approval, quotas, and budget | Bicep definitions and validation of supported cloud/region inputs |
| Existing ACR, Azure OpenAI deployments, Search service/indexes, Key Vault, action group, DNS, certificates, and Entra applications | Function apps, managed identities, least-privilege role assignments, storage/Cosmos resources, queues, private endpoints, Front Door configuration, and alerts defined by Bicep |
| Network routes, private DNS resolution from the deployment runner, firewall approvals, and external integration allowlists | Private-by-default service settings and automated checks that direct portal origins remain closed |
| Model approval, content filters, Search corpus, retention/legal hold, identity grants, on-call routing, backups policy, SIEM/ServiceNow credentials, and secret rotation | Runtime configuration wiring, keyless Azure access, poison paths, health checks, and the sanitized deployment report |
| Final staging acceptance, exception approval, production enablement, and evidence storage | Test commands, acceptance criteria, upgrade/rollback instructions, and observable failure on a failed gate |

The deployment does not create or approve customer identity providers, model
capacity, Search indexes/corpus, notification destinations, external-system
accounts, public DNS, or certificates. A named customer owner must complete
those handoffs before production intake is enabled.

## Baseline application values

The shipped defaults are intentionally safe: `CAPABILITY_PROFILES=core`, private
storage, no consequential writeback, no ServiceNow create, no portal unless
enabled, and no live cloud calls in unit tests. When a customer enables a
profile, validate its dependencies before accepting work. Important customer
configuration names include `AZURE_OPENAI_ENDPOINT`,
`AZURE_OPENAI_ANALYSIS_DEPLOYMENT`,
`AZURE_OPENAI_PORTAL_CHAT_DEPLOYMENT`, `AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT`,
`AZURE_SEARCH_ENDPOINT`, `RAG_AZURE_SEARCH_INDEX`,
`CASE_QA_AZURE_SEARCH_INDEX`, `RAG_TENANT_ID`,
`RAG_SOURCE_STORAGE_ACCOUNT_NAME`, `RAG_SOURCE_STORAGE_ACCOUNT_URL`,
`RAG_SOURCE_CONTAINER`, `SPLUNK_*`,
`ELASTICSEARCH_*`, and `SERVICENOW_*`.

Do not put a service key, connection string, bearer token, client secret, or
private endpoint address in this repository, an image, a command example, or a
log. Azure managed identity is the default for Azure services. Key Vault is for
external integration secrets that cannot use managed identity; store secret
names in configuration and resolve values at runtime.

## Change and rollback record

For every customer configuration change record the old and new profile, owner,
approval, deployment operation ID, image digest, affected indexes/containers,
validation result, rollback condition, and expiration for any exception. A
rollback disables the affected capability or restores the last qualified image
and UI artifact. It does not make a private origin public or delete durable
evidence.

## Next

- **Path B step 1:** continue on this path — [`../../../README.md`](../../../README.md#path-b-customer-default)
- Customer-default deploy: [`AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md`](AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md)
- Upgrade and rollback: [`AZURE_UPGRADE_AND_ROLLBACK.md`](AZURE_UPGRADE_AND_ROLLBACK.md)
- **Path C:** custom profile bundles — [`../../../README.md`](../../../README.md#path-c-custom-profiles)
