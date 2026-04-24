# GLAB vLLM Service

This directory is the GLAB fork target for the host-native `vLLM` package.

The working baseline already exists at the repo root in `onprem_vllm_service/`.
For now, treat that root package as the implementation source of truth and keep
the GLAB runtime contract aligned with it.

## GLAB Runtime Contract

- bind host: `127.0.0.1`
- bind port: `8000`
- served model name: `gpt-oss-120b`
- model path: `/opt/models/gpt-oss-120b`
- install dir: `/opt/vllm`
- service name: `vllm`

## Why This Exists

GLAB needs its own host-only stack home so that:

- `LiteLLM` and KB indexing can live beside `vLLM`
- future GLAB-specific installer changes do not get mixed into older layouts
- the host-service topology is obvious from one directory tree

## Next Copy Step

When we intentionally fork `vLLM` for GLAB, mirror these files from the root package:

- `README.md`
- `install_vllm.sh`
- `systemd/vllm.service`
- `docs/OPERATIONS_RUNBOOK.md`
- `docs/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`
- `docs/SECURITY_POSTURE.md`

Do not let the root package and the GLAB fork drift on endpoint, model-path, or service-name contracts without an explicit decision.
