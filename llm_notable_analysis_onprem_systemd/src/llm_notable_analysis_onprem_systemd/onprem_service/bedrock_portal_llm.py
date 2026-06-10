"""Bedrock Runtime chat transport for portal answer synthesis."""

from __future__ import annotations

import logging
from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError, ProfileNotFound

from .config import Config

logger = logging.getLogger(__name__)

_DEFAULT_READ_TIMEOUT_SECONDS = 300
_DEFAULT_CONNECT_TIMEOUT_SECONDS = 10


class BedrockPortalLlmError(RuntimeError):
    """Non-retryable Bedrock portal chat failure."""


class BedrockPortalLlmTimeoutError(BedrockPortalLlmError):
    """Bedrock portal chat request timed out."""


class BedrockPortalLlmUnavailableError(BedrockPortalLlmError):
    """Bedrock portal chat service unavailable."""


def _bedrock_region(config: Config) -> str:
    region = str(config.BEDROCK_REGION or config.AWS_REGION or "us-east-1").strip()
    if not region:
        raise BedrockPortalLlmError("BEDROCK_REGION or AWS_REGION must be set for Bedrock")
    return region


def _bedrock_timeouts(config: Config) -> tuple[int, int]:
    read_timeout = max(30, min(int(config.BEDROCK_READ_TIMEOUT_SECONDS), 900))
    connect_timeout = max(1, min(int(config.BEDROCK_CONNECT_TIMEOUT_SECONDS), 60))
    return read_timeout, connect_timeout


def _bedrock_aws_profile(config: Config) -> str | None:
    """Return the shared-credentials profile for Bedrock, if configured."""
    for candidate in (config.BEDROCK_AWS_PROFILE, config.AWS_PROFILE):
        value = str(candidate or "").strip()
        if value:
            return value
    return None


def _bedrock_runtime_client(config: Config) -> Any:
    read_timeout, connect_timeout = _bedrock_timeouts(config)
    client_kwargs = {
        "region_name": _bedrock_region(config),
        "config": BotoConfig(
            read_timeout=read_timeout,
            connect_timeout=connect_timeout,
        ),
    }
    profile = _bedrock_aws_profile(config)
    if profile:
        return boto3.Session(profile_name=profile).client("bedrock-runtime", **client_kwargs)
    return boto3.client("bedrock-runtime", **client_kwargs)


def _extract_converse_text(response: dict[str, Any]) -> str:
    output = response.get("output")
    if not isinstance(output, dict):
        raise BedrockPortalLlmError("Bedrock response missing output object")
    message = output.get("message")
    if not isinstance(message, dict):
        raise BedrockPortalLlmError("Bedrock response missing message object")
    content_blocks = message.get("content")
    if not isinstance(content_blocks, list):
        raise BedrockPortalLlmError("Bedrock response missing content blocks")

    text_parts: list[str] = []
    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            text_parts.append(text.strip())
    if not text_parts:
        raise BedrockPortalLlmError("Bedrock response contained no text content")
    return "\n".join(text_parts)


def _map_bedrock_error(exc: Exception) -> BedrockPortalLlmError:
    if isinstance(exc, ProfileNotFound):
        return BedrockPortalLlmUnavailableError(
            "AWS credentials profile was not found. Check BEDROCK_AWS_PROFILE or AWS_PROFILE."
        )
    if isinstance(exc, NoCredentialsError):
        return BedrockPortalLlmUnavailableError(
            "AWS credentials were not found for Bedrock. Configure a profile or instance role."
        )
    if isinstance(exc, ClientError):
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"AccessDeniedException", "UnauthorizedException"}:
            return BedrockPortalLlmUnavailableError(
                f"Bedrock access denied ({code}). Check IAM policy and model access."
            )
        if code in {"ThrottlingException", "TooManyRequestsException"}:
            return BedrockPortalLlmUnavailableError(
                f"Bedrock rate limit reached ({code})"
            )
        if code in {"ModelTimeoutException", "RequestTimeout", "RequestTimeoutException"}:
            return BedrockPortalLlmTimeoutError(f"Bedrock request timed out ({code})")
        return BedrockPortalLlmUnavailableError(
            f"Bedrock request failed ({code or 'ClientError'})"
        )
    if isinstance(exc, BotoCoreError):
        message = str(exc).lower()
        if "timeout" in message or "timed out" in message:
            return BedrockPortalLlmTimeoutError("Bedrock request timed out")
        return BedrockPortalLlmUnavailableError("Bedrock transport failure")
    return BedrockPortalLlmError(str(exc))


def bedrock_chat_complete(
    config: Config,
    *,
    prompt: str,
    max_tokens: int,
    temperature: float = 0.0,
) -> str:
    """Run a single-turn Bedrock Converse call and return assistant text."""
    model_id = str(config.PORTAL_BEDROCK_MODEL_ID or "").strip()
    if not model_id:
        raise BedrockPortalLlmError(
            "PORTAL_BEDROCK_MODEL_ID is required when PORTAL_LLM_PROVIDER=bedrock"
        )
    if not str(prompt or "").strip():
        raise BedrockPortalLlmError("prompt must be non-empty")

    try:
        response = _bedrock_runtime_client(config).converse(
            modelId=model_id,
            messages=[
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ],
            inferenceConfig={
                "maxTokens": max(1, int(max_tokens)),
                "temperature": float(temperature),
            },
        )
    except Exception as exc:
        logger.exception("Bedrock portal chat request failed")
        raise _map_bedrock_error(exc) from exc

    return _extract_converse_text(response)


def probe_bedrock_reachable(config: Config) -> bool:
    """Lightweight Bedrock ping for portal readiness checks."""
    try:
        bedrock_chat_complete(
            config,
            prompt="portal readiness ping",
            max_tokens=1,
            temperature=0.0,
        )
        return True
    except BedrockPortalLlmError:
        logger.exception("Bedrock readiness probe failed")
        return False
