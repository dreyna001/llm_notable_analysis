# Azure Implementation Tracker

Status values: `not started`, `in progress`, `blocked verification`, `complete`.

## Phases

| Phase | Owner | Status | Exit evidence |
| --- | --- | --- | --- |
| Phase 0 — scaffold and inventory | Phase 0 scaffold agent | complete | 66 Python tests, 92 frontend tests/build, root and module Bicep compilation |
| Phase 1 — core pipeline | Phase 1 implementation | complete | Native queue/analyzer/embed wrapper contracts and Bicep are complete; live private-host deployment acceptance remains a customer-subscription verification step |
| Phase 2 — optional Wave 1 profiles | Phase 2 implementation | complete | Native Search grounding, optional-profile orchestration, Cosmos persistence, and archive/embed integration pass the offline Phase 2 gate: 202 passed, 2 skipped, plus 3 golden-rubric subtests |
| Phase 3 — analyst portal | Phase 3 implementation | blocked verification | Offline portal runtime/infra tests and Bicep compile complete; live Front Door private-endpoint approval, direct-origin denial, and authenticated `/ready` acceptance require a customer Azure subscription |
| Phase 4 — disposition sync and operations | Phase 4 implementation | blocked verification | Native timer/runtime and offline operations package complete; live dedicated-subscription staging gate remains |

## Native application boundaries

| Boundary | Owner | Status | Notes |
| --- | --- | --- | --- |
| `azure_clients.py` | Phase 1/2 | complete | Native SDK constructors use the app UAMI, explicit timeouts, Entra token scopes, and no key fallback |
| `blob_store.py` | Phase 1 | complete | Native bytes/text read/write/delete and bounded listing include ETag concurrency and stable typed failures |
| `secret_provider.py` | Phase 1 | complete | Key Vault MI lookup plus plain-text, JSON-object, and required-field validation; no `SecretString` shape |
| `queue_publisher.py` | Phase 1 | complete | Managed-identity Storage Queue publication uses the strict analyzer and versioned embed schemas with retryable failure classification |
| `analyzer_job.py` | Phase 1 | complete | Strict six-key v1 intake job validation/serialization is wired from polling Blob intake through analyzer queue normalization |
| `azure_openai_gateway.py` | Phase 2/3 | complete | Portal chat and embeddings use only Azure OpenAI; returned embedding vectors are strictly 1024-dimensional and analyzer fallback is forbidden |
| `azure_anthropic_gateway.py` | Phase 1/2 | complete | Native Foundry Messages analysis forces one `analyze_notable` tool; optional bounded query synthesis uses strict text-only responses with the same typed failure boundary |
| `azure_search_retrieval.py` | Phase 2 | complete | Bounded native Search maps stable results; semantic rerank is opt-in and known SKU/billing unavailability falls back to plain Search |
| `cosmos_store.py` | Phase 2 | complete | Native aggregate operations use natural IDs/partitions, Strong point reads, ETag outcomes, business TTL, bounded keysets/cross-partition queries, and RU/latency telemetry |
| `case_archive.py` | Phase 2/3 | complete | Deterministic legacy envelope/index schema, Blob layout, retention, replay/collision suppression, and native Cosmos conditional create are preserved |
| `case_embed.py` | Phase 2/3 | complete | Deterministic bounded chunk replacement uses 1024-d Azure OpenAI vectors and ETag-retried Cosmos ready/failed status updates |
| `blob_handler.py` | Phase 1/2 | complete | ETag-guarded orchestration preserves core behavior and AWS ordering for native RAG, SPL, and Elasticsearch grounding/generation/read-only execution, enrichment, interpretation, and deterministic reports |
| `embed_handler.py` | Phase 1/2/3 | complete | Strict v1 Queue dispatcher invokes native Blob/OpenAI/Cosmos embedding and propagates failures for Functions retry/poison handling |
| `portal_chat.py` / `case_chat.py` | Phase 3 | complete | Native Azure OpenAI synthesis and 1024-d case retrieval preserve grounding attribution, attached-case behavior, bounded context/history, timeout, and deterministic read-only policy |
| `portal_handler.py` | Phase 3 | complete | Native Azure HTTP routing preserves the published API/response contracts with application JWT or Entra app-role auth on every route, fail-closed `sub`, ownership isolation, same-origin responses, bounded inputs, and injectable native chat orchestration |
| `function_app.py` | Phase 1/3/4 | complete | Exact six-wrapper host inventory: analyzer intake/queue, embed queue, disposition timer, operations monitor timer, and wildcard portal HTTP; every app enables only its owned functions |

