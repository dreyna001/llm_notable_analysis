# Implementation Tracker

Single place to record **what is done** vs **what is left** for `updated_notable_analysis`. Update it when scope changes, a planning artifact is approved, or an implementation diff lands.

## Authority (what wins if something disagrees)

1. `../technical_specs/core_technical_spec.md` — build contract for the current implementation slice.
2. `domain_capability_map.md` — product capability boundaries, sequencing, and non-goals.
3. `../architecture/core_deployment_architecture.md` — shared-core vs deployment boundary.
4. `../../README.md` — planning overview and decisions already locked for the new path.

## Status Legend

- `[ ]` Not started
- `[~]` In progress
- `[x]` Done

## Current Focus

| Item | Status | Notes |
|------|--------|-------|
| Planning root established | [x] | `updated_notable_analysis/README.md` created and used as planning entrypoint |
| Capability model locked | [x] | `planning/domain_capability_map.md` created |
| Core boundary locked | [x] | `architecture/core_deployment_architecture.md` created |
| First build-ready core spec locked | [x] | `technical_specs/core_technical_spec.md` created |
| Shared core implementation (`Diff 2`) | [x] | Core contracts, policy model, validators, and deterministic tests are in place |
| Prompt and context seams (`Diff 3`) | [x] | Prompt-pack and context-bundle seams implemented with deterministic tests |

## Decisions Locked So Far

| Decision | Status | Notes |
|----------|--------|-------|
| Product model is one shared notable-analysis core | [x] | AWS and on-prem are deployment paths, not product capabilities |
| First ticketing target is `ServiceNow` | [x] | Contract should still stay reusable for later systems |
| On-prem default report sink is local filesystem output | [x] | Deployment-specific default |
| AWS default report sink is S3 output | [x] | Deployment-specific default |
| First read-only query adapter is `Splunk MCP` | [x] | Backend-agnostic seam still required |
| Second read-only query adapter is `Splunk REST API` | [x] | Required for non-MCP environments |
| Preferred first retrieval backend is `SQLite + FAISS` | [x] | Seam remains open for later backends |
| On-prem runtime target is `LiteLLM -> vLLM -> gemma-4-31B-it` | [x] | Deployment choice, not business capability |
| On-prem analyzer runtime is a long-running `systemd` worker | [x] | Locked next-step runtime shape around the reusable local processor |
| On-prem analyzer targets LiteLLM on loopback by default | [x] | Default analyzer-facing endpoint is `127.0.0.1:4000`, not direct vLLM calls |
| LiteLLM fronts vLLM on loopback for on-prem | [x] | Default dependency chain is `notable-analyzer -> LiteLLM -> vLLM` |

## Phase A — Planning Stack

| Item | Status | Notes |
|------|--------|-------|
| `updated_notable_analysis/README.md` | [x] | Planning entrypoint updated to reflect active additive implementation slices |
| `docs/README.md` | [x] | Docs navigation index created |
| `planning/domain_capability_map.md` | [x] | Capability inventory, delivery waves, future-state horizon |
| `architecture/core_deployment_architecture.md` | [x] | Shared-core boundary and adapter seams |
| `technical_specs/core_technical_spec.md` | [x] | Diff 2 build-ready contract |
| `planning/implementation_tracker.md` | [x] | This tracker |

Phase gate:

- planning stack exists
- capability, architecture, and first implementation slice are documented
- no runtime cutover has occurred yet

## Phase B — Shared Core Implementation (`Diff 2`)

| Block | Status | Notes |
|-------|--------|-------|
| `core/` package creation | [x] | Shared core package exists under `updated_notable_analysis/core/` |
| Canonical domain models | [x] | `NormalizedAlert`, `AnalysisReport`, `QueryPlan`, `WritebackDraft`, and related models implemented |
| Shared enums and vocabulary | [x] | Evidence classes, query dialects, query strategies, and capability names are defined |
| Config/profile models | [x] | `CapabilityProfile`, `CustomerBundle`, `QueryPolicyBundle`, shared runtime config contract implemented |
| Deterministic validators | [x] | Schema, enum, capability-combination, and policy validation implemented |
| Deterministic tests | [x] | Deterministic `unittest` suite added with no network and no runtime cutover |

Phase gate:

- `core/` package exists
- validators and tests pass
- no AWS or on-prem imports appear in the shared core
- no active runtime path is changed

## Phase C — Prompt And Context Seams

| Block | Status | Notes |
|-------|--------|-------|
| Prompt-pack contract wiring | [x] | `core/prompting` contract, resolver, and assembly modules added |
| Context-provider contract wiring | [x] | `core/context` bundle model and provider seam added |
| Bundle validation hardening | [x] | Fail-fast prompt/context bundle resolution with deterministic tests |

