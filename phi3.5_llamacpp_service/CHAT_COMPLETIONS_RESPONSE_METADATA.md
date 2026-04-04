# Chat completions response metadata (llama-server / Phi-3.5)

This project runs **llama.cpp `llama-server`**, which implements an **OpenAI-compatible** `POST /v1/chat/completions` API. Responses may include both **standard OpenAI-style fields** and **llama.cpp-specific** fields. Exact keys can vary slightly by **llama.cpp build/version**; when in doubt, inspect one real JSON response from your server.

**Upstream reference:** [llama.cpp `tools/server/README.md`](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) (sections on chat completions, timings, and metrics).

---

## Request field: `n`

- **`n`**: How many **independent completion choices** to return for the same prompt (OpenAI API). Default is **`1`**.
- Not specific to Phi-3.5; it is a client option. Higher **`n`** multiplies server work.

---

## Standard `usage` object (OpenAI-compatible)

Many clients expect a top-level **`usage`** object. Typical shape:

| Field | Meaning |
|--------|--------|
| **`prompt_tokens`** | Tokens counted toward the **input** side of the request (after chat template / formatting). Used for billing and capacity planning on cloud APIs; locally it is still a useful **input size** signal. |
| **`completion_tokens`** | Tokens in the **model’s reply** (the assistant message), i.e. **newly generated** tokens for that response. |
| **`total_tokens`** | Usually **`prompt_tokens + completion_tokens`** (and sometimes other internal accounting, depending on server). |

**Relationship to your limits**

- Server **`--ctx-size`**: caps **prompt + completion** that fit in the KV context for that slot (your deploy sets this, e.g. `16384`).
- Server **`--n-predict`**: caps **maximum generated tokens** per completion (along with the client’s `max_tokens`).
- So **effective max completion** is bounded by **`min(max_tokens, n_predict, ctx_remaining)`** after the prompt is tokenized.

If **`usage` is missing or zeros** in a given build, use **`timings`** (below) or **`GET /metrics`** for load debugging.

---

## llama.cpp `timings` object (often on chat completion responses)

llama-server often adds a top-level **`timings`** object for performance and rough context accounting. Example shape (from upstream docs):

| Field | Meaning |
|--------|--------|
| **`cache_n`** | Prompt tokens **reused from the KV cache** (prefix cache / slot reuse), so they were not fully recomputed. |
| **`prompt_n`** | Prompt tokens **processed** in this step (the non-cached portion; naming reflects server internals). |
| **`predicted_n`** | **Generated** tokens for this completion (output length in tokens). |
| **`prompt_ms`**, **`predicted_ms`** | Wall-time spent on prompt processing vs generation. |
| **`prompt_per_second`**, **`predicted_per_second`** | Throughput estimates for prefill vs decode. |

**Approximate relationship (from upstream documentation):**

```text
tokens in context ≈ prompt_n + cache_n + predicted_n
```

Use this to reason about **how full the context is** and whether you are approaching **`--ctx-size`**.

---

## Other llama.cpp / completion-style fields you may see

These appear in **non-chat** or extended completion payloads in some versions; chat responses may mirror some concepts:

| Field | Meaning |
|--------|--------|
| **`tokens_cached`** | Similar idea to cache reuse: tokens from the prompt that could be **reused** from a prior completion (wording varies by endpoint/version). |
| **`tokens_evaluated`** | **Total prompt tokens** evaluated for this request (see server docs for exact semantics vs `prompt_n`). |
| **`truncated`** | If **`true`**, context limits were hit: prompt length + generated length exceeded what fits in **`n_ctx`** / **`--ctx-size`**. |

---

## Prometheus `GET /metrics` (when `--metrics` is enabled)

Your systemd unit enables **`--metrics`**. Useful series include (names from upstream docs):

| Metric | Meaning |
|--------|--------|
| **`llamacpp:requests_processing`** | Requests currently being processed. |
| **`llamacpp:requests_deferred`** | Requests queued / deferred. |
| **`llamacpp:kv_cache_usage_ratio`** | KV cache fill level (**1** = 100%). |
| **`llamacpp:prompt_tokens_total`** / **`llamacpp:tokens_predicted_total`** | Cumulative token counters since process start. |

Use **`curl -sS http://127.0.0.1:8000/metrics`** on the host where `llama-server` listens.

---

## Phi-3.5-specific note

**Phi-3.5** does not define a separate metadata schema: token counts and timings come from **llama-server + GGUF tokenizer**, not from the model name. Tuning **`--ctx-size`**, **`--n-predict`**, and thread flags affects **latency and whether responses truncate**, not the *meaning* of these fields.

---

## Quick inspection commands

```bash
# One chat completion saved for inspection (adjust host/port/model)
curl -sS http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"YOUR_MODEL_ID","messages":[{"role":"user","content":"ping"}],"max_tokens":16,"temperature":0}' \
  | tee /tmp/llm_response.json

# Pretty-print if jq is available
jq . /tmp/llm_response.json
```
