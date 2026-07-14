# Azure notable pipeline readiness package

Use this checklist as the production-enable record. Store completed
customer-specific values in the approved customer system, not this repository.

## Customer decisions

- [ ] Dedicated subscription, resource group, naming prefix, Azure Commercial
  region, and same-region Foundry/OpenAI qualification approved.
- [ ] Anthropic-hosted Sonnet 4.6 preview, data-processing/residency terms,
  content filtering, quota, deployment name, and rollback model approved.
- [ ] Azure OpenAI chat/embedding deployments and filters approved.
- [ ] AI Search source owners, index names/schema, ingestion, refresh/deletion,
  semantic rerank, and rollback approved.
- [ ] Primary intake profile and optional manual fallback recorded with
  SIEM/SOAR hosting, network, DNS, identity, credential, retry/DLQ, monitoring,
  and operational owners.
- [ ] Portal JWT issuer/audience or Entra app role approved; synthetic identity
  object ID and token issuance/renewal/rotation owner recorded.
- [ ] Retention, chat history, capability profiles, and consequential-action
  approval boundaries recorded.
- [ ] Alert action group, exact thresholds/windows, on-call, and escalation
  recorded.
- [ ] Storage and Functions/Cosmos zone support is confirmed for the selected
  region; LRS/ZRS and zone-redundancy cost exceptions are recorded.
- [ ] Functions host-storage topology and globally unique per-app names are
  approved; any shared-to-isolated cutover has a drain/replay/rollback plan.
- [ ] Cosmos RTO/RPO and single-region serverless limitation are accepted, or a
  separately rehearsed provisioned multi-region migration is approved.

## Deployment and security gate

- [ ] Immutable image digest scanned, recorded, and matches ACR resource ID;
  prior qualified digest is available.
- [ ] Bicep deploy is reproducible; each Function uses a distinct UAMI for ACR,
  host storage, and least-privilege data access.
- [ ] Blob/container soft delete and Blob versioning are enabled with bounded
  previous-version retention; Cosmos continuous backup is enabled.
- [ ] No storage/ACR/Foundry/OpenAI/Search/Cosmos key or connection string exists
  in app settings, image, logs, or committed files.
- [ ] Storage, Function, APIM, and `$web` origins are private; Front Door private
  links are approved; direct origins fail.
- [ ] Key Vault contains only customer integration secrets; rotation owners are
  recorded.
- [ ] Splunk writeback and ServiceNow create are disabled during staging.

## Staging acceptance

- [ ] `scripts/test-pipeline.sh --staging-gate` or PowerShell equivalent passes
  in the dedicated subscription with synthetic fixtures/test identities.
- [ ] Private intake produces the expected report and managed-identity live
  smoke covers Foundry forced output, Azure OpenAI 1024-d embeddings/chat where
  enabled, Search grounding where enabled, Blob/Queue, and Cosmos.
- [ ] At least `3 * AnalyzerMaxInstanceCount` jobs show bounded concurrency,
  queued surplus, drain, and normal idempotent outcomes.
- [ ] Five failures are proven separately for Blob publication, analyzer, and
  embed; the correct poison queue/alert fires once and nothing auto-replays.
- [ ] Duplicate and out-of-order delivery produce one business result and no
  duplicate writeback.
- [ ] OpenAPI is unchanged; negative auth, required role, same-origin CORS, two-
  identity ownership, direct-origin denial, and authenticated Front Door pass.
- [ ] Chat timeout chain is browser 220 / Function 225 / APIM 230 / Front Door
  240 seconds; non-chat APIM operations retain the 30-second default.
- [ ] Disposition disabled-path dry run and fake mapping/checkpoint tests pass;
  any live test uses only the isolated ServiceNow test instance/read credential.

## Operations and recovery

- [ ] All required Monitor alerts route to the action group and were exercised.
- [ ] Synthetic `/ready` uses a dedicated non-human least-privilege identity;
  issuance, renewal, rotation, and failure escalation are tested.
- [ ] Operators can distinguish and snapshot all three poison queues, check for
  durable outcomes, replay one message idempotently, and reconcile state.
- [ ] Intake pause, capability disable, prior-digest/UI rollback, AI/Search
  config rollback, disposition disable, and resume criteria are rehearsed.
- [ ] Deployment operation IDs, test timestamp/results, residual exceptions,
  approvers, and production enable date are recorded.

Production intake remains disabled until every applicable item passes or has a
time-bounded, owner-approved exception with rollback.
