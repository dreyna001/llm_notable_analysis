# Deployment Profile: `h100x2-intel-tbd`

## Status

Draft. No measured benchmark on this hardware yet. Intended for a dual-H100 host
with an Intel CPU whose model is not confirmed. Treat vLLM flags, analyzer
concurrency, RAG rerank guidance, and throughput expectations as provisional
starting points until the CPU is identified and load-tested on the actual machine.

Compare against the validated single-GPU baseline:
[`a6000-96gb-ultra9-285k-vllm-benchmark-2026-05-28.md`](a6000-96gb-ultra9-285k-vllm-benchmark-2026-05-28.md).

## Hardware

| Component | Value |
|-----------|-------|
| GPU | 2x NVIDIA H100 (80 GB VRAM each, 160 GB total) |
| CPU | Intel (model TBD) |
| Interconnect | NVLink vs PCIe topology not confirmed on target host |
| Default model | `gemma-4-31B-it` (same product contract as other on-prem builds) |
| Inference stack | vLLM (`127.0.0.1:8000`) -> LiteLLM (`127.0.0.1:4000`) -> analyzer |

The packaged `deploy/systemd/vllm.service` unit is single-GPU. Do not deploy it
unchanged; override `CUDA_VISIBLE_DEVICES`, add `--tensor-parallel-size 2`, and
validate NCCL/bootstrap behavior on the host before production use.

## Recommended Capability Profiles

Same product profiles as other builds. Hardware changes serving and concurrency,
not capability semantics. See
[`../../platform/CAPABILITY_PROFILES.md`](../../platform/CAPABILITY_PROFILES.md).

Start narrow, add profiles after validation:

```bash
# Baseline production
CAPABILITY_PROFILES=core

# After KB and Splunk owners approve integrations
CAPABILITY_PROFILES=core,html_reports,rag,spl_readonly
```

## vLLM Recommended Starting Settings

Dual-GPU tensor parallel for a single 31B model on one host. Adjust NCCL and
network env vars if vLLM fails to initialize across GPUs on the actual machine.

```ini
Environment="CUDA_VISIBLE_DEVICES=0,1"
Environment="VLLM_HOST_IP=127.0.0.1"
Environment="MASTER_ADDR=127.0.0.1"

ExecStart=/opt/vllm/venv/bin/python -m vllm.entrypoints.openai.api_server \
    --model /opt/models/gemma-4-31B-it \
    --served-model-name gemma-4-31B-it \
    --host 127.0.0.1 \
    --port 8000 \
    --tensor-parallel-size 2 \
    --gpu-memory-utilization 0.90 \
    --max-model-len 32768 \
    --dtype auto \
    --distributed-executor-backend mp
```

After first successful boot and smoke test, consider:

```ini
    --max-num-seqs 8 \
```

Notes:

- Start with `--max-model-len 32768` for notable analysis; raise only with evidence.
- `--gpu-memory-utilization 0.90` is a conservative dual-GPU starting point.
- If NCCL bootstrap fails, review vLLM logs and host NCCL/GPU topology before
  changing analyzer settings. Multi-GPU vLLM tuning belongs in the vLLM unit first.
- Do not copy single-GPU loopback/NCCL assumptions from the packaged unit blindly;
  validate on the actual H100 host (PCIe-only vs NVLink may change safe defaults).

## Analyzer `config.env` Recommended Starting Settings

Copy these into `/etc/notable-analyzer/config.env`. Merge secrets, Splunk/ServiceNow
endpoints, and Postgres DSN locally; do not commit live values. Client contract:
[`../../llm/LLM_INFERENCE_OPERATIONS.md`](../../llm/LLM_INFERENCE_OPERATIONS.md).

### LLM

```bash
LLM_API_URL=http://127.0.0.1:4000/v1/chat/completions
LLM_MODEL_NAME=gemma-4-31B-it
LLM_STRUCTURED_OUTPUT_MODE=prompt_json
LLM_MAX_TOKENS=4096
LLM_TIMEOUT=240
```

Use `LLM_TIMEOUT=120` only for `CAPABILITY_PROFILES=core` with no SPL interpretation.

### Concurrency

