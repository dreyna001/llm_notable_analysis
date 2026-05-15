# Developer Maintainer Guide

This guide is for engineers changing the on-prem notable analyzer. Operator
settings, install steps, and customer-facing runbooks stay in `docs/operations/`;
this page explains how the code is shaped and where to start when adding a new
capability.

## Runtime Shape

The default service is a file-drop analyzer:

```text
incoming file
  -> onprem_main.process_notable
  -> local_llm_client.LocalLLMClient
  -> validation / enrichment / optional integrations
  -> markdown report
  -> optional HTML report
  -> processed or quarantine movement
```

The systemd entrypoint is:

```text
python -m llm_notable_analysis_onprem_systemd.onprem_service.onprem_main
```

The main package lives under `src/llm_notable_analysis_onprem_systemd/`.
Tests live under `tests/onprem_service/` and should import package paths with
`PYTHONPATH=llm_notable_analysis_onprem_systemd/src` when running from the repo
root.

## Code Boundaries

- `onprem_main.py` orchestrates one notable: ingest, analysis, optional query
  execution, optional ServiceNow, report writing, movement to processed or
  quarantine.
- `local_llm_client.py` is the SDK-backed structured analyzer path. It owns
  prompt assembly, RAG context use, structured output validation, repair, and
  LLM calls.
- `local_llm_client_nonsdk.py` mirrors the analyzer path without the shared
  `onprem-llm-sdk` wrapper.
- `openai_transport_nonsdk.py` is the direct OpenAI-compatible HTTP transport:
  request payloads, headers, timeouts, response parsing, and HTTP error
  translation.
- `spl_query_generation.py`, `splunk_investigation.py`, `servicenow.py`,
  `markdown_generator.py`, and `html_generator.py` keep feature-specific logic
  out of the entrypoint.
- `config.py` defines runtime flags and defaults. Any new runtime contract
  belongs in `Config`, `load_config`, `config.env.example`, docs, and tests.

Keep adapters thin. External systems should be transport and normalization
layers; workflow and policy decisions should stay in orchestration or validator
code.

## Tool-Call Structured Output

The on-prem analyzer supports two structured-output modes:

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

1. Add a runtime flag only if the behavior is optional or risky.
2. Add the flag to `Config`, `load_config`, `config.env.example`, and a runtime
   contract test.
3. Keep entrypoint changes in `onprem_main.py` limited to orchestration.
4. Put feature logic in a focused helper module when it has parsing, validation,
   external calls, or report rendering.
5. Add deterministic validators before any generated query, writeback, or
   action reaches an external system.
6. Add tests for the happy path, disabled path, malformed input, and expected
   degradation path.
7. Update operator docs only for values or behavior the customer must operate.

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
optional second artifact controlled by `HTML_REPORT_ENABLED`.

- Markdown rendering belongs in `markdown_generator.py`.
- HTML rendering belongs in `html_generator.py`.
- File writes belong in `sinks.py`.
- Runtime report enablement belongs in `onprem_main.py` / `onprem_main_nonsdk.py`.

Keep renderers deterministic: they should consume already-normalized analysis
objects and escape untrusted content before writing output.

## Validation Commands

Run focused on-prem tests from the repo root:

```bash
PYTHONPATH=llm_notable_analysis_onprem_systemd/src \
python -m unittest discover -s llm_notable_analysis_onprem_systemd/tests/onprem_service
```

Noisy warnings during negative-path tests are expected when the test is proving
degraded behavior. The pass/fail signal is the final unittest result.

For docs-only changes, review links and headings manually. For runtime contract
changes, run the focused tests above and any affected smoke tests.

## What Not To Do

- Do not put business rules inside systemd units, shell installers, or external
  adapters.
- Do not make LLM output authoritative without validation.
- Do not add broad framework layers for a single capability.
- Do not commit secrets, customer data, model weights, wheelhouses, RAG indexes,
  generated production reports, or host-local logs.
- Do not enable risky features by default.
