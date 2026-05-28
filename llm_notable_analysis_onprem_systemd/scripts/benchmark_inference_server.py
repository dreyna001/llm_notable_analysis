#!/usr/bin/env python3
"""Benchmark an OpenAI-compatible local LLM inference endpoint.

This script intentionally bypasses the notable-analysis application. It sends
synthetic chat-completion requests directly to the configured LLM endpoint and
reports serving metrics for the inference stack: HTTP, proxy, tokenizer,
prefill, decode, queueing, and response serialization.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import shlex
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any

DEFAULT_CONFIG_ENV = "/etc/notable-analyzer/config.env"
DEFAULT_URL = "http://127.0.0.1:4000/v1/chat/completions"
DEFAULT_MODEL = "gemma-4-31B-it"


@dataclass(frozen=True)
class BenchmarkCase:
    concurrency: int
    requests: int
    context_tokens_target: int
    max_tokens: int


def read_config_env(path: str) -> dict[str, str]:
    """Read simple KEY=VALUE or export KEY=VALUE lines from config.env."""
    config_path = Path(path)
    if not config_path.exists():
        return {}

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        config_path.read_text(encoding="utf-8").splitlines(), 1
    ):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            tokens = shlex.split(stripped, comments=True, posix=True)
        except ValueError as exc:
            raise ValueError(f"Invalid config line {line_number}: {exc}") from exc
        if tokens and tokens[0] == "export":
            tokens = tokens[1:]
        if len(tokens) != 1 or "=" not in tokens[0]:
            raise ValueError(
                f"Invalid config line {line_number}: expected KEY=VALUE."
            )
        key, value = tokens[0].split("=", 1)
        if not key.isidentifier():
            raise ValueError(f"Invalid config line {line_number}: invalid key {key!r}.")
        values[key] = value
    return values


def parse_int_list(raw: str, *, name: str) -> list[int]:
    values: list[int] = []
    for part in raw.split(","):
        stripped = part.strip()
        if not stripped:
            continue
        try:
            value = int(stripped)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"{name} must be a comma-separated list of integers."
            ) from exc
        if value <= 0:
            raise argparse.ArgumentTypeError(f"{name} values must be positive.")
        values.append(value)
    if not values:
        raise argparse.ArgumentTypeError(f"{name} must include at least one value.")
    return values


def percentile(values: list[float], pct: float) -> float | None:
    """Return the nearest-rank percentile for small benchmark samples."""
    if not values:
        return None
    if not 0 <= pct <= 1:
        raise ValueError("pct must be between 0 and 1")
    sorted_values = sorted(values)
    rank = max(1, math.ceil(pct * len(sorted_values)))
    return sorted_values[rank - 1]


def round_optional(value: float | None, digits: int = 3) -> float | None:
    return round(value, digits) if value is not None else None


def make_prompt(context_tokens: int, request_index: int, vary_prompt: bool) -> str:
    """Build synthetic context with approximate token length and optional variance."""
    # Without a tokenizer, 0.75 words per token is only a sizing target. The
    # endpoint usage fields are the source of truth in the benchmark output.
    approx_words = max(1, int(context_tokens * 0.75))
    words_per_sentence = 11
    sentence_count = max(1, math.ceil(approx_words / words_per_sentence))
    marker = f"request-{request_index:06d}" if vary_prompt else "static"
    words: list[str] = []

    for idx in range(sentence_count):
        # Include the request marker throughout the prompt so prefix caching does
        # not dominate results unless the operator intentionally disables variance.
        sentence = (
            f"{marker} segment-{idx:05d} synthetic local inference benchmark "
            "context describes benign security telemetry and analyst notes."
        )
        words.extend(sentence.split())

    context = " ".join(words[:approx_words])
    return (
        "You are testing local LLM inference serving performance.\n\n"
        "Context:\n"
        f"{context}\n\n"
        "Task:\n"
        "Summarize the context, list five technical observations, and provide "
        "a concise conclusion. Do not mention benchmark internals."
    )


def is_loopback_http(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "http":
        return True
    host = parsed.hostname or ""
    return host in {"127.0.0.1", "localhost", "::1"}


def build_headers(token: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def truncate_error(raw: str, limit: int = 500) -> str:
    normalized = raw.replace("\n", " ").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def usage_from_payload(payload: dict[str, Any]) -> dict[str, int | None]:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
    return {
        "prompt_tokens": int(usage["prompt_tokens"])
        if isinstance(usage.get("prompt_tokens"), int)
        else None,
        "completion_tokens": int(usage["completion_tokens"])
        if isinstance(usage.get("completion_tokens"), int)
        else None,
        "total_tokens": int(usage["total_tokens"])
        if isinstance(usage.get("total_tokens"), int)
        else None,
    }


def post_nonstream(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: float,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            headers_at = time.perf_counter()
            raw = resp.read()
            end = time.perf_counter()
            body = json.loads(raw.decode("utf-8"))
            usage = usage_from_payload(body)
            choices = body.get("choices") if isinstance(body, dict) else None
            return {
                "ok": True,
                "status": getattr(resp, "status", None),
                "latency_s": end - start,
                "ttft_s": None,
                "time_to_headers_s": headers_at - start,
                "output_chars": len(json.dumps(choices)) if choices else 0,
                "error": None,
                **usage,
            }
    except urllib.error.HTTPError as exc:
        end = time.perf_counter()
        detail = exc.read().decode("utf-8", errors="replace")
        return request_error_result(
            start=start,
            end=end,
            status=exc.code,
            error=f"HTTP {exc.code}: {truncate_error(detail)}",
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        end = time.perf_counter()
        return request_error_result(start=start, end=end, status=None, error=str(exc))


def post_stream(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: float,
) -> dict[str, Any]:
    stream_payload = dict(payload)
    stream_payload["stream"] = True
    stream_payload["stream_options"] = {"include_usage": True}

    data = json.dumps(stream_payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    start = time.perf_counter()
    ttft: float | None = None
    output_chars = 0
    usage = {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}

    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            headers_at = time.perf_counter()
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue
                data_line = line[5:].strip()
                if data_line == "[DONE]":
                    break
                event = json.loads(data_line)
                event_usage = usage_from_payload(event)
                if event_usage["total_tokens"] is not None:
                    usage = event_usage
                choices = event.get("choices")
                if isinstance(choices, list) and choices:
                    delta = choices[0].get("delta")
                    if isinstance(delta, dict):
                        content = delta.get("content")
                        if isinstance(content, str) and content:
                            if ttft is None:
                                ttft = time.perf_counter() - start
                            output_chars += len(content)
            end = time.perf_counter()
            return {
                "ok": True,
                "status": getattr(resp, "status", None),
                "latency_s": end - start,
                "ttft_s": ttft,
                "time_to_headers_s": headers_at - start,
                "output_chars": output_chars,
                "error": None,
                **usage,
            }
    except urllib.error.HTTPError as exc:
        end = time.perf_counter()
        detail = exc.read().decode("utf-8", errors="replace")
        return request_error_result(
            start=start,
            end=end,
            status=exc.code,
            error=f"HTTP {exc.code}: {truncate_error(detail)}",
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        end = time.perf_counter()
        return request_error_result(start=start, end=end, status=None, error=str(exc))


def request_error_result(
    *,
    start: float,
    end: float,
    status: int | None,
    error: str,
) -> dict[str, Any]:
    return {
        "ok": False,
        "status": status,
        "latency_s": end - start,
        "ttft_s": None,
        "time_to_headers_s": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "output_chars": 0,
        "error": truncate_error(error),
    }


def summarize_case(case: BenchmarkCase, wall_time_s: float, results: list[dict[str, Any]]) -> dict[str, Any]:
    oks = [result for result in results if result["ok"]]
    fails = [result for result in results if not result["ok"]]
    latencies = [float(result["latency_s"]) for result in oks]
    ttfts = [float(result["ttft_s"]) for result in oks if result["ttft_s"] is not None]
    prompt_tokens = sum(
        int(result["prompt_tokens"]) for result in oks if result["prompt_tokens"] is not None
    )
    completion_tokens = sum(
        int(result["completion_tokens"])
        for result in oks
        if result["completion_tokens"] is not None
    )
    total_tokens = sum(
        int(result["total_tokens"]) for result in oks if result["total_tokens"] is not None
    )
    usage_response_count = sum(1 for result in oks if result["total_tokens"] is not None)
    output_chars = sum(int(result["output_chars"]) for result in oks)

    return {
        "concurrency": case.concurrency,
        "requests": case.requests,
        "context_tokens_target": case.context_tokens_target,
        "max_tokens": case.max_tokens,
        "success": len(oks),
        "failures": len(fails),
        "usage_response_count": usage_response_count,
        "wall_time_s": round(wall_time_s, 3),
        "request_per_sec": round(len(oks) / wall_time_s, 3) if wall_time_s > 0 else None,
        "avg_latency_s": round_optional(mean(latencies) if latencies else None),
        "p50_latency_s": round_optional(median(latencies) if latencies else None),
        "p90_latency_s": round_optional(percentile(latencies, 0.90)),
        "p95_latency_s": round_optional(percentile(latencies, 0.95)),
        "p99_latency_s": round_optional(percentile(latencies, 0.99)),
        "avg_ttft_s": round_optional(mean(ttfts) if ttfts else None),
        "p50_ttft_s": round_optional(median(ttfts) if ttfts else None),
        "p95_ttft_s": round_optional(percentile(ttfts, 0.95)),
        "prompt_tokens": prompt_tokens if usage_response_count else None,
        "completion_tokens": completion_tokens if usage_response_count else None,
        "total_tokens": total_tokens if usage_response_count else None,
        "prompt_tok_per_sec": round(prompt_tokens / wall_time_s, 3)
        if usage_response_count and wall_time_s > 0
        else None,
        "completion_tok_per_sec": round(completion_tokens / wall_time_s, 3)
        if usage_response_count and wall_time_s > 0
        else None,
        "total_tok_per_sec": round(total_tokens / wall_time_s, 3)
        if usage_response_count and wall_time_s > 0
        else None,
        "output_chars": output_chars,
        "sample_error": fails[0]["error"] if fails else None,
    }


def run_case(
    *,
    url: str,
    model: str,
    token: str | None,
    case: BenchmarkCase,
    timeout_seconds: float,
    temperature: float,
    stream: bool,
    vary_prompt: bool,
) -> dict[str, Any]:
    headers = build_headers(token)
    worker = post_stream if stream else post_nonstream
    start = time.perf_counter()
    results: list[dict[str, Any]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=case.concurrency) as executor:
        futures = []
        for request_index in range(case.requests):
            prompt = make_prompt(
                case.context_tokens_target,
                request_index=request_index,
                vary_prompt=vary_prompt,
            )
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": case.max_tokens,
                "temperature": temperature,
                "stream": stream,
            }
            futures.append(
                executor.submit(worker, url, payload, headers, timeout_seconds)
            )
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    wall_time_s = time.perf_counter() - start
    return summarize_case(case, wall_time_s, results)


def make_cases(
    *,
    requests: int,
    concurrency_values: list[int],
    context_values: list[int],
    max_token_values: list[int],
) -> list[BenchmarkCase]:
    cases: list[BenchmarkCase] = []
    for context_tokens in context_values:
        for max_tokens in max_token_values:
            for concurrency in concurrency_values:
                cases.append(
                    BenchmarkCase(
                        concurrency=concurrency,
                        requests=max(requests, concurrency),
                        context_tokens_target=context_tokens,
                        max_tokens=max_tokens,
                    )
                )
    return cases


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark the local OpenAI-compatible LLM serving endpoint without "
            "running the notable-analysis application."
        )
    )
    parser.add_argument(
        "--config-env",
        default=os.getenv("CONFIG_ENV", DEFAULT_CONFIG_ENV),
        help=f"config.env path used for defaults (default: {DEFAULT_CONFIG_ENV})",
    )
    parser.add_argument("--url", help="Full /v1/chat/completions URL")
    parser.add_argument("--model", help="Model name sent in the request payload")
    parser.add_argument(
        "--token",
        help="Bearer token. Prefer LLM_API_TOKEN in config.env or environment.",
    )
    parser.add_argument("--requests", type=int, default=32)
    parser.add_argument("--concurrency", default="1,2,4,8")
    parser.add_argument("--contexts", default="512,2048,8192,16000")
    parser.add_argument("--max-tokens", default="128,512")
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument(
        "--mode",
        choices=("stream", "nonstream"),
        default="stream",
        help="stream measures TTFT; nonstream is useful if streaming usage is unsupported",
    )
    parser.add_argument(
        "--static-prompt",
        action="store_true",
        help="Reuse the same prompt for every request, allowing prefix-cache effects.",
    )
    parser.add_argument(
        "--warmup-requests",
        type=int,
        default=1,
        help="Requests to run before measured cases for each context/max_tokens pair.",
    )
    parser.add_argument(
        "--allow-non-loopback-http",
        action="store_true",
        help="Allow plain HTTP endpoints outside localhost or 127.0.0.1.",
    )
    parser.add_argument(
        "--jsonl-out",
        help="Optional path to write one JSON summary row per measured case.",
    )
    return parser.parse_args(argv)


def resolve_endpoint(args: argparse.Namespace) -> tuple[str, str, str | None]:
    config = read_config_env(args.config_env)
    url = args.url or os.getenv("LLM_API_URL") or config.get("LLM_API_URL") or DEFAULT_URL
    model = (
        args.model
        or os.getenv("LLM_MODEL_NAME")
        or config.get("LLM_MODEL_NAME")
        or DEFAULT_MODEL
    )
    token = args.token or os.getenv("LLM_API_TOKEN") or config.get("LLM_API_TOKEN") or None
    return url, model, token


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        url, model, token = resolve_endpoint(args)
        concurrency_values = parse_int_list(args.concurrency, name="--concurrency")
        context_values = parse_int_list(args.contexts, name="--contexts")
        max_token_values = parse_int_list(args.max_tokens, name="--max-tokens")
        if args.requests <= 0:
            raise ValueError("--requests must be positive.")
        if args.warmup_requests < 0:
            raise ValueError("--warmup-requests must be zero or greater.")
        if args.timeout_seconds <= 0:
            raise ValueError("--timeout-seconds must be positive.")
    except (ValueError, argparse.ArgumentTypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not args.allow_non_loopback_http and not is_loopback_http(url):
        print(
            "ERROR: refusing non-loopback plain HTTP endpoint. Use HTTPS, a "
            "loopback URL, or --allow-non-loopback-http for an explicit lab run.",
            file=sys.stderr,
        )
        return 2

    stream = args.mode == "stream"
    cases = make_cases(
        requests=args.requests,
        concurrency_values=concurrency_values,
        context_values=context_values,
        max_token_values=max_token_values,
    )
    rows: list[dict[str, Any]] = []
    jsonl_file = open(args.jsonl_out, "w", encoding="utf-8") if args.jsonl_out else None

    try:
        print(f"Endpoint: {url}")
        print(f"Model: {model}")
        print(f"Mode: {args.mode}")
        print(f"Prompt variance: {'off' if args.static_prompt else 'on'}")
        print("Note: context token targets are approximate; usage fields are authoritative.")

        warmup_contexts = [(ctx, mt) for ctx in context_values for mt in max_token_values]
        for context_tokens, max_tokens in warmup_contexts:
            if args.warmup_requests <= 0:
                continue
            warmup_case = BenchmarkCase(
                concurrency=1,
                requests=args.warmup_requests,
                context_tokens_target=context_tokens,
                max_tokens=max_tokens,
            )
            print(
                "\nWARMUP "
                f"requests={warmup_case.requests} ctx={context_tokens} max_tokens={max_tokens}"
            )
            run_case(
                url=url,
                model=model,
                token=token,
                case=warmup_case,
                timeout_seconds=args.timeout_seconds,
                temperature=args.temperature,
                stream=stream,
                vary_prompt=not args.static_prompt,
            )

        for case in cases:
            print(
                "\nCASE "
                f"concurrency={case.concurrency} requests={case.requests} "
                f"ctx={case.context_tokens_target} max_tokens={case.max_tokens}"
            )
            row = run_case(
                url=url,
                model=model,
                token=token,
                case=case,
                timeout_seconds=args.timeout_seconds,
                temperature=args.temperature,
                stream=stream,
                vary_prompt=not args.static_prompt,
            )
            rows.append(row)
            encoded = json.dumps(row, sort_keys=True)
            print(encoded)
            if jsonl_file:
                jsonl_file.write(encoded + "\n")
                jsonl_file.flush()

        print("\nSUMMARY_JSON")
        print(json.dumps(rows, indent=2, sort_keys=True))
    finally:
        if jsonl_file:
            jsonl_file.close()

    failures = sum(int(row["failures"]) for row in rows)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
