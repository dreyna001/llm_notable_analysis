# LLM Inference Benchmarking

Measure local LLM serving performance without running the notable-analysis
application. Use before raising analyzer concurrency, `--max-num-seqs`, or other
inference limits.

## What This Controls

Benchmarking measures the **inference serving stack only**:

```text
HTTP client -> LiteLLM (127.0.0.1:4000) -> vLLM (127.0.0.1:8000) -> GPU
```

It does **not** measure notable ingest, RAG, Splunk/Elasticsearch, or analyzer
parse/repair. Treat results as **serving capacity and latency**, not end-to-end
notable throughput.

## Recommended Starting Posture

- Stop or idle `notable-analyzer` so GPU and queue capacity are not shared.
- Start at **concurrency=1**, then increase only when failures stay at zero and
  latency growth is acceptable.
- Benchmark both paths when tuning production:
  - **LiteLLM path:** `http://127.0.0.1:4000` (analyzer route)
  - **vLLM direct path:** `http://127.0.0.1:8000` (model-server baseline)
- Keep endpoints on loopback unless a documented lab exception is approved.
- Change one serving or analyzer setting at a time between runs.

## Customer Decisions

### Which benchmark tool?

| Tool | When to use |
|------|-------------|
| [`scripts/benchmark_inference_server.py`](../../../scripts/benchmark_inference_server.py) | Fast operator smoke/load checks from a repo checkout; stdlib only; reads `/etc/notable-analyzer/config.env` defaults |
| `/opt/vllm/venv/bin/vllm bench serve` | Capacity planning with tokenizer-accurate lengths, request-rate control, and richer percentiles |

Use the repo script for quick checks tied to deployment config. Use vLLM bench
before changing `--max-num-seqs`, `CONCURRENCY_ENABLED`, or `MAX_WORKERS`.

### Which endpoint?

- **Production-shaped path:** LiteLLM at `http://127.0.0.1:4000`
- **Model-server baseline:** vLLM at `http://127.0.0.1:8000`

If LiteLLM and vLLM numbers diverge materially, inspect LiteLLM logs before
blaming GPU or model settings.

### What workload shape?

Start with shapes close to notable-analysis LLM calls:

| Dimension | Starting values | Why |
|-----------|-----------------|-----|
| Input context | 512, 2048, 8192 tokens | small alert vs RAG-heavy prompts |
| Output cap | 128, 512 tokens | short structured sections vs longer outputs |
| Concurrency | 1, 2, 4 | conservative single-GPU rollout |
| Requests per case | 32+ | enough samples for p95 latency |

**Reference vLLM bench case** (measured on the active A6000 profile):
2048 input tokens, 512 output tokens, concurrency 4, 100 prompts. See
[`a6000-96gb-ultra9-285k-vllm-benchmark-2026-05-28.md`](../deployment/deployment_profiles/a6000-96gb-ultra9-285k-vllm-benchmark-2026-05-28.md).

The repo script uses approximate context sizing (~0.75 words/token). vLLM bench
uses the local tokenizer and is authoritative for exact token counts.

## Repo Benchmark Script

### Where to run

The installer copies application code to `/opt/notable-analyzer` but does **not**
install `scripts/`. Run from a repo checkout:

```bash
cd /path/to/llm_notable_analysis_onprem_systemd
python3 scripts/benchmark_inference_server.py \
  --config-env /etc/notable-analyzer/config.env
```

Defaults when flags are omitted (from `config.env`, then environment, then
script defaults):

| Input | Source order | Script default |
|-------|--------------|----------------|
| URL | `--url`, `LLM_API_URL`, config | `http://127.0.0.1:4000/v1/chat/completions` |
| Model | `--model`, `LLM_MODEL_NAME`, config | `gemma-4-31B-it` |
| Token | `--token`, `LLM_API_TOKEN`, config | none |
| Config path | `--config-env`, `CONFIG_ENV` | `/etc/notable-analyzer/config.env` |

Other script defaults: `--requests 32`, `--concurrency 1,2,4,8`,
`--contexts 512,2048,8192,16000`, `--max-tokens 128,512`, `--timeout-seconds 600`,
`--temperature 0.0`, `--mode stream`, `--warmup-requests 1`.

Each measured case runs `max(--requests, concurrency)` requests. Plain HTTP
outside loopback is refused unless `--allow-non-loopback-http` is set.

### Example commands

LiteLLM production path:

```bash
python3 scripts/benchmark_inference_server.py \
  --config-env /etc/notable-analyzer/config.env \
  --requests 64 \
  --concurrency 1,2,4 \
  --contexts 512,2048,8192 \
  --max-tokens 128,512 \
  --jsonl-out /tmp/inference_benchmark.jsonl
```

Direct vLLM path:

```bash
python3 scripts/benchmark_inference_server.py \
  --url http://127.0.0.1:8000/v1/chat/completions \
  --model gemma-4-31B-it \
  --requests 64 \
  --concurrency 1,2,4 \
  --contexts 512,2048,8192 \
  --max-tokens 128,512
```

Useful flags:

| Flag | Purpose |
|------|---------|
| `--mode stream` | default; measures TTFT from streamed tokens |
| `--mode nonstream` | use if streaming or `stream_options.include_usage` is unsupported |
| `--static-prompt` | reuse one prompt; allows prefix-cache effects (default varies per request) |
| `--warmup-requests N` | warmup per context/max_tokens pair before measured cases (default 1) |
| `--timeout-seconds N` | per-request HTTP timeout (default 600) |
| `--temperature N` | request temperature (default 0.0) |
| `--jsonl-out PATH` | one JSON summary row per case |
| `--allow-non-loopback-http` | explicit lab override for non-loopback plain HTTP |