## Phase D — Deployment Wrappers

| Block | Status | Notes |
|-------|--------|-------|
| AWS wrapper path | [x] | Lambda wrapper, S3 transport seam, config contract, and deterministic tests landed under `updated_notable_analysis/aws/` |
| On-prem wrapper path | [x] | Local file-ingest wrapper, archive/quarantine behavior, LiteLLM runner seam, local JSON advisory context provider, config contract, and deterministic tests landed under `updated_notable_analysis/onprem/` |
| Portable proof | [x] | Both deployment wrappers accept canonical alert payloads and emit canonical report JSON to target-specific sinks |

## Phase E — Read-Only Investigation

| Block | Status | Notes |
|-------|--------|-------|
| Query-plan contract usage | [x] | Policy-gated read-only executor seam and investigation result contract landed |
| `Splunk MCP` adapter | [x] | Injected MCP client adapter normalizes bounded SPL results into query evidence |
| `Splunk REST API` adapter | [x] | Injected REST transport adapter builds bounded oneshot SPL requests and normalizes query evidence |
| Query-result-enriched analysis | [x] | Deterministic report enrichment appends query-result evidence and hypothesis support/contradiction annotations |

## Phase F — Writeback

| Block | Status | Notes |
|-------|--------|-------|
| Splunk comment writeback | [x] | Approval-gated bounded notable comment adapter with injected Splunk transport |
| `ServiceNow` draft writeback | [x] | Draft-only ServiceNow incident payload builder with bounded summary/body fields |
| `ServiceNow` create writeback | [x] | Approval-gated ServiceNow incident create adapter with injected transport |

## Deferred / Future-State Notes

| Item | Status | Notes |
|------|--------|-------|
| Additional vector-store backends | [ ] | Seam should support later backends beyond `SQLite + FAISS` |
| Additional SIEM adapters | [ ] | `Microsoft Sentinel`, `Elastic Security`, `IBM QRadar`, `Google SecOps / Chronicle`, `Sumo Logic Cloud SIEM`, `Devo` |
| Broader ticketing adapters | [ ] | After `ServiceNow` path is proven |
| Cross-tool contextual investigation | [ ] | Later explicit capability expansion, not baseline scope |

## Current Non-Goals

The current delivery path does not aim to:

- replace the SIEM, SOAR, or case-management system
- automate containment, eradication, or recovery actions
- become a generalized orchestration platform
- broaden into every security-tool integration in the first implementation wave

## Changelog

| Date | Change |
|------|--------|
| 2026-04-21 | Tracker created for `updated_notable_analysis`; planning stack established through core technical spec. |
| 2026-04-21 | Diff 2 status updated to done after shared core contracts, validators, and tests landed. |
| 2026-04-21 | Diff 3 prompt/context seam slice landed with prompt-pack and context-bundle contract coverage. |
| 2026-04-24 | Diff 4 AWS slice landed: Lambda wrapper, AWS config contract, S3 JSON transport seam, and deterministic wrapper tests. |
| 2026-04-24 | Diff 4 on-prem slice landed: local file-ingest wrapper, filesystem transport seam, archive/quarantine behavior, and deterministic wrapper tests. |
| 2026-04-24 | On-prem runtime contract locked further: long-running `systemd` worker, analyzer -> LiteLLM -> vLLM service chain, and loopback endpoint topology documented. |
| 2026-04-24 | On-prem runtime expanded with LiteLLM core runner seam and deterministic local JSON advisory context provider; SQLite + FAISS remains a later retrieval backend. |
| 2026-04-24 | Diff 5 read-only investigation started with policy-gated executor seam, normalized result contract, and deterministic guardrail coverage. |
| 2026-04-24 | Diff 5 Splunk MCP read-only adapter landed with injected MCP client seam, bounded payload construction, and normalized query-result evidence tests. |
| 2026-04-24 | Diff 5 Splunk REST API read-only adapter landed with injected transport seam, bounded oneshot payload construction, and non-MCP deterministic coverage. |
| 2026-04-24 | Diff 5 query-result-enriched analysis landed with deterministic report refinement, explicit query evidence sections, and hypothesis support/contradiction annotations. |
| 2026-04-24 | Diff 6 Splunk comment writeback landed with explicit runtime approval gate, bounded comment validation, and normalized writeback results. |
| 2026-04-24 | Diff 6 ServiceNow draft writeback landed with draft-only incident payload construction, routing metadata, and bounded summary/body validation. |
| 2026-04-24 | Diff 6 ServiceNow create writeback landed with approval-gated incident creation, injected transport seam, and normalized audit metadata. |
