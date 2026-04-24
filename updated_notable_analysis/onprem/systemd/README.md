# On-Prem systemd Template

This directory contains the host service template for the updated on-prem analyzer worker.

The template intentionally does not introduce a Python CLI or package entrypoint. Deployment packaging must provide the executable referenced by `ExecStart`:

- `/opt/notable-analyzer/bin/run-onprem-worker`

That launcher is responsible for:

- constructing the real deployment `CoreAnalysisRunner`, typically `OnPremLiteLlmCoreRunner`
- calling `updated_notable_analysis.onprem.build_default_worker(...)`
- calling `updated_notable_analysis.onprem.install_stop_signal_handlers(...)`
- running `worker.run_until_stopped()`

The analyzer unit depends on `litellm.service`, not directly on `vllm.service`. LiteLLM owns the vLLM dependency and keeps the analyzer-facing boundary stable at loopback.

The service file keeps the analyzer filesystem write scope limited to `/var/notables` and `/var/sftp/soar`, and keeps analyzer network access constrained to loopback.