## Bicep modules

| Module | Owner | Status | Required capability |
| --- | --- | --- | --- |
| `main.bicep` | all phases | blocked verification | Root composition, production gates, outputs, and all four apps compile; live Azure deployment acceptance remains |
| `network.bicep` | Phase 1 | complete | VNet, delegated integration subnet, PE subnet, private DNS, required storage endpoints |
| `storage.bicep` | Phase 1/3 | complete | Dedicated private/keyless `$web` static website, SPA fallback, and deployer MI/RBAC added |
| `identities.bicep` | Phase 1 | complete | Four user-assigned identities plus keyless host-storage grants |
| `container-registry-access.bicep` | Phase 1 | complete | Deterministic `AcrPull` grants for all four identities |
| `cosmos.bicep` | Phase 2 | complete | Single-region serverless Strong account, database, conditional aggregate containers, TTL/index contracts, and container-scoped SQL RBAC |
| `functions-analyzer.bicep` | Phase 1 | complete | Private polling Blob/analyzer queue app, scale/timeout overrides, native RBAC |
| `functions-embed.bicep` | Phase 1 | complete | Private embed queue app, scale/timeout override, native RBAC |
| `functions-disposition.bicep` | Phase 4 | complete | Private/keyless 900s timer app, exact wrapper isolation, conditional Blob/Key Vault/Cosmos access, and queue-depth-reader RBAC |
| `functions-portal.bicep` | Phase 3 | complete | Private portal app/PE, 225s timeout, exact wrapper isolation, keyless app settings, Blob/OpenAI/Search/Cosmos access |
| `apim-portal.bicep` | Phase 3 | complete | Standard v2, VNet integration, OpenAPI import, authenticated 30s backend policy; public access staged only for AFD connection approval |
| `frontdoor-portal.bicep` | Phase 3 | complete | Premium private `web`/`Gateway`/`sites` origins, ordered chat/API routes, 240s timeout, no API cache or single-origin probes |
| `keyvault-access.bicep` | Phase 1/2 | complete | Conditional managed-identity secret-reader grants; no secret values provisioned |
| `observability.bicep` | Phase 4 | complete | Conditional action-group-only poison/backlog/dependency/edge/synthetic/disposition alerts consume the locked structured queue trace schema |

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

## Phase 2 optional-profile orchestration verification log

- `blob_handler.py` now retrieves general advisory RAG before the primary
  analysis, then applies only the selected backend's grounding, validated query
  generation, deterministic read-only execution, result enrichment, and
  optional bounded interpretation before report rendering and sink/archive
  side effects. Disabled profiles do not enter these lanes.
- RAG and query-grounding status, snippet counts, failure messages, backend,
  executor, and result counts retain the AWS report metadata contract. Search
  contexts keep explicit source/section attribution and configured character
  budgets; SPL and Elasticsearch executors retain their allowlists, time/row
  caps, concurrency caps, and denial results.
- Optional model synthesis uses the native Anthropic Foundry text response
  boundary and the existing deterministic SPL/Elasticsearch/interpreted-result
  validators. Generation and interpretation remain fail-soft; general RAG
  retains its configured `suppress`/`fail_closed` behavior.
- Focused offline optional-profile/analyzer/grounding/investigation suite:
  `57 passed`. Full Azure regression after the integration gate:
  `202 passed, 2 skipped`, plus 3 golden-rubric subtests. The Cosmos
  correlation-query cap now preserves the AWS business bound of 200.

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

## Phase 2 case archive and embedding verification log

