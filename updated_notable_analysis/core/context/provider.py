"""Advisory context provider seam and bundle resolution helpers."""

from __future__ import annotations

from typing import Mapping, Protocol, Sequence

from ..config_models import CustomerBundle
from ..models import AdvisoryContextSnippet, NormalizedAlert
from ..validators import require_int_gt_zero
from .models import ContextBundle


class ContextProvider(Protocol):
    """Contract for fetching advisory context for prompt grounding.

    Implementations must return advisory context only, never direct alert evidence.
    """

    def get_advisory_context(
        self, normalized_alert: NormalizedAlert, context_bundle: ContextBundle
    ) -> Sequence[AdvisoryContextSnippet]:
        """Return advisory context snippets for the provided alert and context bundle."""


def resolve_context_bundle(
    customer_bundle: CustomerBundle, context_bundles: Mapping[str, ContextBundle]
) -> ContextBundle:
    """Resolve and validate the context bundle referenced by a customer bundle."""
    if customer_bundle.context_bundle_name not in context_bundles:
        available = ", ".join(sorted(context_bundles))
        raise ValueError(
            "Unknown context bundle "
            f"{customer_bundle.context_bundle_name!r}. Available bundles: {available}"
        )
    return context_bundles[customer_bundle.context_bundle_name]


def normalize_advisory_context(
    snippets: Sequence[AdvisoryContextSnippet],
    *,
    retrieval_limit: int,
    context_budget_chars: int,
) -> tuple[AdvisoryContextSnippet, ...]:
    """Normalize advisory context snippets by enforcing limits and budget."""
    retrieval_limit = require_int_gt_zero(retrieval_limit, "retrieval_limit")
    context_budget_chars = require_int_gt_zero(context_budget_chars, "context_budget_chars")

    def rendered_snippet_chars(snippet: AdvisoryContextSnippet) -> int:
        """Return rendered advisory snippet size used by prompt assembly."""
        rendered_line = f"- [{snippet.provenance_ref}] {snippet.title}: {snippet.content}"
        return len(rendered_line)

    normalized: list[AdvisoryContextSnippet] = []
    used_chars = 0
    for snippet in snippets:
        if not isinstance(snippet, AdvisoryContextSnippet):
            raise ValueError("Advisory context entries must be AdvisoryContextSnippet.")
        separator_chars = 1 if normalized else 0
        projected = used_chars + separator_chars + rendered_snippet_chars(snippet)
        if projected > context_budget_chars:
            break
        normalized.append(snippet)
        used_chars = projected
        if len(normalized) >= retrieval_limit:
            break
    return tuple(normalized)

