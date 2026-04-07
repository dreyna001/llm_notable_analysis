# Dockerized On-Prem Notable Analyzer (GPU vLLM + gpt-oss-120b)

This directory is a reference Docker bundle for on-prem deployments that run:

- `analyzer`: the generic Python notable analyzer worker image (`notable-analyzer-service`)
- `model-serving`: GPU-backed vLLM OpenAI-compatible server for `gpt-oss-120b`

The analyzer image remains backend-agnostic. Inference behavior comes from this
bundle's `model-serving` service definition and your runtime config values.

## Scope

- Uses the shared analyzer image build target in
  `../llm_notable_analysis_analyzer_image/`.
- Uses host-mounted model artifacts under `./models` (model files are not baked
  into either container image).
- Supports connected-host and air-gapped workflows via `compose.yaml` and
  `compose.airgap.yaml`.

## Host model layout

The default model directory convention is:

```text
models/gpt-oss-120b/
  config.json
  ...model shard/tokenizer files...
```

`config.json` must be present before startup. Set `.env` keys if you use a
different model directory or served model name.

## Key files

- `compose.yaml`: two-service stack with local analyzer image build and GPU vLLM
  runtime
- `compose.airgap.yaml`: image-only variant for registry/tarball workflows
- `.env.example`: Compose substitution values (`VLLM_*`, GPU runtime knobs,
  UID/GID)
- `config/config.env.example`: analyzer runtime env defaults
- `../llm_notable_analysis_analyzer_image/Dockerfile.analyzer`: shared analyzer image build definition
- `systemd/notable-analyzer-stack.service`: optional host unit wrapper
- `docs/deployment.md`: operator deployment runbook
- `docs/true-no-lapse-rollout.md`: blue/green runbook for true no-lapse updates

## Manual edits per deployment

- `.env`
  - copy from `.env.example`
  - set `CONTAINER_UID` and `CONTAINER_GID` to match host ownership requirements
  - verify `VLLM_MODEL_DIRNAME` and `VLLM_SERVED_MODEL_NAME`
  - tune `VLLM_GPU_MEMORY_UTILIZATION` and other `VLLM_*` values as needed
- `config/config.env`
  - copy from `config/config.env.example`
  - keep `LLM_API_URL=http://model-serving:8000/v1/chat/completions` unless
    intentionally changing service names/ports
  - keep `LLM_MODEL_NAME` aligned with `VLLM_SERVED_MODEL_NAME`
  - set Splunk values only if writeback is enabled
- host runtime files
  - stage model artifacts under `models/`
  - create required `data/` and `config/` directories

## Security and operations notes

- `--trust-remote-code` is intentionally disabled by default. Only enable it via
  explicit compose command edits after artifact verification.
- Keep secrets out of repo files (`.env.example`, `config.env.example`, docs).
- Prefer least-privilege host account mapping with `CONTAINER_UID/GID`.

## Next step

Use [docs/deployment.md](docs/deployment.md) for prerequisites, workflow
selection, smoke testing, troubleshooting, and rollback procedures. For no-lapse
release strategy, use
[docs/true-no-lapse-rollout.md](docs/true-no-lapse-rollout.md).
