"""Prompt-pack resolution helpers."""

from __future__ import annotations

from typing import Mapping

from ..config_models import CustomerBundle
from .models import PromptPack


def resolve_prompt_pack(
    customer_bundle: CustomerBundle, prompt_packs: Mapping[str, PromptPack]
) -> PromptPack:
    """Resolve and validate the prompt pack referenced by a customer bundle."""
    if customer_bundle.prompt_pack_name not in prompt_packs:
        available = ", ".join(sorted(prompt_packs))
        raise ValueError(
            "Unknown prompt pack "
            f"{customer_bundle.prompt_pack_name!r}. Available packs: {available}"
        )
    return prompt_packs[customer_bundle.prompt_pack_name]

