"""Interactive playground for the public onprem-llm-sdk surface.

This script demonstrates:
- Environment-driven config loading and explicit overrides.
- VLLMClient usage with explicit and auto-generated correlation IDs.
- Per-call timeout, token, and temperature overrides.
- Typed exception handling.
- Optional custom logger and metrics sink wiring.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from dataclasses import dataclass, field
from threading import Lock
from typing import List

import requests

from onprem_llm_sdk import (
    ClientRequestError,
    ConfigError,
    RateLimitError,
    RequestTimeoutError,
    ResponseFormatError,
    SDKConfig,
    ServerError,
    TransportError,
    VLLMClient,
)


@dataclass
class PlaygroundMetricsSink:
    """Thread-safe metrics sink used for demonstration output."""

    request_count: int = 0
    success_count: int = 0
    error_count: int = 0
    current_inflight: int = 0
    max_observed_inflight: int = 0
    request_events: List[dict] = field(default_factory=list)

    _lock: Lock = field(default_factory=Lock)

    def record_inflight(self, *, app_name: str, inflight: int) -> None:
        """Store inflight gauge values emitted by the SDK."""
        del app_name
        with self._lock:
            self.current_inflight = inflight
            if inflight > self.max_observed_inflight:
                self.max_observed_inflight = inflight

    def record_request_result(
        self,
        *,
        app_name: str,
        success: bool,
        status_code: int,
        attempts: int,
        latency_seconds: float,
        error_type: str = "",
    ) -> None:
        """Store terminal request events emitted by the SDK."""
        with self._lock:
            self.request_count += 1
            if success:
                self.success_count += 1
            else:
                self.error_count += 1
            self.request_events.append(
                {
                    "app_name": app_name,
                    "success": success,
                    "status_code": status_code,
                    "attempts": attempts,
                    "latency_seconds": round(latency_seconds, 6),
                    "error_type": error_type,
                }
            )


def build_logger() -> logging.Logger:
    """Create a console logger so SDK structured events are visible."""
    logger = logging.getLogger("onprem_llm_sdk_playground")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger


def run_call(
    client: VLLMClient,
    *,
    prompt: str,
    max_tokens: int,
    temperature: float,
    correlation_id: str | None,
    connect_timeout_sec: float,
    read_timeout_sec: float,
) -> None:
    """Run one completion call and print normalized result details."""
    result = client.complete(
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        correlation_id=correlation_id,
        connect_timeout_sec=connect_timeout_sec,
        read_timeout_sec=read_timeout_sec,
    )
    print(
        json.dumps(
            {
                "text_preview": result.text[:220],
                "status_code": result.status_code,
                "attempts": result.attempts,
                "latency_seconds": round(result.latency_seconds, 6),
                "correlation_id": result.correlation_id,
                "raw_response_keys": sorted(result.raw_response.keys()),
            },
            indent=2,
        )
    )


def parse_args() -> argparse.Namespace:
    """Parse CLI options for easy local experimentation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prompt",
        default="Summarize this notable in one sentence with a confidence statement.",
        help="Prompt for the first call.",
    )
    parser.add_argument(
        "--json-prompt",
        default='Return JSON only: {"status":"ok","summary":"short"}',
        help="Prompt for the second call.",
    )
    parser.add_argument(
        "--app-name",
        default="sdk-playground",
        help="Override app identity for X-LLM-App header.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=512,
        help="Per-call max_tokens override used for both calls.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.1,
        help="Per-call temperature override used for first call.",
    )
    parser.add_argument(
        "--connect-timeout-sec",
        type=float,
        default=None,
        help="Per-call connect timeout override (seconds).",
    )
    parser.add_argument(
        "--read-timeout-sec",
        type=float,
        default=None,
        help="Per-call read timeout override (seconds).",
    )
    parser.add_argument(
        "--explicit-correlation-id",
        default=None,
        help="Explicit ID for first call; defaults to generated demo UUID.",
    )
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Print resolved SDK configuration before calls.",
    )
    return parser.parse_args()


def main() -> int:
    """Run two calls that exercise major public SDK behaviors."""
    args = parse_args()

    if args.max_tokens < 1:
        print("max_tokens must be >= 1")
        return 2

    logger = build_logger()
    metrics = PlaygroundMetricsSink()

    try:
        cfg = SDKConfig.from_env(
            overrides={
                "llm_app_name": args.app_name,
                "llm_max_tokens_default": args.max_tokens,
            }
        )
    except ConfigError as exc:
        print(f"[CONFIG ERROR] {exc}")
        return 3

    if args.show_config:
        print(
            json.dumps(
                {
                    "llm_api_url": cfg.llm_api_url,
                    "llm_model_name": cfg.llm_model_name,
                    "llm_app_name": cfg.llm_app_name,
                    "llm_max_tokens_default": cfg.llm_max_tokens_default,
                    "llm_connect_timeout_sec": cfg.llm_connect_timeout_sec,
                    "llm_read_timeout_sec": cfg.llm_read_timeout_sec,
                    "llm_max_retries": cfg.llm_max_retries,
                    "llm_retry_backoff_sec": cfg.llm_retry_backoff_sec,
                    "llm_max_inflight": cfg.llm_max_inflight,
                    "llm_verify_tls": cfg.llm_verify_tls,
                },
                indent=2,
            )
        )

    client = VLLMClient(
        cfg,
        session=requests.Session(),
        metrics_sink=metrics,
        logger=logger,
    )

    connect_timeout = (
        args.connect_timeout_sec
        if args.connect_timeout_sec is not None
        else cfg.llm_connect_timeout_sec
    )
    read_timeout = (
        args.read_timeout_sec
        if args.read_timeout_sec is not None
        else cfg.llm_read_timeout_sec
    )
    explicit_corr = args.explicit_correlation_id or f"demo-{uuid.uuid4()}"

    try:
        print("\n=== Call 1: explicit correlation ID ===")
        run_call(
            client,
            prompt=args.prompt,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            correlation_id=explicit_corr,
            connect_timeout_sec=connect_timeout,
            read_timeout_sec=read_timeout,
        )

        print("\n=== Call 2: auto-generated correlation ID ===")
        run_call(
            client,
            prompt=args.json_prompt,
            max_tokens=min(args.max_tokens, 256),
            temperature=0.0,
            correlation_id=None,
            connect_timeout_sec=connect_timeout,
            read_timeout_sec=read_timeout,
        )
    except ValueError as exc:
        print(f"[INPUT ERROR] {exc}")
        return 4
    except RequestTimeoutError as exc:
        print(f"[TIMEOUT] {exc}")
        return 5
    except TransportError as exc:
        print(f"[TRANSPORT] {exc}")
        return 6
    except RateLimitError as exc:
        print(f"[RATE LIMIT] {exc}")
        return 7
    except ServerError as exc:
        print(f"[SERVER ERROR] {exc}")
        return 8
    except ClientRequestError as exc:
        print(f"[CLIENT ERROR] status={exc.status_code} detail={exc}")
        return 9
    except ResponseFormatError as exc:
        print(f"[RESPONSE FORMAT ERROR] {exc}")
        return 10

    print("\n=== Metrics sink summary ===")
    print(
        json.dumps(
            {
                "request_count": metrics.request_count,
                "success_count": metrics.success_count,
                "error_count": metrics.error_count,
                "current_inflight": metrics.current_inflight,
                "max_observed_inflight": metrics.max_observed_inflight,
                "request_events": metrics.request_events,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
