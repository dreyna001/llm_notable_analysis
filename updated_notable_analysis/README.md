# Updated Notable Analysis Plan

## Status

This directory is **planning-first with active additive implementation slices** for the next-generation notable-analysis layout.

The current source of truth for production behavior still remains the existing implementations elsewhere in this repository.

The new `updated_notable_analysis` path now contains:

- planning artifacts
- shared core contracts and validators
- AWS wrapper slice
- on-prem wrapper slice

Nothing in the current on-prem, analyzer-image, AWS, SDK, or RAG paths has been cut over or replaced by this path yet.

## Goal

Create a new `updated_notable_analysis` workspace inside this repository that preserves the current codebase while defining a cleaner long-term shape:

- one shared `core`
- one `aws` implementation around that core
- one `onprem` implementation around that core
- explicit capability and profile seams for customer variation
- a path to add RAG, read-only Splunk investigation, and ticketing without heavy abstraction

## Use Case

This product remains a **bounded notable-analysis workflow**, not a generic incident-response platform.

Primary purpose:

- receive a notable or alert from an approved upstream handoff
- produce a structured analyst-ready report
- optionally enrich that report with approved advisory context
- optionally test bounded hypotheses through approved read-only Splunk queries
- optionally write approved outputs to Splunk comments or a ticketing system

## Scope Contract

### In scope

- define the target capability shape
- define the target configuration and profile shape
- define the directory shape for `core`, `aws`, and `onprem`
- define the smallest first refactor that begins the migration safely
- keep customer seams explicit for prompts, retrieval, query policy, mappings, and sinks

### Out of scope for this planning block

- moving current code into the new directory
- deleting or rewriting current implementations
- implementing vector DB storage
- implementing Splunk MCP execution
- implementing ServiceNow or other ticket creation
- designing a generic plugin framework

### Assumptions

- current repo behavior and outputs should remain available during migration
- future customer variation should be supported through profiles, prompt packs, policy bundles, and adapters
- risky capabilities must stay off by default
- read-only retrieval, writeback, and action-like behaviors must remain separate
- `ServiceNow` is the first ticketing target for the new path
- on-prem default report output is local filesystem output
- AWS default report output is S3 output
- on-prem runtime should use an always-on `systemd` service topology of `notable-analyzer -> LiteLLM -> vLLM -> gemma-4-31B-it`

### Risks and unknowns

- the current repo has duplicated runtime logic across multiple deployment paths
- prompt, parsing, validation, and reporting logic are not yet centered in one shared core
- profile and customer-seam validation do not yet exist as a first-class config layer
- the first external systems are now known, but the shared seams still need to stay backend-friendly enough for later customer variation

## Design Rules

- keep the implementation boring and readable
- prefer plain modules and dataclasses over framework-style abstractions
- use thin adapters for external systems
- keep policy logic out of adapters
- keep deployment-specific logic out of the shared core
- keep customer-specific behavior out of workflow branches
- make capabilities explicit instead of hiding them behind unrelated flags

## Target Directory Shape

Planned long-term shape:

```text
updated_notable_analysis/
  README.md
  docs/
    planning/
    architecture/
    technical_specs/
  core/
  aws/
  onprem/
  profiles/
  prompt_packs/
```

Initial intent for each top-level area:

- `docs/planning/`
  capability map, sequencing, and implementation tracker
- `docs/architecture/`
  shared-core, AWS, and on-prem runtime-shape docs
- `docs/technical_specs/`
  build-ready implementation specs for each approved diff
- `core/`
  contracts, validators, prompt assembly, report generation, policy gates, orchestration helpers
- `aws/`
  AWS-specific entrypoints, adapters, secrets/config wiring, runtime packaging
- `onprem/`
  on-prem-specific entrypoints, long-running file-drop worker behavior, LiteLLM runner seam, local advisory context bridge, service wiring, runtime packaging
- `profiles/`
  named capability bundles plus customer policy/config bundles
- `prompt_packs/`
  prompt variants that still target stable output contracts

## Capability Shape

Capabilities are product capabilities, not deployment modes.

### Capability 1: `notable_analysis`

- risk class: read-only
- default: enabled
- purpose: produce the baseline structured notable-analysis report from direct alert evidence
- outputs: normalized alert view, evidence/inference separation, hypotheses, TTPs, IOCs, report object

### Capability 2: `retrieval_grounding`

- risk class: read-only
- default: disabled
- purpose: add advisory context from customer-approved knowledge sources such as SOPs, Splunk data dictionary material, and environment guidance
- dependency: `notable_analysis`
- critical rule: advisory context must never be presented as direct alert evidence

### Capability 3: `readonly_splunk_investigation`

