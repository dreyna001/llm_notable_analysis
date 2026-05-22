# Deployment Hardware Profiles

Hardware profiles are **operator tuning sheets** for `llm_notable_analysis_onprem_systemd`.
They recommend vLLM and `config.env` starting values for a specific CPU/GPU build.

These profiles are separate from **capability profiles** (`core`, `rag`, `spl_readonly`,
and so on). Capability profiles control product features. Deployment profiles control
how a particular host should run the same features.

## How To Use

1. Pick the profile that matches the host hardware.
2. Copy the recommended vLLM flags into `/etc/systemd/system/vllm.service` (or use the
   packaged unit plus documented overrides).
3. Copy the recommended analyzer values into `/etc/notable-analyzer/config.env`.
4. Keep capability profiles aligned with product scope (`CAPABILITY_PROFILES=...`).
5. Run the validation steps in the profile before raising concurrency.

Treat values as **recommended starting points**, not guarantees. Load-test on the
actual host before increasing `MAX_WORKERS`, `--max-num-seqs`, or Splunk concurrency.

## Profiles

| Profile ID | Hardware | Status |
|------------|----------|--------|
| [`a6000-96gb-ultra9-285k.md`](a6000-96gb-ultra9-285k.md) | 1x NVIDIA RTX PRO 6000 (96 GB) + Intel Core Ultra 9 Processor 285K | Active baseline |
| [`h100x2-intel-tbd.md`](h100x2-intel-tbd.md) | 2x NVIDIA H100 (80 GB) + Intel CPU (model TBD) | Draft / load-test required |

## Related Docs

- [`../CAPABILITY_PROFILES.md`](../CAPABILITY_PROFILES.md) — feature bundles
- [`../LLM_INFERENCE_OPERATIONS.md`](../LLM_INFERENCE_OPERATIONS.md) — LLM client contract
- [`../FILE_DROP_AND_RETENTION_OPERATIONS.md`](../FILE_DROP_AND_RETENTION_OPERATIONS.md) — concurrency and ingest
- [`../../../config.env.example`](../../../config.env.example) — generic template (not host-specific)
- [`../../../deploy/systemd/vllm.service`](../../../deploy/systemd/vllm.service) — packaged single-GPU unit
