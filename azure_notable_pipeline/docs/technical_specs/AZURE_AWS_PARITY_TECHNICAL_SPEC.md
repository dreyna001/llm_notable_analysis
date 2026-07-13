# Azure / AWS parity technical specification

**Status:** Normative shipped Azure v1 contract. The implementation plan remains
the design provenance; this document defines the operator-visible contract.

## Scope and invariants

Azure preserves the AWS product behavior, schemas, policy decisions,
capability-profile semantics, ordering, ownership, and idempotency outcomes. It
does not emulate boto3, Lambda events, S3/DynamoDB APIs, Bedrock response shapes,
or AWS configuration names. Durable compatibility fields such as `source_key`,
`input_bucket`, and `*_key` retain their published spelling; their Azure values
refer to containers and Blob names.

Profiles are `core`, `html_reports`, `rag`, `spl_readonly`,
`elastic_readonly`, `ticket_draft`, `action_gated`, and `analyst_portal`.
Risky writes are disabled by default and separately gated. Profile changes are
configuration/Bicep deployments, not code changes.

## Runtime architecture

| Capability | Azure implementation |
| --- | --- |
| Private intake | polling Blob trigger on `input/incoming/{name}` plus input queue receipts |
| Analyzer | strict Storage Queue job, Premium Function, Foundry Claude Sonnet 4.6 |
| Reports/archive | private output Blob `reports/`, `cases/`, `case_chunks/` |
| Embed | versioned queue job, Azure OpenAI 1024-d embeddings |
| Persistence | native Cosmos application operations with Strong point-read semantics |
| Grounding | Azure AI Search stable retrieval objects and attribution |
| Portal | Front Door Premium, private `$web`/APIM Standard v2/Function origins |
| Disposition | daily timer, read-only ServiceNow pull, Cosmos state/cursor |

One immutable `linux/amd64` image digest runs four isolated Function Apps, each
with its own UAMI. Managed identity is mandatory for ACR, Functions host
storage, Blob/Queue, Foundry, Azure OpenAI, Search, Cosmos, and Key Vault. Azure
service keys, storage connections, ACR credentials, and public-origin fallback
are forbidden. Key Vault holds only external integration secrets that cannot
use managed identity.

## Intake and queue contracts

The analyzer message has exactly six fields: integer `schema_version=1`,
nonempty `container_name`, `blob_name`, `etag`, RFC3339 UTC `last_modified`, and
nonnegative integer `size_bytes`. The embed message has exactly
`schema_version=1`, `case_envelope_container`, and
`case_envelope_blob_name`. Missing/extra/invalid fields fail closed.

Analyzer and embed queue settings are `batchSize=1`, `newBatchThreshold=0`, and
`maxDequeueCount=5`. Default analyzer/embed scale caps are five. Surplus work
queues normally; processing failure poisons after five attempts. Blob
publication failure poisons independently on input. Duplicate/out-of-order
delivery is expected and produces one report/case and idempotent side effects.

## Data and API contracts

Blob prefixes and retention are: `incoming/` (default 2 days), `reports/`
(default 30 days), and `cases/`/`case_chunks/` (default 30 days when portal is
enabled). Containers are private and encrypted with Microsoft-managed keys.
The unchanged portal OpenAPI document is normative. Stable user ownership comes
only from the validated `sub` claim. Responses are same-origin without
permissive CORS.

Cosmos uses native documents and natural partitions: side-effect identity,
`/case_id`, `/snow_sys_id`, `/job_name`, `/user_id`, and `/session_id` as
applicable. Physical IDs, ETags, and indexing are Azure implementation details;
case/report/disposition business fields, ordering, bounded pagination,
retention, replay, and ownership are parity contracts.

## AI and evidence boundary

Analysis uses the customer-qualified Anthropic-hosted Sonnet deployment through
Foundry and forces `analyze_notable` structured output. Chat and embeddings use
explicit Azure OpenAI deployment names; no lane substitutes for another.
Embeddings are exactly 1024 dimensions. General/Search grounding is advisory
and source-attributed; it cannot be represented as current-case evidence.
Model output is parsed, validated, optionally repaired once, and policy checked
before persistence or action.

The region, preview/Anthropic hosting and data-processing terms, content filters,
model deployments, quota, and rollback model require recorded customer
approval. Chat timeout chain is browser/gateway 220 seconds, Function 225
seconds, Front Door 240 seconds.

## Security and external integrations

Storage and origins use private endpoints and customer private DNS. One primary
vendor-neutral intake profile—direct, transfer bridge, or controlled manual—is
recorded per customer. External inputs, URLs, paths, queries, maps, and model
outputs are bounded and validated. SPL/Elasticsearch investigation is read-only
and allowlisted. ServiceNow create and Splunk writeback require distinct enable,
approval, and idempotency gates. Disposition sync is a separate read-only
inbound credential and never advances its cursor on failed runs.

Portal `jwt` mode validates signature, issuer, audience, expiry, and `sub`;
`iam` additionally validates the required Entra app role. `/health` and `/ready`
are authenticated. A dedicated non-human identity supplies the customer-owned
synthetic check; the stack stores no long-lived token.

## Failure, observability, and acceptance

Production requires an action group and alerts for all three poison queues,
15-minute backlog, Function failure/timeout, sustained Foundry/OpenAI/Cosmos
errors, Front Door 5xx, authenticated synthetic failure, and missed disposition
sync. Exact thresholds and owners are customer deployment decisions.

Default CI uses fakes/emulators and no live cloud/model calls. The dedicated
staging gate proves private intake, 3x burst, five-attempt poison paths,
duplicate delivery, unchanged OpenAPI, authentication and cross-user ownership,
timeout chain, disposition dry run, direct-origin denial, and managed-identity
Foundry/OpenAI/Search/Cosmos behavior using synthetic data. Production case
data, production SIEM, and external writeback are forbidden in staging.

Acceptance additionally requires reproducible Bicep/digest deployment, no
`boto3` in production source, no Azure service keys, customer decision record,
tested replay/rollback, and the runbooks indexed under `docs/operations/`.
