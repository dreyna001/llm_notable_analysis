# Azure Implementation Tracker

Status values: `not started`, `in progress`, `blocked verification`, `complete`.

## Phases

| Phase | Owner | Status | Exit evidence |
| --- | --- | --- | --- |
| Phase 0 — scaffold and inventory | Phase 0 scaffold agent | complete | 66 Python tests, 92 frontend tests/build, root and module Bicep compilation |
| Phase 1 — core pipeline | Phase 1 implementation | in progress | Native queue/analyzer/embed wrapper contracts and Bicep are complete; live private-host deployment acceptance remains |
| Phase 2 — optional Wave 1 profiles | Phase 2 implementation | in progress | Cosmos IaC, native Search grounding, and native Cosmos persistence behavior are complete; remaining Wave 1 integration is tracked by its owning modules |
| Phase 3 — analyst portal | Phase 3 implementation | not started | OpenAPI, portal, Front Door/APIM acceptance |
| Phase 4 — disposition sync and operations | Phase 4 implementation | not started | Timer, runbooks, staging readiness |

## Native application boundaries

| Boundary | Owner | Status | Notes |
| --- | --- | --- | --- |
| `azure_clients.py` | Phase 1/2 | complete | Native SDK constructors use the app UAMI, explicit timeouts, Entra token scopes, and no key fallback |
| `blob_store.py` | Phase 1 | complete | Native bytes/text read/write/delete and bounded listing include ETag concurrency and stable typed failures |
| `secret_provider.py` | Phase 1 | complete | Key Vault MI lookup plus plain-text, JSON-object, and required-field validation; no `SecretString` shape |
| `queue_publisher.py` | Phase 1 | complete | Managed-identity Storage Queue publication uses the strict analyzer and versioned embed schemas with retryable failure classification |
| `analyzer_job.py` | Phase 1 | complete | Strict six-key v1 intake job validation/serialization is wired from polling Blob intake through analyzer queue normalization |
| `azure_openai_gateway.py` | Phase 2/3 | complete | Portal chat and embeddings use only Azure OpenAI; returned embedding vectors are strictly 1024-dimensional and analyzer fallback is forbidden |
| `azure_anthropic_gateway.py` | Phase 1 | complete | Native Foundry Messages call forces one `analyze_notable` tool with Sonnet 4.6; strict native block parsing and typed failures covered offline |
| `azure_search_retrieval.py` | Phase 2 | complete | Bounded native Search maps stable results; semantic rerank is opt-in and known SKU/billing unavailability falls back to plain Search |
| `cosmos_store.py` | Phase 2 | complete | Native aggregate operations use natural IDs/partitions, Strong point reads, ETag outcomes, business TTL, bounded keysets/cross-partition queries, and RU/latency telemetry |
| `blob_handler.py` | Phase 1 | complete | Core ETag-guarded orchestration preserves bounded gzip/JSON parsing, Sonnet analysis, deterministic reports, Blob-first sink ordering, and retry semantics |
| `embed_handler.py` | Phase 1/2/3 | in progress | Phase 1 strict v1 Queue dispatcher is registered and dependency-injectable; native Blob/Cosmos embedding remains deferred without AWS emulation |
| `function_app.py` | Phase 1/3/4 | in progress | Phase 1 polling intake Blob, analyzer queue, and case embed queue wrappers complete; timer and portal wrappers remain with later phases |

## Bicep modules

| Module | Owner | Status | Required capability |
| --- | --- | --- | --- |
| `main.bicep` | all phases | in progress | Root parameter/output contract established |
| `network.bicep` | Phase 1 | complete | VNet, delegated integration subnet, PE subnet, private DNS, required storage endpoints |
| `storage.bicep` | Phase 1/3 | in progress | Phase 1 input/output/host resources complete; UI origin remains Phase 3 |
| `identities.bicep` | Phase 1 | complete | Four user-assigned identities plus keyless host-storage grants |
| `container-registry-access.bicep` | Phase 1 | complete | Deterministic `AcrPull` grants for all four identities |
| `cosmos.bicep` | Phase 2 | complete | Single-region serverless Strong account, database, conditional aggregate containers, TTL/index contracts, and container-scoped SQL RBAC |
| `functions-analyzer.bicep` | Phase 1 | complete | Private polling Blob/analyzer queue app, scale/timeout overrides, native RBAC |
| `functions-embed.bicep` | Phase 1 | complete | Private embed queue app, scale/timeout override, native RBAC |
| `functions-disposition.bicep` | Phase 4 | not started | Timer app |
| `functions-portal.bicep` | Phase 3 | not started | Private portal app |
| `apim-portal.bicep` | Phase 3 | not started | Standard v2 API and policy |
| `frontdoor-portal.bicep` | Phase 3 | not started | Premium routes/private origins |
| `keyvault-access.bicep` | Phase 1/2 | complete | Conditional managed-identity secret-reader grants; no secret values provisioned |

