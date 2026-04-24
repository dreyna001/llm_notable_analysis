# On-Prem Deployment Technical Spec

## Status

This document is the normative implementation contract for the current on-prem wrapper slice of Diff 4.

If wording conflicts with planning notes, this spec wins for the on-prem implementation block.

## 1. Purpose

Define the smallest production-shaped on-prem wrapper around shared `updated_notable_analysis/core`.

This slice exists to establish deterministic local runtime wiring without changing shared business logic or cutting over legacy runtime paths.

## 2. Scope

### In scope

- create first `updated_notable_analysis/onprem/` package
- provide local file-ingest processor entrypoint
- support direct-file and wrapped-file payload intake
- load and validate normalized alert payloads
- invoke a shared-core runner seam
- serialize canonical `AnalysisReport` output
- write report JSON to configured local directory
- move successful files to `processed/`
- move failed files to `quarantine/` and write an error sidecar
- add deterministic tests for wrapper behavior

### Out of scope

- implementing direct vLLM client orchestration inside on-prem module
- implementing Splunk MCP or Splunk REST adapters
- wiring ServiceNow adapter logic into the on-prem runtime path
- replacing or migrating existing runtime paths

## 3. Baseline Assumptions

- first on-prem runtime shape is local file-drop processing on a Linux host
- on-prem default report sink is local filesystem output
- wrapper should fail closed on malformed config or payload shape
- shared core remains the source of canonical model and policy semantics
- intended later on-prem inference chain remains `notable-analyzer -> LiteLLM -> vLLM -> gemma-4-31B-it`

## 3.1 Locked Runtime Topology For The Next On-Prem Integration Slice

The following runtime assumptions are now locked for the next implementation block:

- the analyzer runs as a long-running `systemd`-managed worker service
- LiteLLM runs as an always-on local proxy service on loopback
- vLLM runs as an always-on local model-serving service on loopback
- the default analyzer call path is LiteLLM first, not direct vLLM calls
- the served model target remains `gemma-4-31B-it`

Default endpoint shape:

- analyzer -> `http://127.0.0.1:4000/v1/chat/completions`
- LiteLLM -> `http://127.0.0.1:8000/v1/chat/completions`

Default service dependency order:

- `vllm.service`
- `litellm.service`
- `notable-analyzer.service`

This topology is locked as an architecture and implementation target. The current runner targets LiteLLM; direct vLLM wiring remains behind the LiteLLM service boundary.

## 4. Required Package and File Shape

Minimum required implementation files:

- `updated_notable_analysis/onprem/__init__.py`
- `updated_notable_analysis/onprem/config.py`
- `updated_notable_analysis/onprem/context_provider.py`
- `updated_notable_analysis/onprem/file_io.py`
- `updated_notable_analysis/onprem/runner.py`
- `updated_notable_analysis/onprem/service.py`
- `updated_notable_analysis/onprem/worker.py`
- `updated_notable_analysis/onprem/config.env.example`
- `updated_notable_analysis/onprem/systemd/notable-analyzer.service.example`

Minimum required test file:

- `updated_notable_analysis/tests/test_onprem_service.py`

## 5. Runtime Config Contract

### 5.1 Required env vars

- `UPDATED_NOTABLE_ONPREM_INCOMING_DIR`
- `UPDATED_NOTABLE_ONPREM_PROCESSED_DIR`
- `UPDATED_NOTABLE_ONPREM_QUARANTINE_DIR`
- `UPDATED_NOTABLE_ONPREM_REPORT_OUTPUT_DIR`

### 5.2 Optional env vars

- `UPDATED_NOTABLE_ONPREM_DEFAULT_PROFILE_NAME`
- `UPDATED_NOTABLE_ONPREM_DEFAULT_CUSTOMER_BUNDLE_NAME`
- `UPDATED_NOTABLE_ONPREM_ADVISORY_CONTEXT_DIR`
- `UPDATED_NOTABLE_ONPREM_LITELLM_BASE_URL`
- `UPDATED_NOTABLE_ONPREM_LITELLM_READINESS_PATH`
- `UPDATED_NOTABLE_ONPREM_READINESS_TIMEOUT_SECONDS`
- `UPDATED_NOTABLE_ONPREM_LITELLM_CHAT_COMPLETIONS_PATH`
- `UPDATED_NOTABLE_ONPREM_LITELLM_MODEL_NAME`
- `UPDATED_NOTABLE_ONPREM_LITELLM_REQUEST_TIMEOUT_SECONDS`
- `UPDATED_NOTABLE_ONPREM_WORKER_IDLE_SLEEP_SECONDS`
- `UPDATED_NOTABLE_ONPREM_WORKER_MAX_FILES_PER_POLL`

The runner slice includes LiteLLM readiness and chat-completions configuration for fail-closed service polling and analysis calls. It does not couple the analyzer directly to vLLM.

### 5.3 Config validation rules

- all required directory paths must be present and non-empty
- optional profile and bundle values must be strings when present
- optional advisory context directory must be a string when present
- LiteLLM base URL must target loopback
- worker interval, batch size, readiness timeout, and LiteLLM request timeout values must be positive integers
- runtime config construction must be keyword-only to avoid positional ABI drift as fields are added

## 6. Input File Contract

### 6.1 Direct file mode

One input file may contain a top-level `NormalizedAlert`-compatible mapping.

### 6.2 Wrapped file mode

One input file may contain:

- `normalized_alert` mapping
- optional `profile_name`
- optional `customer_bundle_name`

### 6.3 Invalid file handling

The processor must quarantine files when:

