# Azure Government parity implementation plan

## Target

- Azure US Government only.
- Default region: `usgovvirginia`; permit `usgovarizona` only after live service and model qualification.
- Azure OpenAI provides analyzer, chat, and embedding models through customer-owned deployments.
- Azure AI Search provides tenant-scoped hybrid vector retrieval.
- Blob Storage remains the durable source of truth; Cosmos DB remains transactional application state.
- Customer-specific names, quotas, retention, identities, keys, endpoints, and integration credentials remain deployment inputs.

## Product-enforced contracts

- Reject commercial-cloud endpoints, audiences, DNS suffixes, regions, and image registries.
- Require immutable image digests, managed identities, private data paths, and explicit Azure Government token audiences.
- Validate input retention against queue residence and recovery windows.
- Validate required profile dependencies before Functions accept work.
- Preserve one logical case per `finding_id` with immutable analysis runs and an atomic latest-run pointer.
- Fence external side effects and preserve uncertain external-success outcomes for reconciliation.
- Return completed chat results for replayed client request IDs without another model call.
- Keep risky write capabilities disabled unless their profile, approval, identity, secret, and idempotency dependencies are complete.

## Implementation checklist

### Sovereign cloud and infrastructure

- [x] Make `AzureUSGovernment` the only supported cloud and `usgovvirginia` the default region.
- [x] Replace the analyzer's commercial Foundry Claude dependency with Azure OpenAI structured output/tool calling.
- [x] Use Government resource audiences and endpoint suffix validation for OpenAI, Search, Storage, Cosmos, Key Vault, ACR, Front Door, Functions, and Entra.
- [x] Add optional customer-managed-key parameters and role assignments without requiring CMK for every customer.
- [x] Route Front Door privately to the portal Function without an unsupported Government APIM v2 dependency.
- [x] Add Cosmos private endpoint and private DNS; disable its public data endpoint.
- [x] Keep production backup controls configurable until the product backup/recovery decision is approved; record the gap internally.

### Reliability and data integrity

- [x] Add immutable `run_id` records derived from Blob version/ETag processing identity.
- [x] Publish the latest run with Cosmos optimistic concurrency and reject out-of-order pointer regression.
- [x] Stage case retrieval generations and publish them only after all documents are indexed.
- [x] Add queue TTL settings and deployment validation against customer input retention.
- [x] Add fenced side-effect leases and an `external_success_unrecorded` reconciliation state.
- [x] Add completed chat-request replay ahead of distributed quota admission.

### Azure AI Search retrieval

- [x] Define customer-selected SOC, Splunk, Elasticsearch, and case index names.
- [x] Add manifest-driven Blob ingestion with schema validation, deterministic chunks, embeddings, provenance, tombstones, deletion, and reconciliation.
- [x] Add a dedicated ingestion queue, poison queue, Function trigger, managed identity permissions, scaling, and alerts.
- [x] Use hybrid keyword/vector queries with tenant/corpus filters for knowledge sources.
- [x] Use hybrid keyword/vector queries with tenant/case/run filters for case Q&A.
- [x] Remove online Blob list/read fan-out from case retrieval.

### Optional integrations

- [x] Wire ServiceNow draft/create into analyzer orchestration with approval and fenced idempotency.
- [x] Add a customer-configurable Splunk SOAR/Phantom-to-Blob intake helper.
- [x] Preserve read-only Splunk/Elasticsearch query policy and disposition-sync separation.

### Documentation and validation

- [x] Add Azure Government customer configuration, security, capability, retention/recovery, RAG, SIEM, MITRE, testing, and golden-evaluation guides.
- [x] Add Azure architecture and end-to-end diagrams.
- [x] Add executive workflow and readiness artifacts.
- [x] Add local deterministic coverage across intake, queues, immutable runs, ingestion, retrieval, portal replay, and side-effect uncertainty; use Azurite for Blob/Queue and injected substitutes where Azure has no faithful emulator.
- [x] Add Bicep contract tests for sovereign endpoints, private networking, CMK option, queue retention, identities, and alerts.
- [ ] Require live Azure Government validation for model availability/quota, managed identity, private DNS, Search vector behavior, Front Door/Function Private Link, poison recovery, and rollback.

## Deferred internal gap

- Customer backup and disaster-recovery objectives are not yet a product-level commitment. Azure resource protection settings must remain explicit deployment choices until that decision is made; do not present backup/recovery guarantees to customers.
