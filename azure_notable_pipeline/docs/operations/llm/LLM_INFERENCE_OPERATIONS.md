# Azure OpenAI inference operations

The Azure Government profile uses customer-owned Azure OpenAI deployments for
analysis, portal chat, and 1024-dimensional embeddings. There is no model
fallback between these lanes and no API-key fallback; each Function App uses
its assigned managed identity. Any legacy Foundry/Anthropic settings in the
source tree are not a substitute for this profile and require separate
customer qualification before use.

## Mandatory customer approval

Before deployment, record explicit approval for the Azure OpenAI model
deployment, applicable data-processing and residency terms, support/SLA
limitations, content-filter behavior, qualified deployment name, quota, and
rollback model. If those terms are not approved, stop; do not silently
substitute a different model or endpoint.

All Functions, Azure OpenAI deployments, and Azure AI Search resources must be
qualified in Azure Government `usgovvirginia` by default. Inputs may contain
case data; customer classification and residency approval therefore apply to
the full prompt and response, not only extracted IOCs.

## Runtime contract

| Lane | Settings | Identity permission | Operational bound |
| --- | --- | --- | --- |
| Analysis | `AZURE_OPENAI_ENDPOINT`, customer analyzer deployment name | analyzer MI OpenAI user | strict structured output; queue concurrency cap |
| Chat | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_PORTAL_CHAT_DEPLOYMENT` | portal MI OpenAI user | gateway 220s, Function 225s, Front Door 240s |
| Embeddings | `AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT` | embed/portal MI OpenAI user | exactly 1024 dimensions |

Set quota for at least the qualified analyzer/embed concurrency. Jobs above
the cap remain queued. Do not increase `AnalyzerMaxInstanceCount` or
`EmbedMaxInstanceCount` without quota, latency, burst, and cost validation.

## Monitoring and response

Alert on sustained 429s/5xx, timeouts, analyzer/embed backlog, poison messages,
and abnormal latency/token use. A single transient provider error is retried by
the owning SDK/queue path; do not add a second unbounded retry loop. For
sustained throttling, pause intake or reduce the scale cap, preserve queued
work, request quota, then replay only poison messages after checking durable
outcomes.

Content-filter rejection is not evidence about the case. Record the provider
status as an operational failure and follow customer policy for redaction or
manual review. Never weaken filtering ad hoc in production.

The staging live smoke uses committed synthetic alerts and proves analyzer MI,
Azure OpenAI structured output, embeddings/chat where enabled, and no API keys.
Default CI remains mocked and never calls live models.

Rollback is configuration redeployment to the last customer-qualified
deployment name/image digest. Record who owns quota escalation and who approves
any model or content-filter change.

## Deploy path — next

- **Path B step 4 complete (or skipped):** [`../deployment/DEPLOYMENT_IMAGE_STEPS.md`](../deployment/DEPLOYMENT_IMAGE_STEPS.md)
- **Path B step 6:** [`../deployment/AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md`](../deployment/AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md) when deploying the customer-default bundle
- **Path C:** [`../../../README.md`](../../../README.md#path-c-custom-profiles) when analysis or embeddings are enabled
