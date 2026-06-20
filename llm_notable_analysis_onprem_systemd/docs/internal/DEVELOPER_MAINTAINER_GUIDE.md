# Developer Maintainer Guide

This guide is for engineers changing the on-prem notable analyzer. Operator
settings, install steps, and customer-facing runbooks stay in `docs/operations/`;
this page explains how the code is shaped and where to start when adding a new
capability.

Local dev bootstrap, venv layout, and portal preview workflow:
[`DEVELOPING.md`](../../../DEVELOPING.md).

## Runtime Shape

The default service is a file-drop analyzer:

```text
incoming file (*.json / *.txt)
  -> ingest.discover_files / read_notable_text / normalize_notable
  -> onprem_main.process_notable
  -> local_llm_client.LocalLLMClient (SDK-backed default)
  -> validation / enrichment / optional integrations
  -> markdown report
  -> optional HTML report (html_reports profile)
  -> optional Postgres case archive (analyst_portal profile)
  -> optional Splunk writeback / ServiceNow draft-create (action_gated profile)
  -> processed or quarantine movement
  -> periodic retention (notable-retention.service)
```

Separate long-lived service for the analyst portal:

```text
nginx (443) -> portal_app (127.0.0.1:8080)
  -> case_index / case_store / case_chat
  -> Postgres case archive + derived chunks
```

Systemd entrypoints (installed host):

```text
python -m llm_notable_analysis_onprem_systemd.onprem_service.onprem_main
python -m llm_notable_analysis_onprem_systemd.onprem_service.portal_app
```

Alternate analyzer entrypoint for SDK-free smoke or debugging:

```text
python -m llm_notable_analysis_onprem_systemd.onprem_service.onprem_main_nonsdk
```

Production units use the SDK-backed `onprem_main` path
(`deploy/systemd/notable-analyzer.service`).

## Repository Layout

```text
llm_notable_analysis_onprem_systemd/
  config.env.example          # Analyzer runtime contract template
  config.portal.env.example   # Portal-only env template
  deploy/                     # systemd, nginx, LiteLLM assets
  docs/                       # Operator, testing, internal docs
  frontend/analyst-portal/    # React SPA (built into dist/ on install)
  scripts/                    # install, smoke, RAG setup, preview helpers
  src/llm_notable_analysis_onprem_systemd/
    onprem_service/           # Analyzer + portal Python modules
    soar_playbook/            # Phantom/SOAR template scripts (not imported at runtime)
  tests/
    onprem_service/           # Primary unit + contract tests
    onprem_rag_notable_analysis/
    soar_playbook/
    scripts/
```

Related editable packages installed by dev bootstrap (repo root):

- `onprem-llm-sdk` — shared HTTP/SDK wrapper used by `local_llm_client.py`
- `onprem_rag_notable_analysis` — Postgres/pgvector RAG retrieval and ingest helpers

Run tests from the **repository root** with the shared `.venv` activated. See
[`docs/testing/TESTING.md`](../testing/TESTING.md).

## Code Boundaries

### Orchestration and ingest

- `onprem_main.py` / `onprem_main_nonsdk.py` orchestrate one notable: ingest,
  analysis, optional query execution, optional ServiceNow, report writing,
  optional case archive, movement to processed or quarantine.
- `ingest.py` owns file-drop discovery, size limits, normalization, and atomic
  movement to processed/quarantine.
- `config.py` defines runtime flags, capability profiles, and defaults. Any new
  runtime contract belongs in `Config`, `load_config`, `config.env.example`,
  docs, and tests.

### LLM analysis

- `local_llm_client.py` is the SDK-backed structured analyzer path. It owns
  prompt assembly, RAG context use, structured output validation, repair, and
  LLM calls.
- `local_llm_client_nonsdk.py` mirrors the analyzer path without the shared
  `onprem-llm-sdk` wrapper.
- `openai_transport_nonsdk.py` is the direct OpenAI-compatible HTTP transport
  for tool-call mode: request payloads, headers, timeouts, response parsing, and
  HTTP error translation. The SDK client imports it for tool-call requests.

### Query generation, execution, and enrichment

- `spl_query_generation.py` — SPL generation schema, prompts, merge/validate.
- `spl_query_grounding.py` — SPL-dedicated RAG context wiring.
- `splunk_investigation.py` — read-only Splunk search execution and policy gates.
- `elastic_query_generation.py` — Elasticsearch query generation schema/prompts.
- `elasticsearch_query_grounding.py` — Elasticsearch KB grounding wiring.
- `elasticsearch_investigation.py` — read-only Elasticsearch execution.
- `query_result_enrichment.py` — merges deterministic query results into analysis.
- `query_result_interpretation.py` — optional narrative interpretation contract.