- `case_archive.py` preserves deterministic case IDs, `cases/YYYY/MM/DD/` Blob
  names, durable legacy envelope/index fields, bounded source completeness,
  retention timestamps, normalized verdicts, and identity replay/collision
  outcomes while using native Blob writes and Cosmos conditional creates.
- The analyzer's default archive seam honors `suppress`/`fail_closed` and queues
  only an actual native envelope reference. `case_embed.py` replaces bounded
  chunk prefixes, requests Azure OpenAI vectors at exactly 1024 dimensions,
  writes deterministic chunk IDs, and updates ready/failed status with bounded
  Cosmos ETag retries.
- Strict v1 embed jobs reject missing, extra, malformed, or unknown-version
  fields. Failed native embedding raises through the Functions wrapper for the
  configured Storage Queue retry and poison behavior; successful duplicate
  delivery converges through chunk replacement and status updates.
- Focused archive/embed/analyzer seam/runtime suite: `31 passed`. Full Python
  regression after the Phase 2 gate: `202 passed, 2 skipped`, plus 3
  golden-rubric subtests. The combined Cosmos/optional-profile/archive/embed
  seam gate reports `42 passed, 1 skipped`.

## Phase 3 private portal infrastructure verification log

- The root conditionally deploys one portal Function App from the same immutable
  digest, APIM Standard v2, Front Door Premium, and a dedicated private/keyless
  `$web` static website for `core,analyst_portal`. Portal app settings preserve
  the 225-second runtime timeout and native Cosmos, Blob, Search, and OpenAI
  contracts without Azure service keys or connection strings.
- Front Door sends all `/api/*` traffic, including chat, plus authenticated
  `/health` and `/ready` to the private APIM `Gateway` origin, and uses a private
  Storage `web` origin for the SPA. APIM gives only the imported chat operation
  a 230-second backend timeout; all other operations keep the 30-second API
  default. API routes have no cache configuration and all single-origin groups
  omit unauthenticated health probes.
- Bash and PowerShell deployment gates build/test and upload the SPA with Entra
  auth, approve and poll both generated Front Door managed private endpoint
  connections, then disable APIM public access. They verify direct APIM denial,
  disabled Function/Storage public access, and authenticated Front Door `/ready`
  without logging the bearer token. Both scripts fail before mutation when Entra
  `iam` mode omits its required app role, preventing an empty APIM/Easy Auth role
  contract from reaching deployment.
- Bicep CLI 0.45.15 compiles the root and every module. The focused static
  infrastructure/scaffold gate reports `22 passed`; Bash syntax validation and
  PowerShell 7.6.3 parser validation succeed. The local frontend test/build
  command remains unavailable because the installed Windows Node runtime
  rejects WSL1; this change does not modify frontend source or dependencies.
  Live Azure mutation was intentionally not run; customer-subscription private
  endpoint approval, propagation, direct-origin denial, and authenticated
  synthetic acceptance remain the Phase 3 deployment blocker.

## Phase 3 portal chat verification log

- `portal_chat.py` uses only the native Azure OpenAI gateway and the configured
  portal deployment. It propagates the 225-second business timeout, merges
  normalized gateway usage into deterministic context estimates, sends no tool
  definitions, and rejects any unexpected tool call without execution.
- Selected-case Q&A performs bounded BM25/vector fusion with exactly 1024-d
  Azure OpenAI query embeddings, labels case chunks as direct evidence, keeps
  Azure Search material advisory, and includes the attached case ID and entities
  in the bounded knowledge query. General knowledge is used only when its
  explicit capability setting is enabled.
- The handler-facing seam accepts authenticated identity, native Cosmos/Blob
  dependencies, and a plain prior transcript. Cosmos-backed history tests cover
  ownership isolation, expiry, per-session message limits, per-user session
  pruning, UTF-8 storage bounds, and latest-turn deletion. The integration gate
  also verifies that selected-case retrieval passes the configured case-index
  container into the native `CosmosStore.get_case(container, case_id)` contract.
- Focused offline chat/history/chunk/Search/OpenAI suite: `38 passed`. A full
  Phase 3 integration regression reports `249 passed, 2 skipped`, plus 3
  golden-rubric subtests. The exact runtime-wrapper assertion now includes
  `portal_http`, and the Bicep contract verifies the complete analyzer, embed,
  and portal enable/disable matrix.

