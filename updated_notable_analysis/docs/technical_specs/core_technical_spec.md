# Core Technical Spec

## Status

This document is the normative implementation contract for the current `updated_notable_analysis` core build block.

Current block:

- Diff 2
- shared core contracts
- shared validators and policy models
- shared config and profile contracts
- deterministic tests for the new core package

If wording conflicts with older notes in `updated_notable_analysis/README.md`, this document wins for the active Diff 2 implementation slice.

This document is the self-contained, build-ready specification for the current core slice.

## 1. Purpose

This document defines the first real implementation slice for the new shared notable-analysis core.

Diff 2 exists to establish the canonical contracts and deterministic validation boundary before any AWS or on-prem cutover, before any adapter execution, and before any broad refactor of the existing runtime paths.

Baseline objective:

- create the first `updated_notable_analysis/core/` package
- formalize canonical internal objects for baseline analysis and planned future seams
- formalize profile, bundle, and policy contracts
- add deterministic validators for those objects
- add deterministic tests for the new contracts and validators
- avoid runtime cutover, adapter wiring, or migration of existing implementations in this slice

## 2. Scope

### In scope

- creation of the first shared `core` package
- canonical environment-neutral data contracts for the baseline workflow
- canonical config, profile, and bundle contracts
- deterministic validators for schema and policy-adjacent constraints
- report contract and writeback-draft contract definitions
- read-only investigation request and response contract definitions
- deterministic tests for core contracts and validators

### Out of scope

- moving existing AWS or on-prem code into the new package
- cutting over current imports or runtime entrypoints
- actual `Splunk MCP` execution
- actual `Splunk REST API` execution
- actual `ServiceNow` writeback
- actual vector-store initialization or retrieval execution
- adapter implementations
- deployment-specific config loading
- live network calls
- prompt tuning or major prompt rewrites beyond contract alignment

## 3. Baseline Assumptions

The Diff 2 implementation assumes:

- the current repository remains the operational source of truth during migration
- `updated_notable_analysis` is still a parallel path, not yet the active runtime
- the first useful code move is to stabilize contracts and validators before moving workflow code
- the product remains a bounded notable-analysis system rather than a generic incident-response platform
- `SQLite + FAISS` remains the preferred first retrieval backend, but only the core contract boundary is in scope here
- `Splunk MCP` is the first planned read-only query adapter and `Splunk REST API` is the second, but only the execution contract boundary is in scope here
- `ServiceNow` is the first planned ticketing target, but only the draft and writeback contract boundary is in scope here
- on-prem runtime may later use `LiteLLM -> vLLM -> gemma-4-31B-it`, but runtime wiring is out of scope for this slice

## 4. Baseline Constraints

The Diff 2 implementation must operate within these constraints:

- the shared core must remain environment-neutral
- no AWS or on-prem runtime objects may appear in core contracts
- no customer-name-specific logic may appear in the shared core
- evidence classes must remain explicit and must not collapse into one undifferentiated object
- prompt text must not be the only safety boundary
- any risky capability must be expressible through policy or profile validation rather than hidden flags
- the slice must be small enough to ship and test independently before any cutover work begins
- the new core contracts must be usable by both AWS and on-prem wrappers later without semantic drift

## 5. Coverage Boundary

Diff 2 starts from stable shared-core contracts and ends at deterministic validation plus tests for those contracts.

Diff 2 must produce:

- canonical domain models for the new core
- canonical config and profile models
- deterministic validators
- deterministic test coverage for expected valid and invalid cases

Diff 2 does not yet produce:

- runtime adapter implementations
- deployment wrappers
- network execution
- end-to-end report generation from current runtime entrypoints
- live writeback

## 6. Normative Decisions

### 6.1 Shared core operating unit

The operating unit for Diff 2 is one shared-core contract boundary.

It is:

- the canonical internal model for future workflow code
- not yet the full migrated runtime
- not yet an adapter implementation

### 6.2 Core-first rule

Shared contracts and validators must be implemented before workflow extraction or runtime cutover.

This slice is allowed to define future-seam request and response shapes even when the concrete adapters are not yet implemented.

### 6.3 Environment-neutral rule

All Diff 2 core models and validators must be environment-neutral.

They may not:

- import AWS runtime types
- import on-prem path or service-manager assumptions
- depend on live network configuration

### 6.4 Evidence separation rule

The core model must keep evidence classes explicit:

- `alert_direct`
- `advisory_context`
- `query_result`
- `workflow_reported`
- `operator_declared`

The Diff 2 implementation must not allow these evidence classes to collapse into a single free-form blob.

### 6.5 Profile validation rule

Capability profiles and customer bundles must be represented as first-class shared-core configuration contracts.

Unsupported capability combinations must be detectable through deterministic validation.

### 6.6 Read-only investigation contract rule

Diff 2 must define the request and response contracts for read-only investigation without implementing execution.

The core must be able to express:

