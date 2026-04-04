"""Configuration models for on-prem retrieval grounding."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RAGConfig:
    """Runtime configuration for retrieval grounding.

    Attributes:
        enabled: Enables retrieval context injection.
        sqlite_path: SQLite path for lexical/chunk metadata.
        faiss_path: FAISS index path for vector retrieval.
        embedding_model_name: Local embedding model identifier/path.
        max_snippets_120b: Max snippets for 120b profile.
        max_snippets_20b: Max snippets for 20b profile.
        context_budget_chars_120b: Prompt context char budget for 120b profile.
        context_budget_chars_20b: Prompt context char budget for 20b profile.
        fused_rank_limit_120b: Max fused rank accepted for 120b quality gate.
        fused_rank_limit_20b: Max fused rank accepted for 20b quality gate.
        near_duplicate_similarity_threshold: Cosine similarity dedupe threshold.
        lexical_top_k: FTS candidate pull size.
        vector_top_k: Vector candidate pull size.
        candidate_pool_limit: Post-fusion candidate cap before gating.
        rrf_k: Reciprocal rank fusion smoothing constant.
        context_header: Stable prompt header name.
    """

    enabled: bool = False

    sqlite_path: Path = Path("/kb/index/kb.sqlite3")
    faiss_path: Path = Path("/kb/index/kb.faiss")

    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"

    max_snippets_120b: int = 5
    max_snippets_20b: int = 4
    context_budget_chars_120b: int = 2200
    context_budget_chars_20b: int = 1600

    fused_rank_limit_120b: int = 8
    fused_rank_limit_20b: int = 6
    near_duplicate_similarity_threshold: float = 0.80

    lexical_top_k: int = 30
    vector_top_k: int = 30
    candidate_pool_limit: int = 40

    rrf_k: int = 60

    # Keep this stable because the prompt contract references it.
    context_header: str = "SOC_OPERATIONAL_CONTEXT"

    @property
    def is_valid(self) -> bool:
        """Return True when both required retrieval artifacts exist."""
        return self.sqlite_path.exists() and self.faiss_path.exists()