## Test ports

The authoritative per-test disposition and owner is in
[`MODULE_INVENTORY.md`](MODULE_INVENTORY.md). Phase 0 currently runs the copied
Tier A tests, Azure config tests, native scaffold checks, and the unchanged
frontend unit suite. Cloud-client, handler, persistence, and deployment tests
remain assigned to their owning implementation phase.

## Phase 0 verification log

- Python: `66 passed` using the workspace Python environment.
- Frontend: `92 passed`; `vite build` succeeded. The build reports the inherited
  bundle-size warning for the 729 kB main chunk.
- Bicep: official standalone Bicep CLI 0.44.1 compiled `main.bicep` and every
  module shell. The root reports expected unused-parameter warnings until the
  resource modules are wired in Phase 1–4.
- Source audit: no `boto3` import exists in production Azure source; removed AWS
  runtime names are absent from the Azure config and env contracts.

## Phase 1 Sonnet analyzer verification log

- `ttp_analyzer.py` preserves the analyzer prompts, native tool schema, ATT&CK
  filtering, deterministic policy validation, token bounds, repair-once behavior,
  and report-facing output contract. The runtime performs no transport retry;
  the Anthropic SDK client is the sole transport retry owner.
- `azure_anthropic_gateway.py` calls native `AnthropicFoundry.messages.create()`
  with deployment default `claude-sonnet-4-6`, forced `analyze_notable` tool use,
  `disable_parallel_tool_use=true`, and no thinking, effort, raw-JSON, Azure
  OpenAI, or API-key fallback path.
- Focused analyzer/gateway/prompt/golden suite: `20 passed, 1 skipped`, plus 3
  golden-rubric subtests. The concurrent Phase 1 full-suite snapshot reached
  `123 passed, 1 skipped`, plus 3 golden-rubric subtests, with one unrelated
  in-progress private-intake Bicep contract failure remaining.

## Phase 1 native boundary verification log

- `azure_clients.py` constructs Blob, Queue, Key Vault, Cosmos, Search, Azure
  OpenAI, and Anthropic Foundry clients with the Function App's explicit
  user-assigned identity. Foundry/OpenAI bearer scopes and ambient API-key
  rejection are covered by unit tests.
- `blob_store.py` keeps container/blob vocabulary, hides SDK paging and response
  shapes, supports optimistic ETag reads/writes/deletes, and caps list/delete
  operations. `secret_provider.py` returns application text/JSON values directly
  and validates required string fields.
- `azure_openai_gateway.py` normalizes portal chat text/tool-call/usage values,
  requests `dimensions=1024`, rejects every returned vector with any other
  dimension, and never reads the Foundry analyzer deployment as a fallback.
- Focused native-boundary suite: `26 passed`. The concurrent full-suite snapshot
  reached `123 passed, 1 skipped`, plus 3 golden-rubric subtests, with one
  unrelated in-progress private-intake Bicep assertion remaining.

## Phase 1 core runtime verification log

- Polling Blob intake reads native `blob_properties`, publishes the exact strict
  analyzer v1 job, and the analyzer queue wrapper rejects non-contract payloads
  before constructing `BlobCreatedInput`.
- The core handler requires the queued ETag on the Blob read, treats a 412/stale
  ETag as a terminal `superseded` outcome, and propagates transient Blob, Queue,
  and Foundry failures for Functions retry/poison handling.
- Bounded gzip decompression, UTF-8/JSON normalization, deterministic
  `reports/<finding_id>.md|json|html` paths, overwrite-safe replay behavior,
  Blob-before-writeback ordering, and the versioned case-embed publication
  schema are covered with native fixtures.
- The analyzer enqueues the exact v1 native embed job only when Case Q&A is
  enabled and a native archive workflow has produced a case-envelope
  reference. It does not invent an archive/Cosmos result, and publication
  failures propagate for queue retry/poison behavior.
- The Functions runtime enumerates `case_embed_queue` with the Bicep-owned
  `%CASE_EMBED_QUEUE_NAME%` / `OutputStorage` binding. The wrapper rejects
  malformed or unknown-version jobs before dispatch; until the native
  Blob/Cosmos workflow lands, valid jobs fail with an explicit deferred-workflow
  error instead of an AWS-shaped or fake persistence path.
- Focused core intake/analyzer/embed/runtime and infrastructure suite: `41 passed`.
  Full Azure Python suite after this gate fix: `154 passed, 1 skipped`, plus 3
  golden-rubric subtests.