- risk class: read-only
- default: disabled
- purpose: generate bounded query plans, validate them, run approved read-only SPL, and normalize the returned evidence
- dependency: `notable_analysis`
- critical rule: all generated queries must pass deterministic policy validation before execution
- implementation note: the first investigation dialect is `SPL`, but the shared execution seam should leave room for later SIEM-specific read-only query adapters

### Capability 4: `query_result_enriched_analysis`

- risk class: read-only
- default: disabled
- purpose: update or extend the report using normalized query results from approved read-only investigation
- dependency: `readonly_splunk_investigation`
- critical rule: query results become a separate evidence class from advisory context

### Capability 5: `splunk_comment_writeback`

- risk class: writeback
- default: disabled
- purpose: write the generated report or a bounded summary back to Splunk notable comments
- dependency: `notable_analysis`
- critical rule: endpoint and identifier mapping are deployment-validated and customer-specific

### Capability 6: `ticket_draft_writeback`

- risk class: writeback
- default: disabled
- purpose: create a draft ticket payload for `ServiceNow` first, while keeping the seam reusable for later ticketing targets without committing the final state change
- dependency: `notable_analysis`

### Capability 7: `ticket_create_writeback`

- risk class: writeback
- default: disabled
- purpose: create the actual downstream ticket after policy and approval checks pass
- dependency: `ticket_draft_writeback`
- critical rule: approval and policy configuration are required before enablement

## Supported Initial Capability Profiles

Profiles are named bundles, not customer names.

- `analysis_only`
  - enables `notable_analysis`

- `analysis_plus_rag`
  - enables `notable_analysis`
  - enables `retrieval_grounding`

- `analysis_plus_readonly_spl`
  - enables `notable_analysis`
  - enables `readonly_splunk_investigation`
  - optionally enables `query_result_enriched_analysis`

- `analysis_plus_ticket_draft`
  - enables `notable_analysis`
  - enables `ticket_draft_writeback`

- `analysis_plus_rag_and_readonly_spl`
  - enables `notable_analysis`
  - enables `retrieval_grounding`
  - enables `readonly_splunk_investigation`
  - optionally enables `query_result_enriched_analysis`

## Config Shape

Configuration should be split into a few explicit layers rather than one large environment blob.

### 1. Runtime config

Deployment and transport details:

- input mode
- paths or buckets
- worker loop interval
- concurrency
- timeout values
- LLM endpoint and model selection
- local loopback service URLs and ports
- service readiness and health expectations
- secrets references
- on-prem runtime chain: `notable-analyzer -> LiteLLM -> vLLM -> gemma-4-31B-it`

### 2. Capability profile config

Operator-facing selection of enabled product behavior:

- profile name
- enabled capabilities
- disabled capabilities
- approval requirements

### 3. Customer bundle config

Stable customer seams:

- prompt pack name
- context bundle name
- query policy bundle name
- sink bundle name
- input mapping bundle name

### 4. Prompt pack config

Prompt customization without changing workflow code:

- analysis prompt version
- report tone
- required report sections
- allowed optional sections
- customer-specific instructions that still preserve the output contract

### 5. Context bundle config

Advisory retrieval settings:

- enabled context sources
- vector DB backend selection
- index or collection names
- retrieval limits
- context budget
- provenance requirements
- preferred initial backend: `SQLite + FAISS`

### 6. Query policy config

Read-only investigation guardrails:

- allowed indexes
- allowed commands
- denied commands
- time range bounds
- row or result limits
- execution timeout
- validated query plans must carry explicit time range, row limit, and execution timeout bounds
- approval requirement
- preferred execution adapters:
  - first: `Splunk MCP`
  - second: `Splunk REST API`
- design constraint: customers without `MCP` enabled must still be supportable through a non-MCP execution path

### 7. Sink bundle config

Writeback selection and routing:

- filesystem output
- S3 output
- Splunk notable comment target
- ticketing target
- draft-only vs create-enabled behavior

Initial deployment intent:

- on-prem default sink bundle:
  - local report output
  - `ServiceNow` draft or create target as enabled by policy
- AWS default sink bundle:
  - S3 report output
  - `ServiceNow` draft or create target as enabled by policy

## Preferred Core Seams

Keep the number of seams small.

### `ContextProvider`

Returns normalized advisory context snippets from SOPs, Splunk field documentation, and customer knowledge sources.

### `ReadOnlyQueryExecutor`

Executes validated read-only queries and returns normalized results.

Initial adapter direction:

- keep the seam backend-agnostic
- make `Splunk MCP` the first adapter
- make `Splunk REST API` the second adapter
- require the core to support environments where `MCP` is unavailable or disabled
- allow later adapters such as `Splunk SDK`