- validated query-plan intent
- execution request shape
- normalized query-result evidence shape
- structured denial or validation-failure results

### 6.7 Writeback contract rule

Diff 2 must define the writeback draft and writeback result contracts without implementing any real downstream write.

The first target is `ServiceNow`, but the contract must remain reusable for later ticketing systems.

### 6.8 No-cutover rule

Diff 2 must not:

- change the current active runtime path
- replace current imports
- delete or move the existing implementations

## 7. Canonical Diff 2 Entities

### 7.1 `NormalizedAlert`

The canonical baseline analysis input object used by the shared core.

Required fields:

- `schema_version`
- `source_system`
- `source_type`
- `source_record_ref`
- `received_at`
- `raw_content_type`
- `raw_content`

Optional fields:

- `alert_time`
- `title`
- `severity`
- `finding_id`
- `notable_id`
- `metadata`

### 7.2 `AlertEvidence`

Structured evidence item derived from direct alert facts.

Required fields:

- `evidence_type`
- `label`
- `value`

Rules:

- `evidence_type` for this object must be `alert_direct`
- no advisory or query-result evidence may be stored in this object

### 7.3 `AdvisoryContextSnippet`

The normalized advisory retrieval item used for prompt grounding and citations.

Required fields:

- `source_type`
- `source_id`
- `title`
- `content`
- `provenance_ref`

Optional fields:

- `source_file`
- `section_path`
- `rank`

### 7.4 `InvestigationHypothesis`

Canonical hypothesis object for report and read-only investigation planning.

Required fields:

- `hypothesis_type`
- `hypothesis`
- `evidence_support`
- `evidence_gaps`

Optional fields:

- `best_pivots`

### 7.5 `QueryPlan`

The canonical read-only query-plan object.

Required fields:

- `query_dialect`
- `query_strategy`
- `query_text`
- `purpose`

Optional fields:

- `time_range`
- `max_rows`
- `execution_timeout_seconds`
- `expected_signal`
- `grounding_refs`

Rules:

- initial supported dialect is `spl`
- initial supported strategies are:
  - `resolve_unknown`
  - `check_contradiction`
- policy validation requires explicit `time_range`, `max_rows`, and `execution_timeout_seconds` before query execution

### 7.6 `QueryExecutionRequest`

The normalized execution request passed from core orchestration to a future adapter.

Required fields:

- `query_plan`
- `policy_bundle_name`
- `source_system`

### 7.7 `QueryResultEvidence`

The normalized read-only query-result object returned by a future adapter.

Required fields:

- `evidence_type`
- `query_dialect`
- `query_text`
- `result_summary`
- `raw_result_ref`

Optional fields:

- `rows_returned`
- `execution_time_ms`
- `metadata`

Rules:

- `evidence_type` for this object must be `query_result`

### 7.8 `AnalysisReport`

The canonical report object for baseline analysis and later enriched analysis.

Required fields:

- `schema_version`
- `alert_reconciliation`
- `competing_hypotheses`
- `evidence_sections`
- `ioc_extraction`
- `ttp_analysis`

Optional fields:

- `query_result_section`
- `advisory_context_refs`
- `metadata`

### 7.9 `WritebackDraft`

The normalized pre-write downstream payload.

Required fields:

- `target_system`
- `target_operation`
- `summary`
- `body`

Optional fields:

- `routing_key`
- `external_ref`
- `fields`

Rules:

- Diff 2 must support `servicenow` as a valid `target_system`
- Diff 2 may also support other string values as future-compatible targets

### 7.10 `WritebackResult`

The normalized post-write result contract.

Required fields:

- `status`
- `target_system`

Optional fields:

- `external_id`
- `message`
- `metadata`

### 7.11 `CapabilityProfile`

The named product capability bundle.

Required fields:

- `profile_name`
- `enabled_capabilities`

Optional fields:

- `disabled_capabilities`
- `approval_requirements`

### 7.12 `CustomerBundle`

The operator-selected customer seam bundle.

Required fields:

- `prompt_pack_name`
- `context_bundle_name`
- `query_policy_bundle_name`
- `sink_bundle_name`
- `input_mapping_bundle_name`

### 7.13 `PolicyDecision`

The normalized allow or deny result from a deterministic policy check.

Required fields:

- `allowed`
- `reason_code`

Optional fields:

- `message`
- `metadata`

## 8. Required Enums And Authoritative Values

Diff 2 must define shared enums or equivalent allowlisted constants for:

- evidence types
- hypothesis types
- query dialects
- query strategies
- writeback statuses
- supported capability names
- supported profile names where applicable

Required allowlisted values:

### 8.1 Evidence types

- `alert_direct`
- `advisory_context`
- `query_result`
- `workflow_reported`
- `operator_declared`

### 8.2 Hypothesis types

- `benign`
- `adversary`

### 8.3 Query dialects

- `spl`

### 8.4 Query strategies

- `resolve_unknown`
- `check_contradiction`

