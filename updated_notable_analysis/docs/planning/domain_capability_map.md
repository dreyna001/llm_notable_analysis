# Domain Capability Map

## 1. Purpose

This document defines the bigger-picture capability model for the updated notable-analysis domain in this repository.

It exists to keep the system expandable without turning the baseline into a generic incident-response or security-automation platform.

Use this document to answer:

- which workflows belong to the product domain
- which capabilities are baseline vs later
- which capabilities are read-only vs writeback
- which shared services and entities must remain stable
- how the product can expand toward RAG, read-only investigation, and ticketing without refactor churn

Implementation detail:

- `../technical_specs/core_technical_spec.md` is the main normative build spec for the first approved implementation slice in `updated_notable_analysis`
- this document defines both the capability seams and the high-level delivery sequencing that future specs and backlogs should plug into

## 2. Product Model

The product should be treated as **one shared notable-analysis core with multiple bounded capabilities**.

Do not model AWS vs on-prem as separate product capabilities.

Those are deployment paths, not business capabilities.

The baseline product is:

- notable or alert in from an approved upstream handoff
- structured analyst-ready report out
- optional approved enrichment and bounded investigative support around that report

The product is **not**:

- a full incident-response command platform
- a generalized multi-tool autonomous SOC agent
- a replacement for the SIEM, SOAR, ticketing system, or case-management system

## 3. Domain Assumptions

The current design assumes:

- customers already operate one or more upstream alerting or SIEM systems
- upstream systems remain the systems of record for detections, notable creation, event storage, and most investigation history
- downstream ticketing or case-management systems remain the systems of record for work tracking and workflow state
- the product can normalize supported alert or notable payloads into a canonical internal model
- first-pass alert interpretation is the current best-fit baseline capability
- later bounded investigation may use approved read-only query execution against supported SIEM platforms
- organization-specific SOPs, field dictionaries, data dictionaries, and runbooks may improve the analysis, but they are advisory context rather than alert evidence
- customer-specific variation should be handled through profiles, prompt packs, policy bundles, mappings, and adapters rather than customer-name branching in code
- service integrations should use thin adapters and only the API surfaces needed for the workflow
- on-prem runtime paths may use `LiteLLM -> vLLM -> gemma-4-31B-it`, but that is a deployment choice rather than a business capability
- initial retrieval grounding should use the already-proven `SQLite + FAISS` path, but the seam should remain open for later backend variation

## 4. Domain Constraints

The architecture must operate within these constraints:

- direct alert evidence, advisory context, query-result evidence, and inference must remain distinguishable
- read-only, writeback, and any future action-like capabilities must stay separate
- risky capabilities must be off by default and explicitly enabled
- vendor-specific logic must stay at the edges, not in the shared core
- the core must remain portable across AWS and on-prem deployment paths
- future workflows must be added as explicit capabilities, not hidden scope creep in the baseline path
- the LLM must remain bounded and must not become the hidden policy engine
- prompt text must not be the only place where safety rules live
- model output must be treated as untrusted until it passes parsing, schema validation, and policy checks
- environments without `MCP` enabled must still be supportable for read-only Splunk investigation
- incomplete, stale, or low-confidence enterprise data must be expected and handled explicitly

## 5. Stable Domain Concepts

These concepts should remain stable even as capabilities expand:

- `NotableInput`
- `NormalizedAlert`
- `AlertEvidence`
- `AdvisoryContextSnippet`
- `InvestigationHypothesis`
- `QueryPlan`
- `QueryResultEvidence`
- `AnalysisReport`
- `ReportSummary`
- `WritebackDraft`
- `WritebackResult`
- `CapabilityProfile`
- `PolicyDecision`

## 6. Evidence Model

Future workflows should share normalized alert identity and report identity, but keep evidence types explicit.

Recommended evidence types:

- `alert_direct`
- `advisory_context`
- `query_result`
- `workflow_reported`
- `operator_declared`

Rules:

- different evidence types may support the same hypothesis or report section
- different evidence types must not be silently collapsed into one undifferentiated record
- `alert_direct` means facts present in the alert, notable, or supplied raw artifacts
- `advisory_context` means SOPs, KB snippets, Splunk field guidance, runbooks, and similar retrieved guidance
- `query_result` means evidence returned from approved read-only query execution
- later capabilities may correlate evidence types, but they must preserve provenance
- advisory context must never be presented as direct alert evidence unless the alert itself supports the same fact

## 7. Capability Inventory

### Capability 1: Notable Analysis

- capability name: `notable_analysis`
- purpose: produce the baseline structured notable-analysis report from direct alert evidence
- state: active implementation target
- risk class: read-only
- primary inputs: supported notable or alert payloads, prompt pack, contract validators
- primary outputs: normalized alert view, evidence vs inference separation, hypotheses, TTPs, IOCs, and analyst-ready report object
- implementation spec: `../technical_specs/core_technical_spec.md`

