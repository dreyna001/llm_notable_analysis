# Deployment Profile: `h100x2-intel-tbd`

## Status

Draft. Intended for a dual-H100 host. CPU model is not confirmed yet; treat
concurrency and RAG CPU guidance as provisional until the CPU is identified and
load-tested.

## Hardware

| Component | Value |
|-----------|-------|
| GPU | 2x NVIDIA H100 (80 GB VRAM each, 160 GB total) |
| CPU | Intel (model TBD) |
| Default model | `gemma-4-31B-it` (same product contract as other on-prem builds) |
| Inference stack | vLLM (tensor parallel) -> LiteLLM -> analyzer |

## Recommended Capability Profiles

Same product profiles as other builds. Hardware changes serving and concurrency,
not capability semantics:

```bash
CAPABILITY_PROFILES=core
# CAPABILITY_PROFILES=core,html_reports,rag,spl_readonly
```

## vLLM Recommended Starting Settings

Dual-GPU tensor parallel for a single 31B model on one host. Adjust NCCL/network
env vars if vLLM fails to initialize across GPUs on the actual machine.

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
- Do not copy single-GPU `NCCL_IB_DISABLE=1` / loopback-only assumptions blindly;
  validate on the actual H100 host.

## Analyzer `config.env` Recommended Starting Settings

Use the same analyzer contract as other builds unless load tests show headroom.

### LLM

```bash
LLM_API_URL=http://127.0.0.1:4000/v1/chat/completions
LLM_MODEL_NAME=gemma-4-31B-it
LLM_STRUCTURED_OUTPUT_MODE=prompt_json
LLM_MAX_TOKENS=4096
LLM_TIMEOUT=240
```

### Concurrency

Start sequential even on H100. Dual GPUs improve per-request throughput and batch
capacity; they do not remove the need to validate multi-notable behavior.

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

If vLLM stable with `--max-num-seqs 8` and acceptable latency:

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

Splunk platform limits may cap effective parallelism before GPU limits do.

### RAG (when `rag` is enabled)

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

## Expected Throughput (Rough, Draft)

Higher than the single A6000 build, but do not publish a fixed SLA until measured.

| Stage | Expectation |
|-------|-------------|
| Sequential `core` | Likely higher than A6000 sequential baseline |
| `MAX_WORKERS=2` + `--max-num-seqs 8` | Best first concurrency target to measure |
| Full SPL + interpretation | Still Splunk- and multi-LLM-call-bound for many alerts |

## Validation Checklist

1. Confirm both GPUs visible: `nvidia-smi`
2. Start vLLM with `--tensor-parallel-size 2`
3. Verify models endpoint: `curl -sS http://127.0.0.1:8000/v1/models`
4. Verify LiteLLM route: `curl -sS http://127.0.0.1:4000/v1/models`
5. Run `scripts/smoke_service_chain.sh`
6. Run an inference serving benchmark:
   [`../LLM_INFERENCE_BENCHMARKING.md`](../LLM_INFERENCE_BENCHMARKING.md)
7. Process representative notables at `MAX_WORKERS=1`
8. Record p50/p95 latency and GPU utilization
9. Only then test `MAX_WORKERS=2` and optional `--max-num-seqs 8`

## Open Items (Update This Profile Later)

- [ ] Record exact Intel CPU model
- [ ] Confirm NCCL / NVLink behavior on the host
- [ ] Capture measured notables/hour at `MAX_WORKERS=1` and `2`
- [ ] Decide final `--max-num-seqs` and `MAX_WORKERS`
- [ ] Decide whether `--max-model-len` should stay at `32768`
- [ ] Update RAG rerank recommendation after CPU identification

## Related Docs

- [`a6000-96gb-ultra9-285k.md`](a6000-96gb-ultra9-285k.md) — validated single-GPU baseline
- [`README.md`](README.md) — profile index
- [`../CAPABILITY_PROFILES.md`](../CAPABILITY_PROFILES.md)