Future-state SIEM notes to preserve in planning:

- `Microsoft Sentinel`
- `Elastic Security`
- `IBM QRadar`
- `Google SecOps / Chronicle`
- `Sumo Logic Cloud SIEM`
- `Devo`

These do not need first-wave implementation, but the shared core should avoid hard-coding the assumption that all read-only investigation will always be `Splunk` plus `MCP`.

### `WritebackAdapter`

Per-system writeback boundary for Splunk comments and ticketing systems.

### `PromptPack`

Provides customer-specific prompt text and guidance while still targeting stable contracts.

## Smallest First Refactor

### Diff 1 objective

Stand up the new planning and shared-core shape without moving or breaking current runtime code.

### Diff 1 exact files to touch

- `updated_notable_analysis/README.md`
- `updated_notable_analysis/docs/planning/domain_capability_map.md`
- `updated_notable_analysis/docs/architecture/core_deployment_architecture.md`
- `updated_notable_analysis/docs/technical_specs/core_technical_spec.md`

### Diff 1 exact behavior

- document the target capability model
- document the shared-core boundary
- document the first build-ready technical spec
- do **not** move current runtime code yet
- do **not** cut over imports yet

### Diff 1 acceptance criteria

- the new directory exists and clearly states that it is planning-only
- capability names, dependencies, and risk classes are explicit
- config/profile layers are explicit
- the first implementation slice is narrow enough to build without broad refactor churn

### Diff 1 rollback note

No runtime rollback needed because Diff 1 is planning-only.

## Planned Follow-On Diffs

### Diff 2: shared core contracts and validators

Objective:

- create the first real `core` package with shared contracts, validators, and report schema

Planned files:

- `updated_notable_analysis/core/contracts/*`
- `updated_notable_analysis/core/validators/*`
- `updated_notable_analysis/core/reporting/*`
- tests under `updated_notable_analysis/tests/`

Acceptance target:

- current output contracts are represented in one shared location
- no deployment-specific code is inside the shared core

### Diff 3: prompt and context seams

Objective:

- move prompt assembly and advisory-context ingestion behind stable seams

Planned files:

- `updated_notable_analysis/core/prompting/*`
- `updated_notable_analysis/core/context/*`
- `updated_notable_analysis/prompt_packs/*`
- `updated_notable_analysis/profiles/*`

Acceptance target:

- customer-specific prompt variation no longer requires workflow branching
- advisory context remains separate from evidence

### Diff 4: AWS and on-prem wrappers around the core

Objective:

- create clean `aws` and `onprem` runtime wrappers that call the shared core

Planned files:

- `updated_notable_analysis/aws/*`
- `updated_notable_analysis/onprem/*`

Acceptance target:

- AWS and on-prem differ only in transport, runtime wiring, and deployment concerns

### Diff 5: read-only Splunk investigation

Objective:

- add a policy-gated read-only query path with normalized results

Acceptance target:

- queries are generated under a strict contract
- deterministic policy validation runs before execution
- normalized results can feed a second analysis step

### Diff 6: writeback adapters

Objective:

- add bounded Splunk writeback, ServiceNow draft ticketing, and approval-gated ServiceNow create

Acceptance target:

- writeback remains separate from read-only analysis
- approval requirements are explicit
- ServiceNow create consumes an approved draft and returns normalized audit metadata

## Non-Functional Acceptance Criteria For The Migration

- preserve existing code while the new path is built
- keep diffs small and reviewable
- avoid new third-party dependencies unless explicitly approved
- keep customer variation in bundles, not code forks
- prefer deterministic validation and policy checks around any risky capability

## Resolved Decisions Before Diff 2

- `ServiceNow` is the first planned ticketing target
- report output defaults should be:
  - on-prem: local filesystem output
  - AWS: S3 output
- the query-execution seam should stay backend-agnostic
- the first planned query adapter is `Splunk MCP`
- the second planned query adapter is `Splunk REST API`
- the design must support customer environments where `MCP` is not available
- the preferred first vector backend is `SQLite + FAISS`
- the on-prem runtime contract should use `notable-analyzer -> LiteLLM -> vLLM -> gemma-4-31B-it`
- the on-prem analyzer should run as a long-running `systemd` worker
- the analyzer-facing default local endpoint should be LiteLLM on loopback rather than direct vLLM calls

## One-Line Summary

Build `updated_notable_analysis` as a new planning-first path with one shared core, thin AWS and on-prem wrappers, explicit capabilities, validated customer profiles, and small migration diffs that preserve the current codebase while enabling future RAG, read-only Splunk investigation, and ticketing.
