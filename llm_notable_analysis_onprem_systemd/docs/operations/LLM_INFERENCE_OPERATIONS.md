# LLM Inference Operations

This guide helps customers tune the local LLM call path without changing code.
It covers the LiteLLM endpoint, model identifier, structured output mode, token
limits, and timeout behavior.

## What This Controls

The analyzer calls an OpenAI-compatible chat completion endpoint. The default
deployment routes through LiteLLM on loopback, with vLLM behind it. The analyzer
does not own model serving internals; it owns the client contract and prompt
parsing behavior.

## Recommended Starting Posture

- Keep `LLM_API_URL=http://127.0.0.1:4000/v1/chat/completions`.
- Keep `LLM_MODEL_NAME=gemma-4-31B-it` unless the serving stack advertises a
  different model id.
- Use `LLM_STRUCTURED_OUTPUT_MODE=prompt_json` first.
- Increase `LLM_TIMEOUT` only after measuring model startup and inference
  latency. Default is `240` to cover spl_readonly plus query interpretation.
  Core-only deployments may use `120`.
- Keep LiteLLM/vLLM bound to loopback unless a documented authenticated edge
  listener is approved.

## Customer Decisions

### Which endpoint should the analyzer call?

**Settings:** `LLM_API_URL`, `LLM_API_TOKEN`

- Default to loopback LiteLLM for the production systemd chain.
- Use a token only when the local gateway requires one.
- Do not put long-lived tokens in committed files.
- If using a different OpenAI-compatible gateway, verify `/v1/models` and chat
  completion response shape before changing production config.

### Which model name should be sent?

**Setting:** `LLM_MODEL_NAME`

- The value must match the model id advertised by the gateway.
- Keep docs, service units, LiteLLM config, and `config.env` aligned when
  changing model names.
- Treat model swaps as validation events: run representative notables and check
  parse/repair rates.

### Prompt JSON or tool-call output?

**Setting:** `LLM_STRUCTURED_OUTPUT_MODE`

- `prompt_json` is the conservative default: prompt, parse, validate, repair.
- `tool_call` asks the OpenAI-compatible server for function/tool-call shaped
  output and falls back to prompt-json behavior if parsing fails.
- Use `tool_call` only when vLLM/model parser/template settings are confirmed
  for the selected model.

### How large and slow may responses be?

**Settings:** `LLM_MAX_TOKENS`, `LLM_TIMEOUT`

- Keep token limits large enough for the structured report but low enough to
  avoid runaway outputs.
- Increase timeout only when the model needs it under normal load.
- Revisit timeout when enabling RAG, SPL generation, or concurrent processing.

### Should freeform mode be used?

The default analyzer is the structured report path. A separate freeform service
entrypoint exists for lab or fallback use when operators want paragraph output
instead of the structured schema.

- Unit: `notable-analyzer-freeform.service`
- Entrypoint: `python -m llm_notable_analysis_onprem_systemd.onprem_service.freeform_main`
- Output suffix: `*_freeform.md`

Do not run the structured analyzer and freeform analyzer against the same
`INCOMING_DIR` at the same time. Treat freeform as an alternate operating mode,
not a per-file toggle.

## Config Quick Reference

| Area | Primary variables |
|------|-------------------|
| Endpoint | `LLM_API_URL`, `LLM_API_TOKEN` |
| Model | `LLM_MODEL_NAME` |
| Output contract | `LLM_STRUCTURED_OUTPUT_MODE` |
| Bounds | `LLM_MAX_TOKENS`, `LLM_TIMEOUT` |
| Alternate report mode | `notable-analyzer-freeform.service` systemd unit |

## Validation And Rollout

1. Confirm the endpoint responds locally:
   `curl -sS http://127.0.0.1:4000/v1/models`.
2. Run the service-chain smoke test after services are started:
   `sudo bash scripts/smoke_service_chain.sh --config-env /etc/notable-analyzer/config.env`.
3. Process representative JSON and text notables.
4. Review parse/repair metadata, report completeness, and latency.
5. Change one inference setting at a time between validation runs.

## Related Docs

- [`INSTALL.md`](INSTALL.md)
- [`OFFLINE_PRESTAGE_GUIDE.md`](OFFLINE_PRESTAGE_GUIDE.md)
- [`RAG_OPERATIONS.md`](RAG_OPERATIONS.md)