## Phase 3 native portal HTTP verification log

- `portal_handler.py` consumes native Azure `HttpRequest` properties and returns
  native `HttpResponse` objects; it contains no API Gateway/Lambda request or
  response envelope. The copied route table, status/error behavior, Pydantic
  response validation, native Cosmos/Blob ports, and synchronous chat semaphore
  remain explicit.
- JWT and Entra app-role modes authenticate before all routes, including
  `/health`, `/ready`, and unsupported methods. Both modes require a stable
  token `sub`; Entra additionally requires the configured role. Chat history
  operations pass that identity into the native ownership boundary and obscure
  cross-user sessions as not found.
- Production responses emit no permissive CORS headers. Request bodies, path
  components, cursor components, integer queries, page sizes, raw-section
  output, question length, and chat-history operations remain bounded.
- The host uses an empty HTTP route prefix and registers one anonymous-trigger
  wildcard `portal_http` wrapper; application authentication remains mandatory.
  `/api/chat` lazy-loads or accepts injection of the separately owned native
  chat service and passes only native application dependencies and a plain
  bounded transcript.
- The Phase 3 integration gate passes Python 3.12 `compileall`, `git diff
  --check`, all 18 root/module Bicep compilations with Bicep CLI 0.45.15, Bash
  syntax checks, PowerShell parser validation, exact OpenAPI/frontend parity,
  and production AWS-shape/secret-bearing-setting scans. Full pytest reports
  `249 passed, 2 skipped`, plus 3 golden-rubric subtests. Live customer Azure
  private-endpoint approval/propagation, direct-origin denial, and authenticated
  Front Door `/ready` acceptance remain blocked on a customer subscription and
  private-network-connected deployment runner.

## Phase 4 operations verification log

- Final local Phase 4 regression reports `273 passed, 2 skipped`, plus 3
  golden-rubric subtests. The skips are the opt-in local emulator cases. All 18
  root/module Bicep files compile, Python compileall passes, and the exact six
  runtime wrappers match every Function App's enable/disable settings and
  deployment-script host enumeration. The unchanged frontend suite reports
  `92 passed`; the production build succeeds with only the inherited bundle-size
  warning, and the production-dependency audit reports no vulnerabilities.
- The Bash and PowerShell staging harnesses default to the non-mutating offline
  contract gate. Live mutation requires an exact dedicated-subscription match
  plus `STAGING_CHAOS_CONFIRMATION=isolated-nonproduction`; generated fixtures
  are synthetic and external Splunk/ServiceNow creation must be disabled.
- The live path covers private storage/origin state, normal intake and report,
  a three-times-cap burst, duplicate delivery, the distinct Blob publication,
  analyzer, and embed five-attempt poison paths, required alert-rule presence,
  authenticated Front Door readiness, and disabled disposition dry run. Poison
  evidence is intentionally retained for the recovery exercise.
- Offline staging selection reports `65 passed, 1 skipped` using an isolated
  Linux Python 3.12 environment, including the mutation-free disposition dry
  run and synchronization behavior cases. Bash syntax, PowerShell parser
  validation, Python compileall, Markdown link resolution, `git diff --check`,
  and credential-pattern scans pass. Live Azure mutation remains for the
  customer staging runner.
- The indexed operations package documents immutable image deployment,
  Anthropic-hosted preview/residency approval, Azure OpenAI, Search ingestion,
  portal synthetic identity, alert thresholds/owners, ServiceNow read-only
  disposition sync, vendor-neutral private intake, explicit replay/rollback,
  normative parity, and the production-readiness decision record.
- Production deployment requires a supplied action group and, for the portal,
  both a nonempty synthetic result name and a fresh successful matching
  `AppAvailabilityResults` row. Live private deployment, alert exercise,
  synthetic token issuance/rotation, three poison paths, managed-identity
  service smoke, and isolated ServiceNow acceptance remain `blocked
  verification` until a customer Azure staging subscription and private runner
  are available.