### Integrations, validation, and artifacts

- `servicenow.py` — draft/create adapters and approval extraction.
- `sinks.py` — markdown/HTML/report writes and Splunk writeback transport.
- `markdown_generator.py` / `html_generator.py` — deterministic report renderers.
- `ttp_validator.py` / `verdicts.py` — ATT&CK validation helpers.
- `idempotency.py` — side-effect dedupe for writeback/create paths.
- `retention.py` — filesystem and case retention sweeps.

### Analyst portal and case archive

- `case_archive_flow.py` — analyzer-side archive hook after successful analysis.
- `case_store.py`, `case_db.py`, `case_index.py`, `case_search.py` — Postgres
  persistence, listing, and hybrid retrieval.
- `case_chat.py`, `case_chat_history.py` — archive-backed Q&A synthesis and
  optional session history.
- `portal_app.py`, `portal_api_models.py`, `portal_case_detail_view.py` —
  FastAPI routes and bounded API response shaping.
- `case_archive_notices.py` — operator-visible archive failure notices.

### SOAR templates

- `soar_playbook/phantom_notable_to_analyzer.py` — container-triggered SFTP drop.
- `soar_playbook/phantom_notable_index_to_analyzer.py` — scheduled
  `index=notable` polling pattern.

These are operator-copy templates, not imported by the analyzer service.

Keep adapters thin. External systems should be transport and normalization
layers; workflow and policy decisions should stay in orchestration or validator
code.

## Capability Profiles

Customer-facing optional behavior is usually enabled through
`CAPABILITY_PROFILES` rather than ad hoc env toggles.

Profiles are defined in `config.py` (`_CAPABILITY_PROFILE_FLAGS`) and documented
in [`docs/operations/platform/CAPABILITY_PROFILES.md`](../operations/platform/CAPABILITY_PROFILES.md).

Current shipped profiles:

| Profile | Primary effect |
|---------|----------------|
| `core` | Baseline analyzer (always included) |
| `html_reports` | `HTML_REPORT_ENABLED=true` |
| `rag` | analysis RAG grounding |
| `spl_readonly` | SPL generation + Splunk read-only execution |
| `elastic_readonly` | Elasticsearch generation + read-only execution |
| `ticket_draft` | ServiceNow draft section |
| `action_gated` | Splunk writeback, ServiceNow create, idempotency |
| `analyst_portal` | case archive, portal API, case Q&A |

Individual env vars still exist for tuning and advanced overrides, but new
optional features should prefer a profile flag mapping unless there is a strong
reason not to.

## Tool-Call Structured Output

The on-prem analyzer supports two structured-output modes via
`LLM_STRUCTURED_OUTPUT_MODE`:

- `prompt_json`: conservative default; prompt for JSON, parse, validate, repair.
- `tool_call`: ask the OpenAI-compatible server for function/tool-call shaped
  output, then validate the returned function arguments. If tool-call parsing
  fails for that request, the code falls back to prompt-json behavior.

Tool-call specs are local function schemas, not external executable tools. They
shape the model response and are still validated deterministically before use.

Current tool-call names:

- `analyze_notable`
- `generate_spl_queries`
- `interpret_query_results`

Where they are defined:

- `local_llm_client.py`
- `local_llm_client_nonsdk.py`

The helper functions build OpenAI-compatible function specs:

```text
_analysis_tool_spec()
_spl_tool_spec()
_query_result_interpretation_tool_spec()
```

The direct HTTP transport sends them with:

```text
tools=[tool_spec]
tool_choice={"type": "function", "function": {"name": tool_name}}
```

Then it parses `message.tool_calls[].function.arguments` or legacy
`message.function_call.arguments` from the model response.

Important rule: a tool-call response is still untrusted model output. Always
parse, normalize, validate, and either repair once or degrade explicitly.

## Adding A New Capability

Start with the smallest end-to-end slice:

1. Decide whether the behavior belongs in an existing profile or needs a new
   profile entry in `_CAPABILITY_PROFILE_FLAGS`.
2. Add a runtime flag only if the behavior is optional or risky.
3. Add the flag to `Config`, `load_config`, `config.env.example`, and a runtime
   contract test (`tests/onprem_service/test_config_runtime_contract.py` and/or
   `test_deployment_contract.py` when install/docs assets change).
4. Keep entrypoint changes in `onprem_main.py` / `onprem_main_nonsdk.py` limited
   to orchestration.
5. Put feature logic in a focused helper module when it has parsing, validation,
   external calls, or report rendering.
6. Add deterministic validators before any generated query, writeback, or
   action reaches an external system.