## Phase 1 infrastructure verification log

- Bicep CLI 0.44.1 compiles `main.bicep` and every module. Remaining warnings
  are unused root parameters owned by future portal, Search, and Cosmos phases.
- Eight infrastructure security contract tests pass: private/keyless storage,
  required private endpoints, four UAMIs, deterministic ACR/host RBAC, Foundry
  access, digest image reuse, wrapper isolation, and no credential fallback.
- The Bash and PowerShell deployment gates statically verify the configured
  digest/UAMI ACR pull contract, identity-based host Blob/Queue/Table settings,
  Functions host health, and the exact analyzer/embed wrapper sets. Their
  name-only app-setting audit rejects ACR, storage/Azure Files, Foundry,
  OpenAI, Search, and Cosmos credential or secret-bearing variants without
  emitting setting values.
- `bash -n` passes for the image-build and setup/deploy scripts. Live Azure
  deployment, RBAC propagation, image pull, and private host readiness remain
  unverified until run with a customer subscription from a
  private-network-connected deployment runner.
- Local container build is blocked in this WSL session because Docker Desktop
  WSL integration is disabled; `build-image.sh` uses ACR Build as the operator
  verification path once authenticated Azure infrastructure is available.

## Phase 2 Cosmos infrastructure verification log

- `cosmos.bicep` creates one key-auth-disabled, single-region serverless Cosmos
  DB for NoSQL account with Strong consistency and one database. The core
  side-effect idempotency container is unconditional; case index, ServiceNow
  disposition state, and chat-history aggregates have explicit deployment
  gates tied to their owning capability settings.
- All six aggregate contracts define their natural partition key. Expiring
  aggregates enable per-item TTL with `defaultTtl=-1`; sync checkpoint state has
  no TTL. Case, disposition, session, and message ordered query shapes have
  matching consistent composite indexes. No account, database, or container
  throughput property exists, preserving the serverless contract.
- Built-in Cosmos SQL data reader/contributor assignments are deterministic and
  container-scoped for analyzer, embed, disposition, and portal identities.
  Function settings use only the Cosmos endpoint, database name, and scoped
  container names; no key or connection-string path is provisioned.
- Bicep CLI 0.44.1 compiled the root and every module. Fourteen focused static
  infrastructure contract tests pass; Bash and PowerShell deployment scripts
  also pass syntax/parser checks with required Cosmos deployment parameters.

## Phase 2 Search and grounding verification log

- `azure_search_retrieval.py` caps each query at 20 results and 8,000 query
  characters, maps native text, source metadata, Search score, and semantic
  reranker score into stable `RetrievalResult` values, and exposes typed
  failures without an AWS-shaped intermediate response.
- Semantic parameters are sent only when `RAG_RERANK_ENABLED=true`. Known
  semantic feature, SKU, quota, or billing rejection logs
  `rerank_status=skipped` and retries once as plain Search; unrelated malformed
  requests do not silently downgrade.
- General RAG, SPL-query, Elasticsearch-query, and portal-chat advisory lanes
  preserve status, failure policy, source/section attribution, and character
  budgets. Case-chunk BM25/RRF behavior uses bounded application-facing chunk
  loading and the strict 1024-dimension Azure OpenAI gateway.
- Focused Search, grounding, portal-KB, and case-chunk suite: `19 passed` with
  native fakes only and no network calls.

## Phase 2 Cosmos persistence verification log

- `cosmos_store.py` defines the six natural aggregate partition contracts and
  exposes only application documents and typed native outcomes. Conditional
  creates map Cosmos 409 to `created=false`; ETag replaces/deletes map 404/412
  to explicit outcomes without synthesizing DynamoDB exceptions or shapes.
- Case listing uses a bounded newest-first `(processed_at, case_id)` keyset and
  never returns a Cosmos continuation token. Correlation/disposition linking is
  a bounded indexed cross-partition query; chat session and message queries are
  partition-scoped, ordered, capped, ownership-checked, and prune the oldest
  session plus its messages at the configured user limit.
- Expiring case, side-effect, disposition, session, and message documents derive
  positive per-item `ttl` values from their retained business expiry fields.
  Every store operation logs Cosmos request charge and elapsed latency.
- Idempotency, case-index, chat-history, and disposition-sync persistence ports
  preserve their public business outcomes while using plain native documents.
  The focused offline suite reports `9 passed, 1 skipped`; the skip is the
  optional Cosmos emulator profile. Full Azure Python regression reports
  `188 passed, 2 skipped`, plus 3 golden-rubric subtests, with no network calls.
