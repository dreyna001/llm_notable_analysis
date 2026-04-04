"""Prompt-context rendering for SOC operational grounding."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List


@dataclass(frozen=True)
class ContextSnippet:
    """One retrieval snippet for prompt grounding.

    Attributes:
        source_file: Source document filename.
        section_path: Source section path/title.
        excerpt: Snippet text to inject into prompt context.
    """

    source_file: str
    section_path: str
    excerpt: str


@dataclass(frozen=True)
class RenderedContext:
    """Rendered context output and accounting metadata.

    Attributes:
        text: Rendered context block text.
        snippet_count: Number of snippets included.
        budget_chars: Maximum character budget used for rendering.
    """

    text: str
    snippet_count: int
    budget_chars: int


def render_context_block(
    *,
    header: str,
    snippets: Iterable[ContextSnippet],
    max_snippets: int,
    budget_chars: int,
) -> RenderedContext:
    """Render context with strict budget accounting.

    Budget includes the final rendered text, including header/provenance/newlines.
    Snippets are added in the provided order; non-fitting snippets are skipped.

    Args:
        header: Context header label (for example `SOC_OPERATIONAL_CONTEXT`).
        snippets: Candidate snippets in priority order.
        max_snippets: Maximum number of snippets to include.
        budget_chars: Total character budget for the rendered block.

    Returns:
        Rendered context block and accounting metadata.
    """
    base_header = f"{header}\n"
    if len(base_header) > budget_chars:
        return RenderedContext(text="", snippet_count=0, budget_chars=budget_chars)

    selected_lines: List[str] = []
    added = 0
    current_len = len(base_header)
    for i, snip in enumerate(snippets, start=1):
        if added >= max_snippets:
            break
        source = (snip.source_file or "").strip() or "unknown_source"
        section = (snip.section_path or "").strip() or "root"
        excerpt = (snip.excerpt or "").strip()
        if not excerpt:
            continue
        line = f"[{i}] [{source} :: {section}] {excerpt}\n"
        if current_len + len(line) <= budget_chars:
            selected_lines.append(line)
            current_len += len(line)
            added += 1
            continue
        # Overflow rule: skip non-fitting snippet and continue to next.
        continue

    if added == 0:
        return RenderedContext(text="", snippet_count=0, budget_chars=budget_chars)

    final = base_header + "".join(selected_lines)
    return RenderedContext(text=final, snippet_count=added, budget_chars=budget_chars)

