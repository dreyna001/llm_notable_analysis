"""Preview-only Bedrock chat transport for portal UI development."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError, ProfileNotFound

from llm_notable_analysis_onprem_systemd.onprem_service.case_chat import (
    GeneralSynthesizeFn,
    SynthesizeFn,
    _build_general_knowledge_prompt,
    _build_prompt,
)

logger = logging.getLogger(__name__)


class BedrockPreviewLlmError(RuntimeError):
    """Non-retryable Bedrock preview chat failure."""


@dataclass(frozen=True)
class BedrockPreviewSettings:
    model_id: str
    aws_profile: str = ""
    aws_region: str = "us-east-1"
    bedrock_region: str = ""
    read_timeout_seconds: int = 300
    connect_timeout_seconds: int = 10


def resolve_bedrock_preview_settings() -> BedrockPreviewSettings | None:
    """Load preview Bedrock settings from the preview env file / process env."""
    provider = os.environ.get("PORTAL_LLM_PROVIDER", "local").strip().lower() or "local"
    model_id = (
        os.environ.get("PORTAL_PREVIEW_BEDROCK_MODEL_ID")
        or os.environ.get("PORTAL_BEDROCK_MODEL_ID")
        or ""
    ).strip()
    if provider != "bedrock" and not model_id:
        return None
    if not model_id:
        raise SystemExit(
            "Set PORTAL_PREVIEW_BEDROCK_MODEL_ID (or PORTAL_BEDROCK_MODEL_ID) when "
            "PORTAL_LLM_PROVIDER=bedrock for preview chat."
        )
    aws_profile = (
        os.environ.get("PORTAL_PREVIEW_BEDROCK_AWS_PROFILE")
        or os.environ.get("BEDROCK_AWS_PROFILE")
        or os.environ.get("AWS_PROFILE")
        or ""
    ).strip()
    aws_region = os.environ.get("AWS_REGION", "us-east-1").strip() or "us-east-1"
    bedrock_region = os.environ.get("BEDROCK_REGION", "").strip()
    read_timeout = int(os.environ.get("BEDROCK_READ_TIMEOUT_SECONDS", "300"))
    connect_timeout = int(os.environ.get("BEDROCK_CONNECT_TIMEOUT_SECONDS", "10"))
    return BedrockPreviewSettings(
        model_id=model_id,
        aws_profile=aws_profile,
        aws_region=aws_region,
        bedrock_region=bedrock_region,
        read_timeout_seconds=read_timeout,
        connect_timeout_seconds=connect_timeout,
    )


def _bedrock_region(settings: BedrockPreviewSettings) -> str:
    region = str(settings.bedrock_region or settings.aws_region or "us-east-1").strip()
    if not region:
        raise BedrockPreviewLlmError("AWS_REGION or BEDROCK_REGION must be set for Bedrock")
    return region


def _bedrock_runtime_client(settings: BedrockPreviewSettings) -> Any:
    read_timeout = max(30, min(int(settings.read_timeout_seconds), 900))
    connect_timeout = max(1, min(int(settings.connect_timeout_seconds), 60))
    client_kwargs = {
        "region_name": _bedrock_region(settings),
        "config": BotoConfig(
            read_timeout=read_timeout,
            connect_timeout=connect_timeout,
        ),
    }
    profile = str(settings.aws_profile or "").strip()
    if profile:
        return boto3.Session(profile_name=profile).client("bedrock-runtime", **client_kwargs)
    return boto3.client("bedrock-runtime", **client_kwargs)


def _extract_converse_text(response: dict[str, Any]) -> str:
    output = response.get("output")
    if not isinstance(output, dict):
        raise BedrockPreviewLlmError("Bedrock response missing output object")
    message = output.get("message")
    if not isinstance(message, dict):
        raise BedrockPreviewLlmError("Bedrock response missing message object")
    content_blocks = message.get("content")
    if not isinstance(content_blocks, list):
        raise BedrockPreviewLlmError("Bedrock response missing content blocks")

    text_parts: list[str] = []
    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            text_parts.append(text.strip())
    if not text_parts:
        raise BedrockPreviewLlmError("Bedrock response contained no text content")
    return "\n".join(text_parts)


def _map_bedrock_error(exc: Exception) -> BedrockPreviewLlmError:
    if isinstance(exc, ProfileNotFound):
        return BedrockPreviewLlmError(
            "AWS credentials profile was not found. Check PORTAL_PREVIEW_BEDROCK_AWS_PROFILE."
        )
    if isinstance(exc, NoCredentialsError):
        return BedrockPreviewLlmError(
            "AWS credentials were not found for Bedrock. Run aws sso login for your profile."
        )
    if isinstance(exc, ClientError):
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"AccessDeniedException", "UnauthorizedException"}:
            return BedrockPreviewLlmError(
                f"Bedrock access denied ({code}). Check IAM policy and model access."
            )
        if code in {"ThrottlingException", "TooManyRequestsException"}:
            return BedrockPreviewLlmError(f"Bedrock rate limit reached ({code})")
        return BedrockPreviewLlmError(f"Bedrock request failed ({code or 'ClientError'})")
    if isinstance(exc, BotoCoreError):
        return BedrockPreviewLlmError("Bedrock transport failure")
    return BedrockPreviewLlmError(str(exc))


def bedrock_preview_chat_complete(
    settings: BedrockPreviewSettings,
    *,
    prompt: str,
    max_tokens: int,
    temperature: float = 0.0,
) -> str:
    """Run a single-turn Bedrock Converse call and return assistant text."""
    if not str(prompt or "").strip():
        raise BedrockPreviewLlmError("prompt must be non-empty")
    try:
        response = _bedrock_runtime_client(settings).converse(
            modelId=settings.model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={
                "maxTokens": max(1, int(max_tokens)),
                "temperature": float(temperature),
            },
        )
    except Exception as exc:
        logger.exception("Bedrock preview chat request failed")
        raise _map_bedrock_error(exc) from exc
    return _extract_converse_text(response)


def build_preview_bedrock_synthesizers(
    settings: BedrockPreviewSettings,
    *,
    max_answer_tokens: int,
) -> tuple[SynthesizeFn, GeneralSynthesizeFn]:
    """Return portal chat synthesizers backed by Bedrock for preview mode."""

    def synthesize(question: str, sources) -> str:
        prompt = _build_prompt(question, sources)
        return bedrock_preview_chat_complete(
            settings,
            prompt=prompt,
            max_tokens=max_answer_tokens,
            temperature=0.0,
        ).strip()

    def general_synthesize(question: str) -> str:
        prompt = _build_general_knowledge_prompt(question)
        return bedrock_preview_chat_complete(
            settings,
            prompt=prompt,
            max_tokens=max_answer_tokens,
            temperature=0.0,
        ).strip()

    return synthesize, general_synthesize
