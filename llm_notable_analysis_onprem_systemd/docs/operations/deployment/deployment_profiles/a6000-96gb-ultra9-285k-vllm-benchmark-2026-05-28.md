# Measured vLLM Benchmark: `a6000-96gb-ultra9-285k`

## Status

Measured direct-vLLM baseline from the current single-GPU on-prem build.

Use this report to help customers understand **model-server throughput** for the
RTX PRO 6000 96 GB class of hardware. Do not treat these numbers as an
end-to-end notable-analysis SLA; the analyzer adds prompt construction,
structured parsing/repair, optional RAG, optional Splunk/Elasticsearch calls,
report writing, and workflow-level queueing.

## Hardware And Serving Shape

| Component | Value |
|-----------|-------|
| GPU | 1x NVIDIA RTX PRO 6000 Blackwell, 96 GB VRAM |
| CPU | Intel Core Ultra 9 285K, 24 cores / 24 threads, 1 socket, 1 NUMA node |
| Model | `gemma-4-31B-it` |
| Model path | `/opt/models/gemma-4-31B-it` |
| Serving path measured | Direct vLLM (`127.0.0.1:8000`) |
| Proxy included | No; this baseline bypasses LiteLLM |
| Date measured | 2026-05-28 |

CPU detail from the measured host:

- Architecture: `x86_64`
- Model name: `Intel(R) Core(TM) Ultra 9 285K`
- Threads per core: `1`
- Max frequency: `6500 MHz`
- L2 cache: `40 MiB`
- L3 cache: `36 MiB`

## Methodology

This report records a **vLLM bench** run, not the repo
[`benchmark_inference_server.py`](../../../../scripts/benchmark_inference_server.py)
script. See [`LLM_INFERENCE_BENCHMARKING.md`](../../llm/LLM_INFERENCE_BENCHMARKING.md)
for tool selection, endpoint paths, and rollout checks.

| Aspect | This run | Repo script default |
|--------|----------|---------------------|
| Tool | `/opt/vllm/venv/bin/vllm bench serve` | `python3 scripts/benchmark_inference_server.py` |
| Endpoint | Direct vLLM `127.0.0.1:8000` | LiteLLM `127.0.0.1:4000` from `config.env` |
| Input length | Tokenizer-accurate random 2048 | Approximate `--contexts` target |
| Output cap | Fixed 512 generated tokens | `--max-tokens` cap (actual length varies) |
| Concurrency | 4 | Sweep default `1,2,4,8` |
| Prompt count | 100 | Default 32 per case |
| Key metrics | TTFT, TPOT, ITL, token/sec | `p95_latency_s`, `p95_ttft_s`, `completion_tok_per_sec` |

Reproduce the same shape with the repo script for a quick LiteLLM or vLLM smoke
check (metrics will not match row-for-row):

```bash
python3 scripts/benchmark_inference_server.py \
  --url http://127.0.0.1:8000/v1/chat/completions \
  --model gemma-4-31B-it \
  --requests 100 \
  --concurrency 4 \
  --contexts 2048 \
  --max-tokens 512
```

## Benchmark Command

Recorded command (matches
[`LLM_INFERENCE_BENCHMARKING.md`](../../llm/LLM_INFERENCE_BENCHMARKING.md)):

```bash
/opt/vllm/venv/bin/vllm bench serve \
  --backend openai-chat \
  --base-url http://127.0.0.1:8000 \
  --endpoint /v1/chat/completions \
  --model gemma-4-31B-it \
  --tokenizer /opt/models/gemma-4-31B-it \
  --dataset-name random \
  --random-input-len 2048 \
  --random-output-len 512 \
  --num-prompts 100 \
  --max-concurrency 4
```

Important command details:

- `--model` is the served API name.
- `--tokenizer` points to the local model directory so vLLM bench can build
  tokenizer-accurate random prompts.
- `--endpoint /v1/chat/completions` is required with `--backend openai-chat`.
- This command measures vLLM directly. Run the same command with
  `--base-url http://127.0.0.1:4000` to measure the production LiteLLM route.

## Workload Shape

| Parameter | Value |
|-----------|-------|
| Successful requests | 100 |
| Failed requests | 0 |
| Maximum request concurrency | 4 |
| Random input length (target) | 2048 tokens |
| Random output length (target) | 512 tokens |
| Total input tokens | 206,147 (~2,061/request; chat-template overhead) |
| Total generated tokens | 51,200 (512/request) |
| Benchmark duration | 611.39 s |

