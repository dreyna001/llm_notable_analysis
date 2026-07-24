# Deployment Hardware Profiles

Hardware profiles are **operator tuning sheets** for `llm_notable_analysis_onprem_systemd`.
They recommend vLLM and `config.env` starting values for a specific CPU/GPU build.

These profiles are separate from **capability profiles** (`core`, `rag`, `spl_readonly`,
and so on). Capability profiles control product features. Deployment profiles control
how a particular host should run the same features.

## How To Use

1. Pick the profile that matches the host hardware.
2. Apply the profile's vLLM settings:
   - **Single GPU (`a6000-96gb-ultra9-285k`):** use the customer drop-in below
     for the validated VM. The generic packaged
     [`deploy/systemd/vllm.service`](../../../../deploy/systemd/vllm.service)
     remains a separate `0.92`/`dtype auto` starting point.
   - **Dual GPU (`h100x2-intel-tbd`):** no packaged unit; edit `vllm.service` or add a
     systemd drop-in with `--tensor-parallel-size 2` and profile env vars. Validate NCCL
     on the host before copying single-GPU loopback settings.
3. Merge profile analyzer values into `/etc/notable-analyzer/config.env`. Start from
   [`config.env.example`](../../../../config.env.example) (generic template with A6000-tuned
   LLM defaults), then apply the profile's concurrency, Splunk, and RAG overrides.
4. Keep capability profiles aligned with product scope (`CAPABILITY_PROFILES=...`); see
   [`CAPABILITY_PROFILES.md`](../../platform/CAPABILITY_PROFILES.md).
5. Run the profile validation steps before raising concurrency.
6. For serving load tests, use
   [`LLM_INFERENCE_BENCHMARKING.md`](../../llm/LLM_INFERENCE_BENCHMARKING.md).

Treat values as **recommended starting points**, not guarantees. Load-test on the
actual host before increasing `MAX_WORKERS`, `--max-num-seqs`, or Splunk concurrency.

## Customer Workload Templates

Full env copies tuned for **RTX PRO 6000 Blackwell + ~400 large notables/day + 5 concurrent portal analysts**.
These do not replace the generic defaults in [`config.env.example`](../../../../config.env.example).

| File | Install path |
|------|--------------|
| [`config.env.rtx-pro-6000-blackwell-5analysts.example`](../../../../config.env.rtx-pro-6000-blackwell-5analysts.example) | `/etc/notable-analyzer/config.env` |
| [`config.portal.env.rtx-pro-6000-blackwell-5analysts.example`](../../../../config.portal.env.rtx-pro-6000-blackwell-5analysts.example) | `/etc/notable-analyzer/portal.env` |
| [`vllm.rtx-pro-6000-blackwell-5analysts.drop-in.example`](../../../../deploy/systemd/vllm.rtx-pro-6000-blackwell-5analysts.drop-in.example) | `/etc/systemd/system/vllm.service.d/override.conf` |

Apply the profile to existing live env files without replacing secrets:

```bash
sudo bash scripts/apply_rtx_pro_6000_blackwell_5analysts_profile.sh
sudo bash scripts/apply_rtx_pro_6000_blackwell_5analysts_profile.sh --execute
```

The first command is a dry-run. The execute mode creates timestamped backups,
updates only profile-owned non-secret keys, removes duplicate profile-owned env
assignments, installs the vLLM drop-in, and does not restart services.

Conservative overrides versus the generic template:
`CAPABILITY_PROFILES=core,analyst_portal`, 32K model context end-to-end,
bounded chat history (`25` sessions/user, `30` messages/session, `30` days),
`CONCURRENCY_ENABLED=false`, `MAX_WORKERS=1`, `MAX_QUEUE_DEPTH=8`,
`PORTAL_CHAT_MAX_CONCURRENCY=4`, and vLLM `0.85` GPU memory,
`--max-num-seqs 4`, `bfloat16`, and eager mode.
Raise analyzer and portal concurrency only after representative load testing.

## Profiles

| Profile ID | Hardware | vLLM unit | Status |
|------------|----------|-----------|--------|
| [`a6000-96gb-ultra9-285k.md`](a6000-96gb-ultra9-285k.md) | 1x NVIDIA RTX PRO 6000 (96 GB) + Intel Core Ultra 9 285K (24 cores / 24 threads) | Packaged [`vllm.service`](../../../../deploy/systemd/vllm.service) | Active baseline |
| [`h100x2-intel-tbd.md`](h100x2-intel-tbd.md) | 2x NVIDIA H100 (80 GB) + Intel CPU (model TBD) | Manual override required | Draft / load-test required |

Shared analyzer contract across profiles: `LLM_API_URL=http://127.0.0.1:4000/v1/chat/completions`,
`LLM_MODEL_NAME=gemma-4-31B-it`, start with `CONCURRENCY_ENABLED=false` and `MAX_WORKERS=1`.

## Measured Benchmark Reports

| Report | Scope | Use |
|--------|-------|-----|
| [`a6000-96gb-ultra9-285k-vllm-benchmark-2026-05-28.md`](a6000-96gb-ultra9-285k-vllm-benchmark-2026-05-28.md) | Direct vLLM baseline for `gemma-4-31B-it`, 2048 input tokens, 512 output tokens, concurrency 4 | Customer hardware sizing and baseline throughput comparison |

No measured benchmark report exists yet for `h100x2-intel-tbd`.

## Related Docs

- [`CAPABILITY_PROFILES.md`](../../platform/CAPABILITY_PROFILES.md) — feature bundles
- [`LLM_INFERENCE_OPERATIONS.md`](../../llm/LLM_INFERENCE_OPERATIONS.md) — LLM client contract
- [`LLM_INFERENCE_BENCHMARKING.md`](../../llm/LLM_INFERENCE_BENCHMARKING.md) — serving load tests
- [`FILE_DROP_AND_RETENTION_OPERATIONS.md`](../../platform/FILE_DROP_AND_RETENTION_OPERATIONS.md) — concurrency and ingest
- [`INSTALL.md`](../INSTALL.md) — install and systemd bring-up
- [`config.env.example`](../../../../config.env.example) — generic template (merge profile overrides)
- [`deploy/systemd/vllm.service`](../../../../deploy/systemd/vllm.service) — packaged single-GPU unit
