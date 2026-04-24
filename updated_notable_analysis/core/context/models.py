"""Context-bundle contracts for advisory retrieval seams."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..validators import normalize_string_list, require_bool, require_int_gt_zero, require_non_empty_string


@dataclass(slots=True)
class ContextBundle:
    """Customer-selected advisory context retrieval bundle.

    Attributes:
        bundle_name: Logical bundle name selected by operator config.
        enabled_context_sources: Named context sources (for example SOPs and field dictionaries).
        vector_backend: Retrieval backend identifier (for example sqlite_faiss).
        index_names: Retrieval index or collection names that may be queried.
        retrieval_limit: Maximum snippets requested from the provider.
        context_budget_chars: Maximum advisory-context character budget.
        provenance_required: Whether returned snippets must include provenance refs.
    """

    bundle_name: str
    enabled_context_sources: Sequence[str]
    vector_backend: str
    index_names: Sequence[str]
    retrieval_limit: int
    context_budget_chars: int
    provenance_required: bool = True

    def __post_init__(self) -> None:
        """Validate and normalize context-bundle fields."""
        self.bundle_name = require_non_empty_string(self.bundle_name, "bundle_name")
        self.enabled_context_sources = normalize_string_list(
            self.enabled_context_sources, "enabled_context_sources", allow_empty=False
        )
        self.vector_backend = require_non_empty_string(self.vector_backend, "vector_backend")
        self.index_names = normalize_string_list(self.index_names, "index_names", allow_empty=False)
        self.retrieval_limit = require_int_gt_zero(self.retrieval_limit, "retrieval_limit")
        self.context_budget_chars = require_int_gt_zero(
            self.context_budget_chars, "context_budget_chars"
        )
        self.provenance_required = require_bool(self.provenance_required, "provenance_required")

