# Azure AI inference operations

The analyzer uses Claude Sonnet 4.6 through Microsoft Foundry's
Anthropic-hosted Messages API. Portal chat and 1024-dimensional embeddings use
Azure OpenAI. There is no model fallback between these lanes and no API-key
fallback; each Function App uses its assigned managed identity.

## Mandatory customer approval

Before deployment, record explicit approval for the preview Sonnet offering,
that inference is hosted/processed on Anthropic infrastructure through Foundry,
applicable data-residency and processing terms, preview support/SLA limitations,
content-filter behavior, qualified deployment name, quota, and rollback model.
If those terms are not approved, stop; do not silently substitute Azure OpenAI
or a different Claude deployment.

All Functions, the qualified Foundry deployment, and Azure OpenAI deployments
must be in the selected v1 region (default `eastus`). Inputs may contain case
data; customer classification and residency approval therefore apply to the
full prompt and response, not only extracted IOCs.

## Runtime contract

| Lane | Settings | Identity permission | Operational bound |
| --- | --- | --- | --- |
| Analysis | `AZURE_AI_FOUNDRY_ANTHROPIC_BASE_URL`, `AZURE_AI_FOUNDRY_RESOURCE_ID`, `AZURE_AI_FOUNDRY_ANALYSIS_DEPLOYMENT` | analyzer MI inference role | forced `analyze_notable` tool; queue concurrency cap |
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
forced output contract, Azure OpenAI embeddings/chat where enabled, and no API
keys. Default CI remains mocked and never calls live models.

Rollback is configuration redeployment to the last customer-qualified
deployment name/image digest. Record who owns quota escalation and who approves
any model or content-filter change.