### What the script reports

Each `CASE` prints one JSON row. Key fields:

- `success`, `failures`, `sample_error`, `wall_time_s`, `usage_response_count`
- `p50_latency_s`, `p90_latency_s`, `p95_latency_s`, `p99_latency_s`, `avg_latency_s`
- `p50_ttft_s`, `p95_ttft_s`, `avg_ttft_s` (streaming mode only)
- `prompt_tok_per_sec`, `completion_tok_per_sec`, `total_tok_per_sec`
- `request_per_sec`

The final `SUMMARY_JSON` block contains all case rows. Exit code `0` when all
cases succeed, `1` when any request failed, `2` on config/validation errors.

Prioritize:

1. `failures` should be `0`
2. `p95_ttft_s` and `p95_latency_s` at target concurrency
3. `completion_tok_per_sec` for decode throughput
4. latency growth as `context_tokens_target` and `concurrency` increase

Percentiles use nearest-rank on small samples. `context_tokens_target` is
approximate; server `usage` fields and vLLM `/metrics` are authoritative for
actual token counts.

## vLLM Serving Benchmark

Use the vLLM CLI installed with the packaged runtime:

```bash
/opt/vllm/venv/bin/vllm bench serve --help
```

Direct vLLM baseline (matches the measured A6000 report):

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

LiteLLM production path (same workload, swap base URL):

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

Important:

- `--model` must match the **served model id** (`gemma-4-31B-it` in this build).
- `--tokenizer` must point to the **local model directory**
  (`/opt/models/gemma-4-31B-it`), not the served name.
- `--endpoint /v1/chat/completions` is required for `--backend openai-chat`.
- If weights live elsewhere, use the same path as `vllm.service` `--model=...`.

vLLM bench adds tokenizer-accurate lengths, request-rate and burstiness
simulation, richer percentiles/goodput, and ShareGPT/random/custom datasets.

## Live Monitoring During A Run

```bash
watch -n 1 nvidia-smi
curl -sS http://127.0.0.1:8000/metrics
sudo journalctl -u vllm -f
sudo journalctl -u litellm -f
```

Watch for:

| Signal | Healthy | Investigate |
|--------|---------|-------------|
| GPU util | high during active cases | stays near 0 while requests run |
| VRAM | stable below cap | sudden drops or process restarts |
| `num_requests_waiting` | low or zero at low concurrency | sustained growth under load |
| `kv_cache_usage_perc` | moderate for tested contexts | climbs toward saturation |
| `http_requests_total{status="5xx"}` | 0 | any 5xx during benchmark |
| `request_success_total{finished_reason="error"}` | 0 | any errors |

Metric names may differ by vLLM version; grep `/metrics` on the host if a
label is missing.

## Validation And Rollout

1. Confirm services are healthy:
   ```bash
   curl -sS http://127.0.0.1:8000/health
   curl -sS http://127.0.0.1:4000/v1/models
   ```
2. Run a small repo-script case:
   ```bash
   python3 scripts/benchmark_inference_server.py \
     --config-env /etc/notable-analyzer/config.env \
     --requests 8 \
     --concurrency 1 \
     --contexts 512 \
     --max-tokens 128
   ```
3. Run the full matrix or a vLLM bench case matching your target workload.
4. Compare direct-vLLM results to the measured profile baseline when sizing on
   A6000-class hardware.
5. Review failures before trusting throughput numbers.
6. Change one setting, then re-run the same case:
   - `CONCURRENCY_ENABLED`, `MAX_WORKERS`, `MAX_QUEUE_DEPTH`
   - vLLM `--max-num-seqs`
   - `LLM_TIMEOUT`

Repo unit tests for script helper logic:

```bash
cd /path/to/llm_notable_analysis_onprem_systemd
python3 -m unittest discover -s tests -p "test_benchmark_inference_server.py" -v
```

## Config Quick Reference

| Area | Primary inputs |
|------|----------------|
| Repo script | `scripts/benchmark_inference_server.py` in repo checkout |
| Script defaults | `/etc/notable-analyzer/config.env` (`LLM_API_URL`, `LLM_MODEL_NAME`, `LLM_API_TOKEN`) |
| LiteLLM path | `http://127.0.0.1:4000/v1/chat/completions` |
| vLLM path | `http://127.0.0.1:8000/v1/chat/completions` |
| vLLM metrics | `http://127.0.0.1:8000/metrics` |
| vLLM bench CLI | `/opt/vllm/venv/bin/vllm bench serve` |
| Analyzer concurrency | `CONCURRENCY_ENABLED`, `MAX_WORKERS`, `MAX_QUEUE_DEPTH` |

## Related Docs

- [`LLM_INFERENCE_OPERATIONS.md`](LLM_INFERENCE_OPERATIONS.md)
- [`deployment/deployment_profiles/README.md`](../deployment/deployment_profiles/README.md)
- [`deployment/deployment_profiles/a6000-96gb-ultra9-285k.md`](../deployment/deployment_profiles/a6000-96gb-ultra9-285k.md)
- [`deployment/deployment_profiles/a6000-96gb-ultra9-285k-vllm-benchmark-2026-05-28.md`](../deployment/deployment_profiles/a6000-96gb-ultra9-285k-vllm-benchmark-2026-05-28.md)
- [`platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](../platform/FILE_DROP_AND_RETENTION_OPERATIONS.md)
- [`deployment/INSTALL.md`](../deployment/INSTALL.md)