### Capability 2: Retrieval Grounding

- capability name: `retrieval_grounding`
- purpose: add customer-approved advisory context such as SOPs, Splunk data dictionary guidance, and environment documentation
- state: active implementation target
- risk class: read-only
- primary inputs: normalized alert, context bundle, retrieval policy, vector or lexical indexes
- primary outputs: advisory context snippets with provenance suitable for prompt grounding and report citations
- critical rule: advisory context is guidance, not alert evidence

### Capability 3: Read-Only Splunk Investigation

- capability name: `readonly_splunk_investigation`
- purpose: generate bounded Splunk query plans, validate them, run approved read-only searches, and normalize the returned evidence
- state: active implementation target
- risk class: read-only
- primary inputs: normalized alert, hypotheses, query policy bundle, Splunk execution adapter
- primary outputs: validated query plans, normalized read-only query results, structured execution metadata
- critical rules:
  - all generated queries must pass deterministic policy validation before execution
  - the first dialect is `SPL`
  - the first execution adapter is `Splunk MCP`
  - the second execution adapter is `Splunk REST API`
  - customer environments without `MCP` must still be supportable

### Capability 4: Query-Result-Enriched Analysis

- capability name: `query_result_enriched_analysis`
- purpose: update or extend the report using normalized query-result evidence from approved read-only investigation
- state: active implementation target
- risk class: read-only
- primary inputs: baseline report state, normalized query-result evidence, prompt pack, validators
- primary outputs: second-pass report refinement, stronger hypothesis support or contradiction, richer next-step guidance
- critical rule: query-result evidence must remain separate from advisory context and direct alert evidence

### Capability 5: Splunk Comment Writeback

- capability name: `splunk_comment_writeback`
- purpose: write a bounded report summary or report body back to Splunk notable comments
- state: implemented in Diff 6
- risk class: writeback
- primary inputs: approved report output, sink bundle, identifier mapping, policy configuration
- primary outputs: bounded notable comment writeback result and audit metadata
- critical rule: endpoint and identifier mapping are deployment-validated and customer-specific

### Capability 6: Ticket Draft Writeback

- capability name: `ticket_draft_writeback`
- purpose: create a draft ticket payload for `ServiceNow` first, while keeping the seam reusable for later ticketing systems
- state: implemented in Diff 6
- risk class: writeback
- primary inputs: approved report output, routing metadata, sink bundle, policy configuration
- primary outputs: structured draft payload plus downstream reference metadata when applicable
- critical rule: draft generation must stay separate from actual downstream ticket creation

### Capability 7: Ticket Create Writeback

- capability name: `ticket_create_writeback`
- purpose: create the actual downstream ticket after policy and approval checks pass
- state: implemented in Diff 6
- risk class: writeback
- primary inputs: approved writeback draft, ticketing adapter, approval state, policy configuration
- primary outputs: created ticket reference, structured writeback result, audit metadata
- critical rule: approval and policy configuration are required before enablement

## 8. Shared Services

These services should be reusable across capabilities:

- ingest and normalization
- input mapping and alert-shape adaptation
- prompt-pack resolution
- structured output parsing and validation
- TTP and content validation
- report rendering
- context retrieval and provenance handling
- read-only query planning and policy validation
- read-only query execution normalization
- sink routing and writeback validation
- policy and approval validation
- audit and logging

Not every capability uses every shared service, but capabilities should compose from this set rather than inventing one-off pipelines.

## 9. Capability Boundaries

Capabilities should remain explicit and separately enabled.

Recommended capability names:

- `notable_analysis`
- `retrieval_grounding`
- `readonly_splunk_investigation`
- `query_result_enriched_analysis`
- `splunk_comment_writeback`
- `ticket_draft_writeback`
- `ticket_create_writeback`

Rules:

- risky capabilities are off by default
- read-only and writeback capabilities must stay distinct
- unsupported capability combinations should fail fast in configuration
- customer-specific variation belongs in supported profiles or bundles, not hidden code paths

## 10. Capability Dependencies

Recommended dependency model:

- `retrieval_grounding` depends on `notable_analysis`
- `readonly_splunk_investigation` depends on `notable_analysis`
- `query_result_enriched_analysis` depends on `readonly_splunk_investigation`
- `splunk_comment_writeback` depends on a producing analysis capability plus policy configuration
- `ticket_draft_writeback` depends on a producing analysis capability plus policy configuration
- `ticket_create_writeback` depends on `ticket_draft_writeback` plus approval configuration

## 11. Deployment Separation

AWS and on-prem are deployment adapters for the same capability set.

