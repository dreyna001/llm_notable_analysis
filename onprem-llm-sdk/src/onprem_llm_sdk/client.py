"""vLLM client implementation with retries, inflight guard, and observability."""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from threading import BoundedSemaphore, Lock
from typing import Dict, Generator, Optional

import requests

from .config import SDKConfig
from .contracts import (
    CompletionRequest,
    CompletionResult,
    parse_completion_text,
    parse_retry_after_seconds,
)
from .errors import (
    ClientRequestError,
    RateLimitError,
    RequestTimeoutError,
    ResponseFormatError,
    ServerError,
    TransportError,
)
from .logging import get_sdk_logger, log_event
from .metrics import MetricsSink, NoOpMetricsSink


class VLLMClient:
    """Reusable client for local OpenAI-compatible vLLM chat endpoint.

    The client enforces bounded in-flight concurrency, structured logging, metrics
    callbacks, and typed error mapping on top of OpenAI-compatible chat APIs.
    """

    def __init__(
        self,
        config: SDKConfig,
        *,
        session: Optional[requests.Session] = None,
        metrics_sink: Optional[MetricsSink] = None,
        logger: Optional[logging.Logger] = None,
        sleep_fn=time.sleep,
    ) -> None:
        """Initialize a vLLM client instance.

        Args:
            config: Validated SDK configuration.
            session: Optional requests-compatible session for HTTP calls.
            metrics_sink: Optional metrics sink implementation.
            logger: Optional logger instance for structured events.
            sleep_fn: Sleep function used for retry delays (injectable for tests).
        """
        self._config = config
        self._session = session or requests.Session()
        self._metrics = metrics_sink or NoOpMetricsSink()
        self._logger = logger or get_sdk_logger()
        self._sleep_fn = sleep_fn
        self._semaphore = BoundedSemaphore(config.llm_max_inflight)
        self._inflight_lock = Lock()
        self._inflight = 0

    @contextmanager
    def _inflight_slot(self) -> Generator[None, None, None]:
        """Acquire and release one inflight request slot.

        Yields:
            A context guard for one inflight request.
        """
        self._semaphore.acquire()
        with self._inflight_lock:
            self._inflight += 1
            self._metrics.record_inflight(
                app_name=self._config.llm_app_name,
                inflight=self._inflight,
            )
        try:
            yield
        finally:
            with self._inflight_lock:
                self._inflight -= 1
                self._metrics.record_inflight(
                    app_name=self._config.llm_app_name,
                    inflight=self._inflight,
                )
            self._semaphore.release()

    def _headers(self, correlation_id: str) -> Dict[str, str]:
        """Build request headers for outbound API calls.

        Args:
            correlation_id: Correlation identifier for request tracing.

        Returns:
            Header mapping to send with HTTP requests.
        """
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "X-Correlation-ID": correlation_id,
            "X-LLM-App": self._config.llm_app_name,
            "User-Agent": f"onprem-llm-sdk/{self._config.llm_app_name}",
        }
        if self._config.llm_api_token:
            headers["Authorization"] = f"Bearer {self._config.llm_api_token}"
        return headers

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
        correlation_id: Optional[str] = None,
        connect_timeout_sec: Optional[float] = None,
        read_timeout_sec: Optional[float] = None,
    ) -> CompletionResult:
        """Send a completion request with bounded retries and error mapping.

        Args:
            prompt: Prompt text to submit.
            max_tokens: Optional per-call max token override.
            temperature: Sampling temperature.
            correlation_id: Optional caller-provided correlation ID.
            connect_timeout_sec: Optional per-call connect timeout override.
            read_timeout_sec: Optional per-call read timeout override.

        Returns:
            Normalized completion result including text, timing, and metadata.

        Raises:
            ValueError: If prompt is empty.
            RequestTimeoutError: If retries are exhausted due to timeouts.
            TransportError: If retries are exhausted due to transport failures.
            ResponseFormatError: If response JSON/shape is invalid.
            RateLimitError: If endpoint returns 429 and retries are exhausted.
            ServerError: If endpoint returns 5xx and retries are exhausted.
            ClientRequestError: For non-retryable client errors (except 429).
        """
        if not prompt or not prompt.strip():
            raise ValueError("prompt must not be empty")

        req = CompletionRequest(
            model=self._config.llm_model_name,
            prompt=prompt,
            max_tokens=max_tokens or self._config.llm_max_tokens_default,
            temperature=temperature,
        )
        corr_id = correlation_id or str(uuid.uuid4())
        timeout = (
            connect_timeout_sec or self._config.llm_connect_timeout_sec,
            read_timeout_sec or self._config.llm_read_timeout_sec,
        )
        max_attempts = self._config.llm_max_retries + 1
        overall_start = time.perf_counter()

        with self._inflight_slot():
            for attempt in range(1, max_attempts + 1):
                try:
                    response = self._session.post(
                        self._config.llm_api_url,
                        json=req.to_payload(),
                        headers=self._headers(corr_id),
                        timeout=timeout,
                        verify=self._config.llm_verify_tls,
                    )
                except requests.exceptions.Timeout as exc:
                    if attempt < max_attempts:
                        self._retry_sleep(attempt)
                        continue
                    latency = time.perf_counter() - overall_start
                    self._record_failure(
                        status_code=0,
                        attempts=attempt,
                        latency_seconds=latency,
                        correlation_id=corr_id,
                        error_type="timeout",
                    )
                    raise RequestTimeoutError(
                        f"vLLM request timed out after {attempt} attempt(s)"
                    ) from exc
                except requests.exceptions.RequestException as exc:
                    if attempt < max_attempts:
                        self._retry_sleep(attempt)
                        continue
                    latency = time.perf_counter() - overall_start
                    self._record_failure(
                        status_code=0,
                        attempts=attempt,
                        latency_seconds=latency,
                        correlation_id=corr_id,
                        error_type="transport",
                    )
                    raise TransportError(
                        f"vLLM transport error after {attempt} attempt(s): {exc}"
                    ) from exc

                if 200 <= response.status_code < 300:
                    try:
                        response_json = response.json()
                        text = parse_completion_text(response_json)
                    except ValueError as exc:
                        latency = time.perf_counter() - overall_start
                        self._record_failure(
                            status_code=response.status_code,
                            attempts=attempt,
                            latency_seconds=latency,
                            correlation_id=corr_id,
                            error_type="response_json",
                        )
                        raise ResponseFormatError("Response is not valid JSON") from exc

                    latency = time.perf_counter() - overall_start
                    self._metrics.record_request_result(
                        app_name=self._config.llm_app_name,
                        success=True,
                        status_code=response.status_code,
                        attempts=attempt,
                        latency_seconds=latency,
                    )
                    log_event(
                        self._logger,
                        logging.INFO,
                        "llm_request_success",
                        app_name=self._config.llm_app_name,
                        correlation_id=corr_id,
                        attempts=attempt,
                        latency_seconds=round(latency, 6),
                        status_code=response.status_code,
                    )
                    return CompletionResult(
                        text=text,
                        raw_response=response_json,
                        latency_seconds=latency,
                        attempts=attempt,
                        correlation_id=corr_id,
                        status_code=response.status_code,
                    )

                body = response.text[:4000]
                error = self._error_for_http_status(response.status_code, body)
                retryable = self._is_retryable_status(response.status_code)
                if retryable and attempt < max_attempts:
                    self._retry_sleep(
                        attempt,
                        response.headers if response.status_code == 429 else None,
                    )
                    continue

                latency = time.perf_counter() - overall_start
                self._record_failure(
                    status_code=response.status_code,
                    attempts=attempt,
                    latency_seconds=latency,
                    correlation_id=corr_id,
                    error_type=type(error).__name__,
                )
                raise error

        raise RuntimeError("unreachable")

    def _record_failure(
        self,
        *,
        status_code: int,
        attempts: int,
        latency_seconds: float,
        correlation_id: str,
        error_type: str,
    ) -> None:
        """Record failure metrics and structured logs.

        Args:
            status_code: HTTP status code (0 when unavailable).
            attempts: Number of attempts made.
            latency_seconds: Total elapsed request latency.
            correlation_id: Correlation identifier for tracing.
            error_type: Normalized error category string.
        """
        self._metrics.record_request_result(
            app_name=self._config.llm_app_name,
            success=False,
            status_code=status_code,
            attempts=attempts,
            latency_seconds=latency_seconds,
            error_type=error_type,
        )
        log_event(
            self._logger,
            logging.ERROR,
            "llm_request_failure",
            app_name=self._config.llm_app_name,
            correlation_id=correlation_id,
            attempts=attempts,
            latency_seconds=round(latency_seconds, 6),
            status_code=status_code,
            error_type=error_type,
        )

    def _retry_sleep(self, attempt: int, headers: Optional[Dict[str, str]] = None) -> None:
        """Apply retry delay using Retry-After or exponential backoff.

        Args:
            attempt: One-based attempt number.
            headers: Optional response headers used to parse Retry-After.
        """
        retry_after = parse_retry_after_seconds(headers)
        if retry_after is None:
            retry_after = self._config.llm_retry_backoff_sec * (2 ** max(0, attempt - 1))
        if retry_after > 0:
            self._sleep_fn(retry_after)

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        """Return whether an HTTP status should be retried.

        Args:
            status_code: HTTP status code.

        Returns:
            True for retryable statuses; otherwise False.
        """
        return status_code == 429 or status_code >= 500

    @staticmethod
    def _error_for_http_status(status_code: int, body: str):
        """Map an HTTP status/body into a typed SDK exception.

        Args:
            status_code: HTTP response status code.
            body: Truncated response body for context.

        Returns:
            A typed SDK exception instance.
        """
        if status_code == 429:
            return RateLimitError(
                f"vLLM returned 429 rate limit: {body}",
                status_code=status_code,
                response_body=body,
            )
        if status_code >= 500:
            return ServerError(
                f"vLLM server error {status_code}: {body}",
                status_code=status_code,
                response_body=body,
            )
        return ClientRequestError(
            f"vLLM client error {status_code}: {body}",
            status_code=status_code,
            response_body=body,
        )