- JSON is malformed
- top-level payload is not a JSON object mapping
- wrapped `normalized_alert` field is not a mapping
- `NormalizedAlert` validation fails
- injected core runner raises during processing

## 7. Core Runner Seam Contract

The on-prem wrapper must invoke a deployment-injected runner implementing:

- input: `NormalizedAlert`
- optional runtime selections: `profile_name`, `customer_bundle_name`
- output: canonical `AnalysisReport`

The default processor path must fail closed until a real core runner is explicitly injected.

The on-prem LiteLLM core runner must:

- call LiteLLM on loopback as the analyzer-facing endpoint
- treat vLLM as an implementation detail behind LiteLLM
- assemble prompts through shared prompt-pack and customer-bundle seams
- use the configured local advisory context provider when `UPDATED_NOTABLE_ONPREM_ADVISORY_CONTEXT_DIR` is present
- validate model output against the shared `AnalysisReport` contract
- fail closed when LiteLLM requests fail or responses are malformed

## 7.1 Local Advisory Context Provider Contract

The first on-prem advisory context implementation is a deterministic local JSON bridge, not a vector store.

When `UPDATED_NOTABLE_ONPREM_ADVISORY_CONTEXT_DIR` is configured, the provider reads one JSON file per configured context index:

- `<advisory_context_dir>/<index_name>.json`

Each file must be a JSON object with:

- `snippets`: list of advisory snippet objects compatible with `AdvisoryContextSnippet`

Provider rules:

- only files named by the selected `ContextBundle.index_names` are considered
- only snippets whose `source_type` is in `ContextBundle.enabled_context_sources` are returned
- snippets are sorted deterministically by rank, provenance, and source id
- missing index files are treated as empty
- malformed configured files fail closed with `ValueError`
- retrieval limit and context budget enforcement remains owned by shared core context normalization

SQLite + FAISS remains the preferred later retrieval backend, but it is not implemented in this local JSON bridge slice.

## 8. Local File Transport Contract

The on-prem wrapper uses one filesystem JSON transport seam:

- `list_json_files(directory) -> tuple[Path, ...]`
- `read_json_file(path) -> Mapping[str, Any]`
- `write_json_file(path, payload) -> None`
- `move_file(source_path, destination_path) -> Path`

Provide:

- stdlib-backed default transport
- real filesystem tests using temporary directories

## 9. Output Contract

Successful processing result must include:

- `status` (`ok`)
- `input_path`
- `processed_path`
- `report_path`
- `source_record_ref`

Quarantine result must include:

- `status` (`quarantined`)
- `input_path`
- `quarantine_path`
- `error_path`
- `message`

Report filename format:

- `<utc_timestamp>_<sanitized_source_record_ref>.json`

Quarantine sidecar format:

- JSON file beside quarantined input with `status` and `message`

Serialization requirements:

- dataclasses converted to JSON mappings
- enum values serialized by `.value`
- datetimes serialized as UTC ISO-8601 with `Z`

## 10. Test Requirements

Tests must be deterministic and require no live network, systemd, LiteLLM, or vLLM.

Required coverage:

- successful file processing path
- wrapped payload with runtime override fields
- quarantine path for invalid payload
- empty queue no-op behavior
- report output filename normalization behavior
- worker loop idle-sleep behavior
- clean shutdown handling
- LiteLLM endpoint readiness failure
- explicit failure when the analyzer is configured to use a non-loopback local endpoint
- LiteLLM chat-completions endpoint selection
- malformed LiteLLM response handling
- invalid `AnalysisReport` response handling
- local advisory context JSON loading
- local advisory context malformed-file failure

Future runtime-client hardening should add targeted tests for explicit failure when the analyzer is configured to use an unavailable local endpoint.

Static systemd-template coverage must prove:

- analyzer unit depends on `litellm.service`
- analyzer unit does not depend directly on `vllm.service`
- analyzer unit loads `/etc/notable-analyzer/config.env`
- analyzer unit uses a deployment-owned launcher rather than adding a package CLI
- analyzer unit constrains writes to expected local notable paths
- analyzer unit constrains network access to loopback

## 11. Acceptance Criteria

This on-prem slice is complete when:

- on-prem package exists with thin wrapper modules and config example
- wrapper accepts direct and wrapped local alert inputs
- wrapper invokes injected core runner and writes report JSON locally
- successful inputs move to `processed/`
- failed inputs move to `quarantine/` with an explanatory sidecar
- worker loop can poll continuously and sleep between idle polls
- worker fails closed when LiteLLM readiness is unavailable
- analyzer-facing LiteLLM config targets loopback by default
- on-prem LiteLLM core runner targets the configured chat-completions endpoint
- on-prem LiteLLM core runner validates model JSON into `AnalysisReport`
- local JSON advisory context can feed the on-prem runner while preserving provenance
- systemd template captures LiteLLM dependency, stop behavior, local config loading, and hardened runtime scope
- deterministic tests cover happy and representative failure paths
- no deployment-specific behavior leaks into shared `core` contracts

The next implementation slice must additionally prove:

- LiteLLM fronts vLLM on loopback
- the service startup order is documented and enforced by deployment wiring

## 12. Rollback Note

This slice is additive. Existing runtime paths are not modified.

Rollback is straightforward by ignoring or removing the new `updated_notable_analysis/onprem` package.

## 13. One-Line Summary

Diff 4 on-prem establishes a thin local file-drop wrapper with explicit env and file contracts that ingests normalized alerts, calls a deployment-injected shared-core runner, writes canonical report JSON locally, and archives or quarantines source files with deterministic validation and tests.