7. Add tests for the happy path, disabled path, malformed input, and expected
   degradation path.
8. Update operator docs only for values or behavior the customer must operate.

Prefer this shape:

```text
normalize input
  -> add grounded context or prompt
  -> generate structured output
  -> parse
  -> validate
  -> optional repair
  -> policy check
  -> optional bounded execution
  -> summarize / report / write back
```

Portal-only features should stay out of `onprem_main` except for explicit archive
hooks (`case_archive_flow.py`) that the analyzer calls after successful analysis.

## Adding Another Tool Call

Use tool calls only when a structured model output contract benefits from
function-shaped output. Do not use them for deterministic decisions.

Implementation checklist:

1. Define a small tool name and schema near the existing `_tool_spec` helpers.
2. Keep the schema narrow: required keys, enum values, simple object or array
   shapes.
3. Add a validator for the returned arguments before downstream use.
4. Add fallback behavior for tool-call parser failures.
5. Add tests for:
   - successful tool-call arguments
   - malformed arguments
   - parser fallback to prompt-json
   - validator rejection
6. Document the operator-facing flag only if operators can enable, disable, or
   tune the behavior.

Do not let the model invent source facts. If a value is not in the alert,
retrieved context, or deterministic query results, the contract should require
`unknown`, omit it, or label it as inference.

## Adding An Integration

Use a thin adapter module for each external system or API surface. Keep these
concerns inside the adapter:

- authentication headers or tokens
- URLs and request construction
- timeouts and retry classification
- external response parsing
- translation into stable internal objects
- typed failure classes or explicit error outcomes

Keep these outside the adapter:

- approval decisions
- policy gates
- workflow branching
- generated query validation
- report wording

Separate read-only retrieval, writeback, and action-taking operations even when
they use the same vendor API.

## Report Rendering

Markdown remains the default operator artifact. HTML dashboard reports are an
optional second artifact controlled by the `html_reports` profile
(`HTML_REPORT_ENABLED`).

- Markdown rendering belongs in `markdown_generator.py`.
- HTML rendering belongs in `html_generator.py`.
- File writes belong in `sinks.py`.
- Runtime report enablement belongs in `onprem_main.py` / `onprem_main_nonsdk.py`.

Keep renderers deterministic: they should consume already-normalized analysis
objects and escape untrusted content before writing output.

## Validation Commands

Primary test guide: [`docs/testing/TESTING.md`](../testing/TESTING.md).

From the repo root with `.venv` activated:

```bash
pytest llm_notable_analysis_onprem_systemd/tests/onprem_service -q
```

Focused suites:

```bash
pytest llm_notable_analysis_onprem_systemd/tests/onprem_rag_notable_analysis -q
pytest llm_notable_analysis_onprem_systemd/tests/soar_playbook -q
```

Legacy unittest entrypoint (also valid):

```bash
PYTHONPATH=llm_notable_analysis_onprem_systemd/src \
python -m unittest discover -s llm_notable_analysis_onprem_systemd/tests/onprem_service -p "test_*.py"
```

Contract tests to run when changing runtime env, profiles, or deployment assets:

- `tests/onprem_service/test_config_runtime_contract.py`
- `tests/onprem_service/test_deployment_contract.py`
- `tests/onprem_service/test_local_llm_client_contract.py`

Noisy warnings during negative-path tests are expected when the test is proving
degraded behavior. The pass/fail signal is the final pytest/unittest result.

For docs-only changes, review links and headings manually. For runtime contract
changes, run the focused tests above and any affected smoke tests listed in
`TESTING.md`.

## What Not To Do

- Do not put business rules inside systemd units, shell installers, or external
  adapters.
- Do not make LLM output authoritative without validation.
- Do not add broad framework layers for a single capability.
- Do not commit secrets, customer data, model weights, wheelhouses, RAG indexes,
  generated production reports, or host-local logs.
- Do not enable risky features by default.

## Related Docs

- [`docs/testing/TESTING.md`](../testing/TESTING.md) — unit, smoke, and integration commands
- [`docs/operations/platform/CAPABILITY_PROFILES.md`](../operations/platform/CAPABILITY_PROFILES.md) — customer profile bundles
- [`docs/technical_specs/feature_enhancements_technical_spec.md`](../technical_specs/feature_enhancements_technical_spec.md) — normative enhancement contracts
- [`docs/integrations/SOAR_PLAYBOOK_PHANTOM.md`](../integrations/SOAR_PLAYBOOK_PHANTOM.md) — container-triggered SOAR template
- [`docs/integrations/SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md`](../integrations/SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md) — notable-index polling template
- [`DEVELOPING.md`](../../../DEVELOPING.md) — shared dev venv and portal preview workflow
