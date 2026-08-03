# Two-T4 llama.cpp Gemma 4 Demo Profile

## Decision

Two 16 GB NVIDIA T4 GPUs are sufficient for a **single-user demo** of the
on-prem application when the backend is llama.cpp and the model is Google's
official **Gemma 4 26B-A4B instruction-tuned QAT Q4_0 GGUF**. This is not the
recommended production profile and it must not inherit the 31B BF16/vLLM
settings used by the larger GPU builds.

The selected model has about 25.2B total parameters and 3.8B active parameters.
Its main GGUF is about 13.45 GiB and its multimodal projector is about 1.11 GiB.
The profile spreads model layers and KV cache across both T4s, caps context at
16K, and admits one request at a time. See the
[official model repository](https://huggingface.co/google/gemma-4-26B-A4B-it-qat-q4_0-gguf),
[llama.cpp](https://github.com/ggml-org/llama.cpp), and
[NVIDIA T4 specifications](https://www.nvidia.com/en-us/data-center/tesla-t4/).

## Customer-Facing Quality Statement

Use this wording for the demo expectation:

> The two-T4 build uses Google's quantization-aware-trained 4-bit Gemma 4 26B
> checkpoint. It is a credible demo configuration, not a toy fallback, but it
> will have some quality loss versus the unquantized model and less headroom
> than the 31B build. It is configured for one active request and a 16K context.
> We will validate it against representative customer notables before making
> any production claim.

The 4-bit checkpoint should remain useful for extraction, summarization,
grounded Q&A, and the structured analysis flow. The main risks are edge-case
reasoning accuracy, long-context recall, and latency. Do not promise a fixed
tokens/second figure before measuring the actual host, PCIe layout, prompt
sizes, and customer examples.

## Host Prerequisites

| Requirement | Demo minimum |
|-------------|--------------|
| GPUs | 2x NVIDIA T4, 16 GB each; default indexes `0,1` |
| Driver | Working `nvidia-smi` visible to root/systemd |
| CUDA toolkit | `nvcc` installed; the installer compiles specifically for SM 7.5 |
| System RAM | 64 GB recommended; more helps installation and model loading |
| Free disk | At least 25 GiB under `/opt` |
| Service manager | systemd |
| Network | HTTPS access to GitHub, Hugging Face, OS repos, and Python/npm repos used by the base installer |

The one-command script intentionally does not install the NVIDIA driver or CUDA
toolkit. Those packages depend on the approved OS repository and can require a
reboot. It fails before modifying the application if either prerequisite is
missing.

## One-Command Install

From the repository checkout:

```bash
cd /path/to/llm_notable_analysis_onprem_systemd
sudo bash scripts/install_t4x2_llamacpp_demo.sh
```

That command:

1. Validates two T4s, CUDA compiler availability, and free disk.
2. Runs the standard application installer with vLLM installation and service
   startup disabled; the analyst portal is included by default.
3. Installs build dependencies and compiles a pinned llama.cpp revision for
   T4 compute capability 7.5.
4. Downloads the pinned official model and projector, then verifies both with
   committed SHA-256 checksums.
5. Installs the unprivileged `llamacpp-gemma.service`, the LiteLLM route and
   dependency override, and bounded application settings.
6. Disables the port-conflicting vLLM service, starts the service chain, waits
   for readiness, and runs a direct inference smoke test.

No Hugging Face token is required for this repository. Model use remains
subject to the Gemma license and the customer's model-governance approval.

### Installer flags

| Variable | Default | Purpose |
|----------|---------|---------|
| `T4_CUDA_VISIBLE_DEVICES` | `0,1` | Select exactly two physical GPU indexes |
| `T4_INSTALL_ANALYST_PORTAL` | `true` | Install the portal, PostgreSQL, nginx, and frontend path |
| `T4_AUTO_START` | `true` | Start services and run readiness/inference checks |
| `T4_SKIP_BASE_INSTALL` | `false` | Reuse an already installed application and LiteLLM environment |
| `T4_SKIP_DISK_CHECK` | `false` | Bypass only the 25 GiB free-space check |
| `LLAMACPP_BUILD_JOBS` | `8` | Limit parallel compilation work |

Examples:

```bash
# Existing application install; add/replace only the inference profile
sudo T4_SKIP_BASE_INSTALL=true bash scripts/install_t4x2_llamacpp_demo.sh

# Install files but leave service startup to the operator
sudo T4_AUTO_START=false bash scripts/install_t4x2_llamacpp_demo.sh

# GPUs are physical indexes 2 and 3
sudo T4_CUDA_VISIBLE_DEVICES=2,3 bash scripts/install_t4x2_llamacpp_demo.sh
```

## Enforced Runtime Contract

| Layer | Setting |
|-------|---------|
| llama.cpp | `--gpu-layers all`, `--split-mode layer`, `--tensor-split 1,1` |
| Capacity | `--ctx-size 16384`, `--parallel 1`, continuous batching |
| KV cache | Q8_0 keys and values to conserve VRAM without 4-bit KV-cache pressure |
| Generation | Reasoning mode off, Jinja chat template, max application output 2,048 tokens |
| Network | llama.cpp `127.0.0.1:8000`; LiteLLM `127.0.0.1:4000` |
| Application | Sequential analyzer worker, queue depth 8, one portal chat at a time |
| Model alias | `gemma-4-26B-A4B-it` from application through LiteLLM to llama.cpp |

The layer split is preferred over llama.cpp's experimental tensor split on
PCIe-attached T4s. The image projector remains installed so existing single-
image portal flows can be exercised, but image prompts consume additional
context and latency.

Runtime knobs are in `/etc/notable-analyzer/llamacpp-gemma.env`. Keep
`LLAMACPP_PARALLEL=1` and 16K context for the initial customer demo. Changing
those values is an explicit requalification, not a routine tuning step.

## Validation and Operations

```bash
nvidia-smi
systemctl status llamacpp-gemma litellm notable-analyzer notable-portal
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:4000/v1/models
journalctl -u llamacpp-gemma -u litellm -u notable-analyzer -f
```

Before the customer session:

1. Run the repository's golden evaluation set against this profile and compare
   structured-field correctness with the larger reference build.
2. Exercise a short, medium, and worst-case representative notable.
3. Verify both GPUs remain below out-of-memory limits at the longest planned
   prompt and with a portal image if images are part of the demo.
4. Record time-to-first-token and total response time; do not raise concurrency
   to hide latency.

## Reapply, Backups, and Rollback

To preview or reapply just the non-secret profile settings:

```bash
sudo bash scripts/apply_t4x2_llamacpp_demo_profile.sh
sudo bash scripts/apply_t4x2_llamacpp_demo_profile.sh --execute
```

Every execute run backs up the analyzer env, portal env when present, LiteLLM
config, and existing LiteLLM drop-in under
`/root/notable-profile-backups/t4x2-llamacpp-demo/` in a timestamped directory. It does not
copy or print secret values.

To return to the previous backend:

1. Stop and disable `llamacpp-gemma.service`.
2. Restore `config.env`, `portal.env`, and `litellm-config.yaml` from the chosen
   timestamped backup.
3. Restore the prior LiteLLM drop-in if the backup contains one; otherwise
   remove only `/etc/systemd/system/litellm.service.d/t4x2-llamacpp.conf`.
4. Run `systemctl daemon-reload`, then enable/start the previously configured
   vLLM backend, LiteLLM, analyzer, and portal in that order.

The installer leaves the vLLM unit and environment on disk; it only disables
the service to prevent both backends from claiming port 8000.
