"""Helpers for local sentence-transformers embedding inputs."""

MXBAI_QUERY_PROMPT_PREFIX = "Represent this sentence for searching relevant passages: "


def format_embedding_query_text(*, model_name: str, query_text: str) -> str:
    """Apply model-specific query formatting before encode()."""
    normalized = (model_name or "").strip().lower()
    text = (query_text or "").strip()
    if "mxbai-embed" in normalized:
        return f"{MXBAI_QUERY_PROMPT_PREFIX}{text}"
    return text
