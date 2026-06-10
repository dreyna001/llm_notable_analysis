"""Portal chat LLM provider selection and synthesizer wiring."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .bedrock_portal_llm import bedrock_chat_complete
from .case_chat import (
    GeneralSynthesizeFn,
    SynthesizeFn,
    _build_general_knowledge_prompt,
    _build_prompt,
)
from .config import Config

if TYPE_CHECKING:
    from .case_chat import RetrievedSource

_PORTAL_LLM_PROVIDERS = {"local", "bedrock"}


def normalize_portal_llm_provider(raw: str) -> str:
    """Return a validated portal LLM provider name."""
    provider = str(raw or "local").strip().lower() or "local"
    if provider not in _PORTAL_LLM_PROVIDERS:
        raise ValueError(
            "PORTAL_LLM_PROVIDER must be one of: "
            + ", ".join(sorted(_PORTAL_LLM_PROVIDERS))
        )
    return provider


def build_portal_synthesizers(
    config: Config,
) -> tuple[SynthesizeFn | None, GeneralSynthesizeFn | None]:
    """Return portal chat synthesizers when not using the default local gateway."""
    if normalize_portal_llm_provider(config.PORTAL_LLM_PROVIDER) != "bedrock":
        return None, None

    def synthesize(question: str, sources: list["RetrievedSource"]) -> str:
        prompt = _build_prompt(question, sources)
        return bedrock_chat_complete(
            config,
            prompt=prompt,
            max_tokens=config.CASE_QA_MAX_ANSWER_TOKENS,
            temperature=0.0,
        ).strip()

    def general_synthesize(question: str) -> str:
        prompt = _build_general_knowledge_prompt(question)
        return bedrock_chat_complete(
            config,
            prompt=prompt,
            max_tokens=config.CASE_QA_MAX_ANSWER_TOKENS,
            temperature=0.0,
        ).strip()

    return synthesize, general_synthesize