### 8.5 Initial capability names

- `notable_analysis`
- `retrieval_grounding`
- `readonly_splunk_investigation`
- `query_result_enriched_analysis`
- `splunk_comment_writeback`
- `ticket_draft_writeback`
- `ticket_create_writeback`

## 9. Config And Profile Contract

### 9.1 `RuntimeConfig`

Diff 2 may define a normalized runtime config contract, but only for shared fields needed by the core.

Allowed fields include:

- `default_profile_name`
- `default_customer_bundle_name`
- `llm_model_name`
- `llm_timeout_seconds`

Diff 2 must not hard-code deployment-specific loading behavior inside this contract.

### 9.2 `CapabilityProfile` validation

Validation must ensure:

- enabled capabilities are known values
- disabled capabilities are known values
- unsupported combinations fail fast
- writeback capabilities require explicit approval configuration

### 9.3 `CustomerBundle` validation

Validation must ensure:

- all required bundle names are present and non-empty
- bundle references are structurally valid strings
- missing bundle names fail fast

### 9.4 `QueryPolicyBundle` contract

Diff 2 must define the shared contract shape for a read-only query policy bundle.

Required fields:

- `allowed_indexes`
- `allowed_commands`
- `denied_commands`
- `max_time_range`
- `max_rows`
- `execution_timeout_seconds`

Optional fields:

- `approval_required`

## 10. Validation Rules

### 10.1 Shared validation model

Diff 2 validators must distinguish:

- schema invalidity
- enum invalidity
- unsupported capability combination
- policy denial

Validation must return structured reasons rather than a single opaque error string where practical.

### 10.2 `NormalizedAlert` validation

Validation must ensure:

- all required fields are present
- required string fields are non-empty
- timestamps are interpretable where required

### 10.3 `AnalysisReport` validation

Validation must ensure:

- required sections exist
- evidence sections use supported evidence classes
- top-level contract shape is stable

### 10.4 `QueryPlan` validation

Validation must ensure:

- only supported query dialects are allowed
- only supported strategies are allowed
- query text is non-empty
- optional numeric execution bounds are non-negative integers when present
- policy-validated execution plans include bounded time range, row limit, and execution timeout values

### 10.5 `WritebackDraft` validation

Validation must ensure:

- target system is present
- target operation is present
- summary and body are non-empty

### 10.6 `CapabilityProfile` validation

Validation must ensure:

- all capability names are supported
- unsupported combinations fail fast
- writeback capabilities are not implicitly enabled without explicit approval requirements

## 11. Package And File Shape

Diff 2 must introduce the first `updated_notable_analysis/core/` structure.

Minimum required files or equivalent modules:

- `updated_notable_analysis/core/__init__.py`
- `updated_notable_analysis/core/models.py`
- `updated_notable_analysis/core/vocabulary.py`
- `updated_notable_analysis/core/validators.py`
- `updated_notable_analysis/core/config_models.py`
- `updated_notable_analysis/core/policy.py`

Minimum required tests or equivalent:

- `updated_notable_analysis/tests/test_models.py`
- `updated_notable_analysis/tests/test_validators.py`
- `updated_notable_analysis/tests/test_config_models.py`
- `updated_notable_analysis/tests/test_policy.py`

Equivalent alternative file breakdown is allowed if:

- the same responsibilities remain present
- the shared core boundary remains explicit
- the technical spec sections can still be mapped directly to implementation

## 12. Test Fixture And Coverage Rules

Diff 2 tests must be deterministic and must not require:

- network
- AWS
- Splunk
- ServiceNow
- vector-store initialization
- local model inference

Required coverage:

- valid baseline core object construction
- invalid required-field handling
- invalid enum handling
- profile validation failure
- query-policy bundle validation failure
- writeback-draft validation failure

## 13. Acceptance Criteria

Diff 2 is complete when:

- the first `updated_notable_analysis/core/` package exists
- canonical domain models for the baseline shared core are implemented
- config, profile, and policy contracts are implemented
- deterministic validators are implemented for the canonical contracts
- unsupported capability combinations fail fast
- the core has no AWS- or on-prem-specific imports
- deterministic tests cover valid and invalid contract cases
- no current runtime code path is cut over or broken by this slice

## 14. Recommended Build Order

1. add shared enums and canonical domain models
2. add config, profile, and policy models
3. add deterministic validators
4. add deterministic tests for valid and invalid cases
5. stop and review before adapter implementations or runtime cutover

## 15. Rollback And Migration Note

Diff 2 is additive.

Rollback is straightforward because:

- no current runtime path is replaced
- no deployment wrapper is cut over
- the new core package can be ignored or removed without changing the existing operational code

## 16. One-Line Summary

Diff 2 creates the first shared `updated_notable_analysis/core/` package by locking canonical contracts, config and profile models, and deterministic validators before any runtime extraction, adapter implementation, or deployment cutover begins.