They may differ in:

- trigger mechanism
- storage implementation
- config and secrets retrieval
- LLM transport
- runtime packaging
- report sink defaults

They must not differ in:

- canonical schemas
- evidence model
- capability boundaries
- prompt contracts
- output contracts
- policy-gate behavior

Initial deployment expectations:

- on-prem default report output: local filesystem output
- AWS default report output: S3 output

## 12. Expansion Guidance

When adding a new workflow in this domain:

1. define the capability name
2. classify it as read-only or writeback
3. define its evidence sources
4. define its structured output contract
5. define whether it reuses normalized alert and report identity or introduces a new decision unit
6. define approval boundaries if anything writes downstream
7. decide whether it belongs in the current main implementation spec or needs its own capability-specific spec
8. create or update the backlog that will own implementation for that capability

If multiple capabilities are planned in one overall delivery wave:

- build the shared core first
- keep capability boundaries explicit even when multiple capabilities share one main implementation spec
- add later writeback capabilities after the read-only capabilities are proven

## 13. Delivery Sequencing

### Delivery model

- shared-core-first
- implement the current read-only capabilities through bounded phases
- add later writeback capabilities after the shared core and read-only analysis capabilities are stable
- do not blur baseline analysis, retrieval grounding, and query execution into one hidden workflow

### Delivery waves

#### Wave 1: Shared Core + Notable Analysis

Goal:

Deliver the first runnable, production-shaped baseline path for `notable_analysis`.

Includes:

- canonical internal contracts
- report output contracts
- prompt-pack and config shape
- parsing and validation
- report rendering
- deterministic tests

#### Wave 2: Retrieval Grounding

Goal:

Add `retrieval_grounding` on the same shared core.

Includes:

- context bundle shape
- `SQLite + FAISS` initial backend
- provenance-preserving advisory snippet model
- prompt grounding support
- retrieval tests and failure handling

#### Wave 3: Read-Only Splunk Investigation

Goal:

Implement `readonly_splunk_investigation` as a bounded read-only capability.

Includes:

- query plan contract
- query policy validation
- `Splunk MCP` adapter
- `Splunk REST API` adapter
- normalized query-result model
- execution metadata and failure handling

#### Wave 4: Query-Result-Enriched Analysis

Goal:

Use approved query-result evidence to improve the report and hypothesis handling.

Includes:

- second-pass report enrichment
- explicit query-result evidence handling
- grounding and contradiction support

#### Wave 5: Writeback

Goal:

Move from report-only outputs into controlled downstream updates.

Includes:

- `splunk_comment_writeback`
- `ticket_draft_writeback`
- `ticket_create_writeback`
- policy and approval gates
- explicit writeback audit trail

### Shared-core build order

The shared core should be built in this order:

1. canonical entities and enums
2. output contracts
3. profile and bundle config model
4. validators and policy model
5. prompt-pack resolution
6. report rendering and report schema
7. context-provider seam
8. query-plan and query-result contracts
9. read-only execution seam
10. writeback seam
11. runtime adapters

### Runtime path

Recommended runtime order:

1. local shared-core tests first
2. AWS deployment wrapper next
3. on-prem deployment wrapper after that

Reason:

- validates the shared core first
- gives a fast buildable path
- preserves the eventual customer portability target

### Current non-goals

The current delivery path does not aim to:

- replace the SIEM, SOAR, or case-management platform
- automate containment, eradication, or recovery actions
- become a generalized security orchestration engine
- hide customer-specific governance rules inside prompts
- correlate every security platform in the environment from day one

## 14. Recommended Initial Capability Profiles

These are product capability bundles, not deployment modes.

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

## 15. Future-State Horizon

These concepts should stay visible as possible long-term directions, but they are not current capability commitments:

- `multi_siem_readonly_investigation`
  - extend the read-only investigation seam to additional SIEM query dialects and adapters beyond `Splunk`

- `cross_tool_contextual_investigation`
  - correlate alert analysis with evidence from adjacent tools such as EDR, identity, cloud, email, or proxy platforms

- `broader_case_system_writeback`
  - expand the writeback seam beyond `ServiceNow` to additional ticketing or case systems

Future-state SIEM notes to preserve:

- `Microsoft Sentinel`
- `Elastic Security`
- `IBM QRadar`
- `Google SecOps / Chronicle`
- `Sumo Logic Cloud SIEM`
- `Devo`

If one of these directions is ever pursued, it should be defined as its own explicit capability expansion rather than quietly expanding the baseline path.

## 16. One-Line Summary

Build one shared notable-analysis core, keep evidence classes explicit, and add future RAG, read-only investigation, and writeback workflows as named capabilities that reuse stable contracts, policies, and adapters without turning the product into a generic incident-response platform.