This is a useful proxy for larger notable-analysis calls where prompt context is
RAG-heavy or event-rich and the model is asked to produce a substantial
structured response section. Smaller outputs or shorter prompts will complete
faster; multi-call workflows will consume more aggregate serving capacity.

## Measured Results

| Metric | Result |
|--------|--------|
| Request throughput | 0.16 req/s (100 / 611.39 s) |
| Approximate requests/minute | 9.8 |
| Approximate requests/hour | 589 |
| Output token throughput | 83.74 tok/s (51,200 / 611.39 s) |
| Peak output token throughput | 92.00 tok/s (vLLM bench window metric) |
| Total token throughput | 420.92 tok/s ((206,147 + 51,200) / 611.39 s) |
| Mean TTFT | 1,552.06 ms |
| Median TTFT | 1,462.88 ms |
| P99 TTFT | 1,892.15 ms |
| Mean TPOT | 44.82 ms/token |
| Median TPOT | 45.03 ms/token |
| P99 TPOT | 45.07 ms/token |
| Mean ITL | 44.73 ms |
| Median ITL | 44.24 ms |
| P99 ITL | 44.49 ms |

Derived interpretation:

- Mean TPOT of `44.82 ms/token` is roughly `22.3 tokens/sec` per actively
  decoding request.
- Aggregate output throughput of `83.74 tokens/sec` shows effective continuous
  batching at this concurrency and output length.
- The narrow TPOT and ITL spread indicates stable decode behavior once
  generation starts.
- P99 TTFT under 2 seconds for 2K-token prompts at this concurrency is a healthy
  direct-vLLM baseline for this model and GPU class.

## Capacity Guidance

For procurement and sizing conversations, this result supports the following
planning assumptions for this hardware class:

| Question | Planning Answer |
|----------|-----------------|
| Can one RTX PRO 6000 96 GB serve `gemma-4-31B-it` locally? | Yes, for the measured direct-vLLM workload. |
| Is the run stable at concurrency 4? | Yes; this run had 100 successes and 0 failures. |
| Is generation the main cost? | Yes; the run is decode-bound for 512-token outputs. |
| Is this enough for a low-to-moderate notable-analysis deployment? | Likely yes, subject to actual alert size, RAG, Splunk, and workflow settings. |
| Should customers needing higher multi-user or multi-call throughput buy more GPU? | Yes; test H100-class or multi-GPU profiles when target workload exceeds this baseline. |

Practical customer guidance:

- This single-GPU profile is a strong starting point for pilots, demos, and
  production deployments with controlled analyzer concurrency.
- Keep `MAX_WORKERS=1` for first rollout. Move to `MAX_WORKERS=2` only after
  LiteLLM-path benchmarks and representative notable runs remain stable.
- If a customer expects concurrent analysts, high alert volume, RAG-heavy prompts,
  SPL generation plus interpretation, or multiple LLM calls per notable, size
  above this baseline or validate with the H100 profile.
- Do not convert the direct-vLLM requests/hour number directly into
  notables/hour. One notable can require multiple LLM calls plus non-LLM work.

## What To Compare Next

Before changing production settings, capture:

1. The same workload through LiteLLM:
   ```bash
   /opt/vllm/venv/bin/vllm bench serve \
     --backend openai-chat \
     --base-url http://127.0.0.1:4000 \
     --endpoint /v1/chat/completions \
     --model gemma-4-31B-it \
     --tokenizer /opt/models/gemma-4-31B-it \
     --dataset-name random \
     --random-input-len 2048 \
     --random-output-len 512 \
     --num-prompts 100 \
     --max-concurrency 4
   ```
2. A shorter-output case, for example `--random-output-len 128`.
3. A larger-context case, for example `--random-input-len 8192`.
4. A representative end-to-end notable run with the intended
   `CAPABILITY_PROFILES` and analyzer `MAX_WORKERS`.

## Related Docs

- [`a6000-96gb-ultra9-285k.md`](a6000-96gb-ultra9-285k.md) — host profile and `config.env` defaults
- [`../../llm/LLM_INFERENCE_BENCHMARKING.md`](../../llm/LLM_INFERENCE_BENCHMARKING.md) — vLLM bench and repo script procedures
- [`../../../../scripts/benchmark_inference_server.py`](../../../../scripts/benchmark_inference_server.py) — stdlib serving benchmark
- [`../../llm/LLM_INFERENCE_OPERATIONS.md`](../../llm/LLM_INFERENCE_OPERATIONS.md) — LLM client contract
- [`h100x2-intel-tbd.md`](h100x2-intel-tbd.md) — higher-throughput draft profile
