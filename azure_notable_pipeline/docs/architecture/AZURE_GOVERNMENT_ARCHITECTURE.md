# Azure Government architecture

## Scope and sovereign boundary

This deployment is Azure US Government only. The default qualified region is
`usgovvirginia`; `usgovarizona` is a customer decision that requires separate
live service, model, quota, and private-network qualification. Connect to the
`AzureUSGovernment` cloud and use Government endpoints throughout. Commercial
cloud endpoints, audiences, registries, and DNS are not fallback options.

The application uses customer-owned Azure OpenAI deployments for analyzer,
chat, and embeddings, and Azure AI Search for tenant-scoped hybrid retrieval.
Azure Government service availability and feature behavior must be rechecked
for the customer's subscription and selected region before enablement. See
[Microsoft's Azure Government endpoint comparison](https://learn.microsoft.com/en-us/azure/azure-government/compare-azure-government-global-azure)
and [Foundry in Azure Government](https://learn.microsoft.com/en-us/azure/foundry/concepts/foundry-azure-government).

## Logical architecture

```mermaid
flowchart LR
    producer["Customer SIEM/SOAR or controlled uploader"]
    fd["Azure Front Door Premium\nprivate origin links"]
    web["Private Blob $web\nanalyst portal"]
    apim["Private API Management"]
    portal["Portal Function\nJWT/Entra + quota"]
    input["Private input Storage\nBlob input/incoming"]
    output["Private output Storage\nreports, cases, chunks, queues"]
    analyzer["Analyzer Function\nmanaged identity"]
    embed["Embed Function\nmanaged identity"]
    cosmos["Cosmos DB\nstate, cases, idempotency"]
    openai["Azure OpenAI\nchat + 1024-d embeddings"]
    search["Azure AI Search\nknowledge + case indexes"]
    kv["Key Vault\nexternal secrets only"]
    snow["ServiceNow\nseparate read/create boundaries"]
    splunk["Splunk\nread-only queries / gated writeback"]
    elastic["Elasticsearch\nread-only queries"]
    monitor["Azure Monitor + App Insights\ncustomer action group"]

    producer -->|private upload| input
    fd --> web
    fd --> apim --> portal
    input --> analyzer
    analyzer --> output
    analyzer --> cosmos
    analyzer --> openai
    analyzer --> search
    analyzer --> kv
    analyzer -. gated .-> splunk
    analyzer -. read-only .-> elastic
    analyzer -. gated .-> snow
    output --> embed --> openai
    embed --> cosmos
    embed --> search
    portal --> cosmos
    portal --> search
    portal --> openai
    portal --> kv
    analyzer -. telemetry .-> monitor
    embed -. telemetry .-> monitor
    portal -. telemetry .-> monitor
```

## Boundary rules

| Boundary | Required rule |
| --- | --- |
| Identity | Use a distinct user-assigned managed identity per Function app. Use RBAC for Azure data-plane services. |
| Network | Keep storage, Functions dependencies, `$web`, Search, Cosmos, Key Vault, and model resources on approved private paths with customer private DNS. |
| AI | Azure OpenAI deployment names, API version, content filters, quota, and model qualification are customer inputs. No commercial endpoint substitution. |
| State | Blob is the durable report/case source; Cosmos is transactional state; Azure AI Search is a rebuildable retrieval projection. |
| Evidence | Case evidence, advisory knowledge, and model inference remain visibly separate. Retrieval never becomes current-alert evidence without source attribution. |
| Actions | Splunk writeback and ServiceNow create are disabled by default and require separate capability, approval, identity, secret, and idempotency gates. |
| Recovery | Poison paths are independent and manually reconciled through documented replay procedures. |

## Deployment identity map

Record the following customer values outside the repository: subscription and
tenant IDs, resource group and naming prefix, region, resource IDs, Function
managed-identity object IDs, private endpoint/DNS owners, Azure OpenAI and Search
deployment/index names, Key Vault secret names, action group, on-call, and
approval owners. The reusable source tree contains no customer identities,
tokens, private addresses, or backup artifacts.
