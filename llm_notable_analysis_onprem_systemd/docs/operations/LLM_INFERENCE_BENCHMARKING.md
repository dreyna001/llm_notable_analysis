# LLM Inference Benchmarking

This guide helps operators measure local LLM serving performance without running
the notable-analysis application. Use it before raising analyzer concurrency,
`--max-num-seqs`, or other inference-related limits.

## What This Controls

Benchmarking here measures the **inference serving stack only**:

```text
HTTP client -> LiteLLM (127.0.0.1:4000) -> vLLM (127.0.0.1:8000) -> GPU
```

It does **not** measure:

- notable ingest or report generation
- RAG retrieval or reranking
- Splunk or Elasticsearch query execution
- parse/repair behavior in the analyzer

Treat benchmark results as **serving capacity and latency**, not end-to-end
notable throughput.

## Recommended Starting Posture

- Stop or idle `notable-analyzer` during inference benchmarks so GPU and queue
  capacity are not shared with production notable processing.
- Start with **concurrency=1**, then increase only after latency and failure
  rates look stable.
- Benchmark both paths when tuning production:
  - **LiteLLM path:** `http://127.0.0.1:4000` (what the analyzer uses)
  - **vLLM direct path:** `http://127.0.0.1:8000` (pure model-server baseline)
- Keep services on loopback unless a documented lab exception is approved.
- Change one serving or analyzer setting at a time between benchmark runs.

## Customer Decisions

### Which benchmark tool should I use?

| Tool | When to use |
|------|-------------|
| [`scripts/benchmark_inference_server.py`](../../scripts/benchmark_inference_server.py) | Quick operator benchmark from the repo checkout; stdlib only; reads `/etc/notable-analyzer/config.env` defaults |
| `vllm bench serve` in `/opt/vllm/venv` | Deeper serving benchmarks with tokenizer-accurate prompt lengths, request-rate control, and richer percentile metrics |

Use the repo script for fast smoke/load checks tied to deployment config. Use
vLLM bench for serious capacity planning and before changing `--max-num-seqs`,
`CONCURRENCY_ENABLED`, or `MAX_WORKERS`.

### Which endpoint should I benchmark?

- **Production-shaped path:** LiteLLM at `http://127.0.0.1:4000`
- **Model-server baseline:** vLLM at `http://127.0.0.1:8000`

If LiteLLM and vLLM numbers diverge materially, inspect LiteLLM logs before
blaming GPU or model settings.

### What workload shape should I test?

Start with shapes close to notable-analysis LLM calls:

| Dimension | Starting values | Why |
|-----------|-----------------|-----|
| Input context | 512, 2048, 8192 tokens | small alert vs RAG-heavy prompt sizes |
| Output cap | 128, 512 tokens | short structured sections vs longer outputs |
| Concurrency | 1, 2, 4 | matches conservative analyzer rollout on single-GPU hosts |
| Requests per case | 32+ | enough samples for p95 latency |

Our repo script uses approximate context sizing. vLLM bench uses tokenizer-based
length control and is authoritative for exact token counts.

## Repo Benchmark Script

### Where to run it

The installer copies application code to `/opt/notable-analyzer`, but **does not**
install `scripts/` there. Run the benchmark from a repo checkout on the host,
for example:

```bash
cd /path/to/llm_notable_analysis_onprem_systemd
python3 scripts/benchmark_inference_server.py \
  --config-env /etc/notable-analyzer/config.env
```

The script reads these defaults from `config.env` when flags are omitted:

- `LLM_API_URL`
- `LLM_MODEL_NAME`
- `LLM_API_TOKEN`

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
| `--mode stream` | default; measures real TTFT from streamed tokens |
| `--mode nonstream` | use if streaming usage is unsupported by the endpoint |
| `--static-prompt` | intentionally allow prefix-cache effects |
| `--warmup-requests 1` | warmup per context/output pair before measured cases |
| `--jsonl-out PATH` | write one JSON summary row per case |

### What the script reports

Each `CASE` prints one JSON row with:

