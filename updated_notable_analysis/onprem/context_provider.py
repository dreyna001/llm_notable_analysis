"""Local JSON advisory context provider for on-prem deployments."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from updated_notable_analysis.core.context import ContextBundle, ContextProvider
from updated_notable_analysis.core.models import AdvisoryContextSnippet, NormalizedAlert
from updated_notable_analysis.core.validators import require_non_empty_string


class LocalJsonAdvisoryContextProvider(ContextProvider):
    """Read advisory context snippets from local JSON files by context index name."""

    def __init__(self, *, context_dir: str | Path) -> None:
        """Initialize the provider with a local context directory."""
        self._context_dir = Path(require_non_empty_string(str(context_dir), "context_dir"))
        if not self._context_dir.is_dir():
            raise ValueError("Field 'context_dir' must be an existing directory.")

    @property
    def context_dir(self) -> Path:
        """Return the local advisory context directory."""
        return self._context_dir

    def get_advisory_context(
        self, normalized_alert: NormalizedAlert, context_bundle: ContextBundle
    ) -> Sequence[AdvisoryContextSnippet]:
        """Return snippets from configured local context index files."""
        if not isinstance(normalized_alert, NormalizedAlert):
            raise ValueError("Field 'normalized_alert' must be NormalizedAlert.")
        if not isinstance(context_bundle, ContextBundle):
            raise ValueError("Field 'context_bundle' must be ContextBundle.")

        allowed_sources = set(context_bundle.enabled_context_sources)
        snippets: list[AdvisoryContextSnippet] = []
        for index_name in context_bundle.index_names:
            index_path = self._context_dir / f"{index_name}.json"
            if not index_path.exists():
                continue
            snippets.extend(
                snippet
                for snippet in _load_snippets(index_path)
                if snippet.source_type in allowed_sources
            )
        return tuple(sorted(snippets, key=_snippet_sort_key))


def _load_snippets(index_path: Path) -> tuple[AdvisoryContextSnippet, ...]:
    """Load and validate one local advisory-context index file."""
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Advisory context file {str(index_path)!r} is not valid JSON.") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("Advisory context file must contain a JSON object.")
    snippets_payload = payload.get("snippets")
    if not isinstance(snippets_payload, list):
        raise ValueError("Advisory context file must include a 'snippets' list.")

    snippets: list[AdvisoryContextSnippet] = []
    for idx, item in enumerate(snippets_payload):
        if not isinstance(item, Mapping):
            raise ValueError(f"Advisory context snippet {idx} must be a JSON object.")
        try:
            snippets.append(_snippet_from_mapping(item, index_path=index_path))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Advisory context snippet {idx} in {str(index_path)!r} is invalid."
            ) from exc
    return tuple(snippets)


def _snippet_from_mapping(
    value: Mapping[str, Any],
    *,
    index_path: Path,
) -> AdvisoryContextSnippet:
    """Normalize one mapping into AdvisoryContextSnippet."""
    return AdvisoryContextSnippet(
        source_type=value["source_type"],
        source_id=value["source_id"],
        title=value["title"],
        content=value["content"],
        provenance_ref=value["provenance_ref"],
        source_file=value.get("source_file", str(index_path)),
        section_path=value.get("section_path"),
        rank=value.get("rank"),
    )


def _snippet_sort_key(snippet: AdvisoryContextSnippet) -> tuple[int, str, str]:
    """Sort snippets deterministically by rank, provenance, then source id."""
    rank = snippet.rank if snippet.rank is not None else 1_000_000
    return (rank, snippet.provenance_ref, snippet.source_id)