Start sequential even on H100. Dual GPUs improve per-request throughput and batch
capacity; they do not remove the need to validate multi-notable behavior. Ingest
and queue behavior:
[`../../platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](../../platform/FILE_DROP_AND_RETENTION_OPERATIONS.md).

```bash
CONCURRENCY_ENABLED=false
MAX_WORKERS=1
MAX_QUEUE_DEPTH=8
```

First load-test ladder on this host:

```bash
CONCURRENCY_ENABLED=true
MAX_WORKERS=2
MAX_QUEUE_DEPTH=16
```

If vLLM is stable with `--max-num-seqs 8` and acceptable latency:

```bash
MAX_WORKERS=4
MAX_QUEUE_DEPTH=32
```

Do not jump directly to `MAX_WORKERS=4`.

### Splunk investigation (when `spl_readonly` is enabled)

Same policy bounds as other builds:

```bash
INVESTIGATION_MAX_QUERIES_PER_ALERT=6
INVESTIGATION_MAX_CONCURRENT_QUERIES=6
SPLUNK_SEARCH_TIMEOUT_SECONDS=30
```

Confirm Splunk search concurrency with the Splunk platform owner before running
all six queries in parallel across multiple notables. Splunk limits may cap
effective parallelism before GPU limits do.

### RAG (when `rag` is enabled)

Stage Mixedbread models before enabling RAG:

```bash
RAG_BACKEND=postgres
RAG_EMBEDDING_MODEL=mixedbread-ai/mxbai-embed-large-v1
RAG_VECTOR_DIMENSIONS=1024
RAG_FAIL_CLOSED=false
RAG_RERANK_ENABLED=false
```

After CPU model is known and reranker is staged, rerank is likely safe on a
dual-socket or high-core Intel host. Enable only after validation:

```bash
RAG_RERANK_MODEL=mixedbread-ai/mxbai-rerank-large-v2
RAG_RERANK_ENABLED=true
```

`gemma-4-31B-it` uses the repo's **120B-class** RAG snippet/budget defaults automatically.

## Expected Throughput (Rough, Draft)

No fixed SLA or notables/hour numbers for this profile yet. Higher than the
single A6000 build is plausible, but measure before committing to customer sizing.

| Stage | Expectation |
|-------|-------------|
| Sequential `core` | Likely higher than A6000 sequential baseline (~20-50 notables/hour) |
| `MAX_WORKERS=2` + `--max-num-seqs 8` | Best first concurrency target to measure |
| Full SPL + interpretation | Still Splunk- and multi-LLM-call-bound for many alerts |

Do not convert direct-vLLM requests/hour into notables/hour. One notable can
require multiple LLM calls plus non-LLM work.

## Validation Checklist

1. Confirm both GPUs visible: `nvidia-smi`
2. Start vLLM with `--tensor-parallel-size 2`
3. Verify models endpoint: `curl -sS http://127.0.0.1:8000/v1/models`
4. Verify LiteLLM route: `curl -sS http://127.0.0.1:4000/v1/models`
5. Run smoke chain:
   ```bash
   sudo bash scripts/smoke_service_chain.sh --config-env /etc/notable-analyzer/config.env
   ```
6. Run an inference serving benchmark:
   [`../../llm/LLM_INFERENCE_BENCHMARKING.md`](../../llm/LLM_INFERENCE_BENCHMARKING.md)
7. Process representative notables at `MAX_WORKERS=1`
8. Record p50/p95 latency and GPU utilization
9. Only then test `MAX_WORKERS=2` and optional `--max-num-seqs 8`

## Change Only After Load Test

- `CONCURRENCY_ENABLED=true`
- `MAX_WORKERS=2` or higher
- `--max-num-seqs`
- `RAG_RERANK_ENABLED=true`
- Higher Splunk concurrency combined with multi-notable workers

## Open Items (Update This Profile Later)

- [ ] Record exact Intel CPU model (cores, sockets, NUMA)
- [ ] Confirm GPU interconnect (NVLink vs PCIe-only) and NCCL behavior on the host
- [ ] Capture measured notables/hour at `MAX_WORKERS=1` and `2`
- [ ] Capture direct-vLLM and LiteLLM-path benchmark results for this host
- [ ] Decide final `--max-num-seqs` and `MAX_WORKERS`
- [ ] Decide whether `--max-model-len` should stay at `32768`
- [ ] Update RAG rerank recommendation after CPU identification

## Related Docs

- [`a6000-96gb-ultra9-285k.md`](a6000-96gb-ultra9-285k.md) — validated single-GPU baseline
- [`a6000-96gb-ultra9-285k-vllm-benchmark-2026-05-28.md`](a6000-96gb-ultra9-285k-vllm-benchmark-2026-05-28.md) — measured comparison baseline
- [`README.md`](README.md) — profile index
- [`../../platform/CAPABILITY_PROFILES.md`](../../platform/CAPABILITY_PROFILES.md) — feature bundles
- [`../../llm/LLM_INFERENCE_OPERATIONS.md`](../../llm/LLM_INFERENCE_OPERATIONS.md) — LLM client contract
- [`../../llm/LLM_INFERENCE_BENCHMARKING.md`](../../llm/LLM_INFERENCE_BENCHMARKING.md) — serving load tests
- [`../../platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](../../platform/FILE_DROP_AND_RETENTION_OPERATIONS.md) — concurrency and ingest