- `success`, `failures`, `sample_error`
- `p50_latency_s`, `p95_latency_s`, `p99_latency_s`
- `p50_ttft_s`, `p95_ttft_s` (streaming mode)
- `prompt_tok_per_sec`, `completion_tok_per_sec`, `total_tok_per_sec`
- `request_per_sec`

The final `SUMMARY_JSON` block contains all case rows.

Prioritize:

1. `failures` should be `0`
2. `p95_ttft_s` and `p95_latency_s` at target concurrency
3. `completion_tok_per_sec` for decode throughput
4. latency growth as `context_tokens_target` and `concurrency` increase

Context targets in the script are approximate. Treat server `usage` token
fields and vLLM `/metrics` as authoritative for actual token counts.

## vLLM Serving Benchmark

For deeper benchmarking, use the vLLM CLI already installed with the packaged
runtime:

```bash
/opt/vllm/venv/bin/vllm bench serve --help
```

LiteLLM production path:

```bash
/opt/vllm/venv/bin/vllm bench serve \
  --backend openai-chat \
  --base-url http://127.0.0.1:4000 \
  --model gemma-4-31B-it \
  --dataset-name random \
  --random-input-len 2048 \
  --random-output-len 512 \
  --num-prompts 100 \
  --max-concurrency 4
```

Direct vLLM baseline:

```bash
/opt/vllm/venv/bin/vllm bench serve \
  --backend openai-chat \
  --base-url http://127.0.0.1:8000 \
  --model gemma-4-31B-it \
  --dataset-name random \
  --random-input-len 2048 \
  --random-output-len 512 \
  --num-prompts 100 \
  --max-concurrency 4
```

vLLM bench adds capabilities the repo script does not provide:

- tokenizer-accurate input/output lengths
- request-rate and burstiness simulation
- richer percentile and goodput reporting
- ShareGPT, random, and custom dataset modes

## Live Monitoring During A Run

Run these in separate terminals while benchmarking:

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

## Validation And Rollout

1. Confirm services are healthy:
   ```bash
   curl -sS http://127.0.0.1:8000/health
   curl -sS http://127.0.0.1:4000/v1/models
   ```
2. Run a small repo-script case first:
   ```bash
   python3 scripts/benchmark_inference_server.py \
     --config-env /etc/notable-analyzer/config.env \
     --requests 8 \
     --concurrency 1 \
     --contexts 512 \
     --max-tokens 128
   ```
3. Run the full matrix or a vLLM bench case matching your target workload.
4. Review failures before trusting throughput numbers.
5. Only then change one setting such as:
   - `CONCURRENCY_ENABLED`
   - `MAX_WORKERS`
   - vLLM `--max-num-seqs`
   - `LLM_TIMEOUT`
6. Re-run the same benchmark case to compare before/after.

Repo unit tests for the script helper logic:

```bash
python3 -m unittest discover \
  -s tests \
  -p "test_benchmark_inference_server.py" \
  -v
```

## Config Quick Reference

| Area | Primary inputs |
|------|----------------|
| Repo script location | `scripts/benchmark_inference_server.py` in repo checkout |
| Repo script defaults | `/etc/notable-analyzer/config.env` (`LLM_API_URL`, `LLM_MODEL_NAME`, `LLM_API_TOKEN`) |
| LiteLLM path | `http://127.0.0.1:4000/v1/chat/completions` |
| vLLM path | `http://127.0.0.1:8000/v1/chat/completions` |
| vLLM metrics | `http://127.0.0.1:8000/metrics` |
| vLLM bench CLI | `/opt/vllm/venv/bin/vllm bench serve` |
| Analyzer concurrency | `CONCURRENCY_ENABLED`, `MAX_WORKERS`, `MAX_QUEUE_DEPTH` |

## Related Docs

- [`LLM_INFERENCE_OPERATIONS.md`](LLM_INFERENCE_OPERATIONS.md)
- [`deployment_profiles/a6000-96gb-ultra9-285k.md`](deployment_profiles/a6000-96gb-ultra9-285k.md)
- [`FILE_DROP_AND_RETENTION_OPERATIONS.md`](FILE_DROP_AND_RETENTION_OPERATIONS.md)
- [`INSTALL.md`](INSTALL.md)
