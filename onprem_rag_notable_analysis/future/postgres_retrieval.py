"""PostgreSQL-backed retrieval provider for on-prem grounding."""

# Optional retrieval dependencies are imported lazily, and request-time retrieval
# intentionally fails open to empty context when the database or reranker is down.
# pylint: disable=import-error,broad-exception-caught

from __future__ import annotations

import logging
import math
import re
from typing import Any, Callable, Mapping, Optional, Sequence

from .postgres_index import PostgresRAGSchemaConfig, build_hybrid_search_sql
from .prompt_context_builder import ContextSnippet, render_context_block
from .rag_config import RAGConfig

logger = logging.getLogger(__name__)

ConnectionFactory = Callable[[str], Any]
_WHITESPACE_RE = re.compile(r"\s+")
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_DOMAIN_RE = re.compile(r"\b(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\b")
_URL_RE = re.compile(r"\bhttps?://[^\s<>\"]+\b", re.IGNORECASE)
_HASH_RE = re.compile(r"\b[a-f0-9]{32,64}\b", re.IGNORECASE)
_USER_RE = re.compile(r"\b[a-z0-9._-]+@[a-z0-9.-]+\.[a-z]{2,63}\b", re.IGNORECASE)
_PROCESS_RE = re.compile(r"\b[a-z0-9._-]+\.(?:exe|dll|bat|cmd|ps1|sh)\b", re.IGNORECASE)
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "was",
    "were",
    "with",
    "this",
    "these",
    "those",
    "not",
    "no",
}
_SUSPICIOUS_ACTION_ALLOWLIST = {
    "encodedcommand",
    "powershell",
    "cmdline",
    "downloadstring",
    "rundll32",
    "regsvr32",
    "wmic",
    "psexec",
    "mimikatz",
    "beacon",
    "lsass",
    "credential",
    "forwarding",
    "exfiltration",
    "phishing",
    "bruteforce",
}


def _lazy_import_sentence_transformer():
    """Import SentenceTransformer lazily for optional retrieval deployments."""
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "sentence-transformers is unavailable in the runtime."
        ) from exc
    return SentenceTransformer


def _lazy_import_cross_encoder():
    """Import CrossEncoder lazily for optional reranking deployments."""
    try:
        from sentence_transformers import CrossEncoder  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "sentence-transformers CrossEncoder is unavailable in the runtime."
        ) from exc
    return CrossEncoder


def _default_connect(dsn: str):
    """Open a psycopg connection with dict rows."""
    try:
        import psycopg  # type: ignore
        from psycopg.rows import dict_row  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError("psycopg is unavailable in the runtime.") from exc
    return psycopg.connect(dsn, row_factory=dict_row, connect_timeout=5)


def _collapse_ws(text: str) -> str:
    """Collapse repeated whitespace into single spaces."""
    return _WHITESPACE_RE.sub(" ", (text or "").strip())


def _tokenize_normalized(text: str) -> list[str]:
    """Tokenize text using the retrieval normalization contract."""
    cleaned = _collapse_ws(text).casefold()
    if not cleaned:
        return []
    tokens: list[str] = []
    for raw in cleaned.split():
        token = raw.strip("()[]{}<>,;!?\"'`").strip()
        if token:
            tokens.append(token)
    return tokens


def _unique_non_stop_tokens(text: str) -> list[str]:
    """Return ordered unique normalized tokens excluding configured stopwords."""
    seen: set[str] = set()
    output: list[str] = []
    for token in _tokenize_normalized(text):
        if token in _STOPWORDS or token in seen:
            continue
        seen.add(token)
        output.append(token)
    return output


def _extract_entity_terms(alert_text: str) -> list[str]:
    """Extract ordered high-signal entity terms from alert text."""
    text = alert_text or ""
    seen: set[str] = set()
    entities: list[str] = []
    for pattern in (_IP_RE, _DOMAIN_RE, _URL_RE, _HASH_RE, _USER_RE, _PROCESS_RE):
        for match in pattern.findall(text):
            normalized = match.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            entities.append(normalized)
    return entities


def _extract_detection_tokens(alert_text: str) -> list[str]:
    """Extract detection cue tokens from leading alert lines."""
    first_lines = " ".join((alert_text or "").splitlines()[:8])
    return _unique_non_stop_tokens(first_lines)


def _extract_suspicious_action_tokens(alert_text: str) -> list[str]:
    """Extract ordered suspicious-action tokens from configured allowlist."""
    return [
        token
        for token in _unique_non_stop_tokens(alert_text)
        if token in _SUSPICIOUS_ACTION_ALLOWLIST
    ]


def _ordered_unique(items: Sequence[str], max_items: int) -> list[str]:
    """Deduplicate items while preserving first-seen order."""
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        normalized = (item or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
        if len(output) >= max_items:
            break
    return output


def _coherent_excerpt(text: str, max_chars: int = 700) -> str:
    """Trim text into a coherent excerpt without harsh mid-token clipping."""
    body = _collapse_ws(text)
    if len(body) <= max_chars:
        return body
    boundary_chars = [". ", "; ", " | ", " - ", "\n"]
    best = -1
    for marker in boundary_chars:
        idx = body.rfind(marker, 0, max_chars + 1)
        if idx > best:
            best = idx
    if best >= int(max_chars * 0.5):
        return body[: best + 1].strip()
    space_idx = body.rfind(" ", 0, max_chars + 1)
    if space_idx > 0:
        return body[:space_idx].strip()
    return body[:max_chars].strip()


def _first_vector(values: Any) -> list[float]:
    """Normalize common embedding outputs into one float vector."""
    data = values.tolist() if hasattr(values, "tolist") else values
    if not data:
        return []
    first = data[0] if isinstance(data[0], (list, tuple)) else data
    return [float(v) for v in first]


def _l2_normalize_vector(values: Sequence[float]) -> list[float]:
    """Apply L2 normalization to one vector."""
    norm = math.sqrt(sum(float(v) * float(v) for v in values)) + 1e-12
    return [float(v) / norm for v in values]


def _vector_rows(values: Any) -> list[list[float]]:
    """Normalize common embedding outputs into a list of float vectors."""
    data = values.tolist() if hasattr(values, "tolist") else values
    if not data:
        return []
    if not isinstance(data[0], (list, tuple)):
        data = [data]
    return [[float(v) for v in row] for row in data]


def _row_value(row: Any, key: str, index: int) -> Any:
    """Read a value from a mapping or tuple-like database row."""
    if isinstance(row, Mapping):
        return row.get(key)
    return row[index]


def _vector_literal(values: Sequence[float]) -> str:
    """Format a pgvector literal from normalized embedding values."""
    return "[" + ",".join(f"{float(v):.8f}" for v in values) + "]"


class PostgresRAGContextProvider:
    """PostgreSQL FTS + pgvector context provider."""

    def __init__(
        self,
        config: RAGConfig,
        *,
        connect: Optional[ConnectionFactory] = None,
        embedding_model: Any = None,
        reranker_model: Any = None,
    ) -> None:
        """Initialize the Postgres retrieval provider.

        Args:
            config: Retrieval runtime configuration.
            connect: Optional connection factory for tests.
            embedding_model: Optional embedding model instance for tests.
            reranker_model: Optional reranker model instance for tests.
        """
        self.config = config
        self._connect = connect or _default_connect
        self._embedding_model = embedding_model
        self._reranker_model = reranker_model
        self._schema_config = PostgresRAGSchemaConfig(
            schema=config.postgres_schema,
            chunks_table=config.postgres_chunks_table,
            vector_dimensions=config.vector_dimensions,
            fts_config=config.postgres_fts_config,
        )
        self._search_sql = build_hybrid_search_sql(
            self._schema_config,
            rrf_k=config.rrf_k,
        )

    @classmethod
    def from_config(
        cls,
        config: RAGConfig,
        *,
        connect: Optional[ConnectionFactory] = None,
        embedding_model: Any = None,
        reranker_model: Any = None,
    ) -> Optional["PostgresRAGContextProvider"]:
        """Create provider when Postgres retrieval is enabled and configured."""
        if not config.enabled:
            return None
        if (config.backend or "").strip().lower() != "postgres":
            return None
        if not config.is_valid:
            logger.warning("Postgres RAG enabled but RAG_POSTGRES_DSN is empty.")
            return None
        return cls(
            config,
            connect=connect,
            embedding_model=embedding_model,
            reranker_model=reranker_model,
        )

    def _profile(self, llm_model_name: str) -> str:
        """Map model name to retrieval profile bucket."""
        return "20b" if "20b" in (llm_model_name or "").casefold() else "120b"

    def _profile_limits(self, profile: str) -> tuple[int, int]:
        """Return snippet and context-budget limits for a model profile."""
        if profile == "20b":
            return self.config.max_snippets_20b, self.config.context_budget_chars_20b
        return self.config.max_snippets_120b, self.config.context_budget_chars_120b

    def _profile_rank_limit(self, profile: str) -> int:
        """Return quality-gate fused rank limit for a model profile."""
        if profile == "20b":
            return self.config.fused_rank_limit_20b
        return self.config.fused_rank_limit_120b

    def _embedding_model_instance(self) -> Any:
        """Return the embedding model, loading it lazily if needed."""
        if self._embedding_model is None:
            SentenceTransformer = _lazy_import_sentence_transformer()
            self._embedding_model = SentenceTransformer(self.config.embedding_model_name)
        return self._embedding_model

    def _reranker_model_instance(self) -> Any:
        """Return the reranker model, loading it lazily if needed."""
        if self._reranker_model is None:
            CrossEncoder = _lazy_import_cross_encoder()
            self._reranker_model = CrossEncoder(self.config.rerank_model_name)
        return self._reranker_model

    def _encode_query(self, query_text: str) -> str:
        """Encode query text and return a pgvector literal."""
        model = self._embedding_model_instance()
        from .embedding_text import format_embedding_query_text

        vectors = model.encode(
            [
                format_embedding_query_text(
                    model_name=self.config.embedding_model_name,
                    query_text=query_text,
                )
            ],
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        vector = _first_vector(vectors)
        if len(vector) != self.config.vector_dimensions:
            raise ValueError(
                "Query embedding vector dimension mismatch: "
                f"expected {self.config.vector_dimensions}, got {len(vector)}."
            )
        vector = _l2_normalize_vector(vector)
        return _vector_literal(vector)

    def _query_rows(self, query_text: str, vector_literal: str) -> list[Any]:
        """Run the hybrid search query and return raw database rows."""
        params = (
            query_text,
            query_text,
            self.config.lexical_top_k,
            vector_literal,
            vector_literal,
            self.config.vector_top_k,
            self.config.candidate_pool_limit,
        )
        with self._connect(self.config.postgres_dsn) as conn:
            timeout_ms = int(self.config.postgres_statement_timeout_ms)
            if timeout_ms > 0:
                conn.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (f"{timeout_ms}ms",),
                )
            return list(conn.execute(self._search_sql, params).fetchall())

    def _rows_to_snippets(self, rows: Sequence[Any]) -> list[ContextSnippet]:
        """Convert database rows into prompt snippets."""
        snippets: list[ContextSnippet] = []
        for row in rows:
            text = str(_row_value(row, "text", 6) or "")
            excerpt = _coherent_excerpt(text)
            if not excerpt:
                continue
            snippets.append(
                ContextSnippet(
                    source_file=str(_row_value(row, "source_file", 5) or "unknown_source"),
                    section_path=str(_row_value(row, "section_path", 4) or "root"),
                    excerpt=excerpt,
                )
            )
        return snippets

    def _encode_snippet_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Encode and normalize snippet excerpts for duplicate detection."""
        if not texts:
            return []
        model = self._embedding_model_instance()
        vectors = model.encode(
            list(texts),
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [_l2_normalize_vector(vector) for vector in _vector_rows(vectors)]

    def _dedupe_snippets(self, snippets: Sequence[ContextSnippet]) -> list[ContextSnippet]:
        """Remove near-duplicate snippets using the configured embedding threshold."""
        if not snippets:
            return []
        try:
            excerpted = [
                (snippet, (snippet.excerpt or "").strip())
                for snippet in snippets
                if (snippet.excerpt or "").strip()
            ]
            if not excerpted:
                return []
            vectors = self._encode_snippet_texts(
                [excerpt for _snippet, excerpt in excerpted]
            )
            if len(vectors) != len(excerpted):
                raise ValueError("Snippet embedding count did not match snippet count.")
            kept: list[ContextSnippet] = []
            kept_vectors: list[list[float]] = []
            for (snippet, _excerpt), candidate in zip(excerpted, vectors):
                max_similarity = (
                    max(
                        sum(a * b for a, b in zip(existing, candidate))
                        for existing in kept_vectors
                    )
                    if kept_vectors
                    else 0.0
                )
                if max_similarity >= self.config.near_duplicate_similarity_threshold:
                    continue
                kept.append(snippet)
                kept_vectors.append(candidate)
            return kept
        except Exception as exc:
            logger.warning("RAG snippet dedupe failed; using undeduped snippets: %s", exc)
            return list(snippets)

    def _row_passes_quality_gate(
        self,
        *,
        row: Any,
        fused_rank: int,
        rank_limit: int,
        profile: str,
        high_signal_terms: set[str],
        cue_tokens: set[str],
    ) -> bool:
        """Apply the same rank and term-overlap gate used by fallback retrieval."""
        if fused_rank > rank_limit:
            return False

        text = str(_row_value(row, "text", 6) or "")
        candidate_tokens = set(_unique_non_stop_tokens(text))
        has_high_signal = bool(candidate_tokens.intersection(high_signal_terms))
        overlap = len(candidate_tokens.intersection(cue_tokens))

        if profile == "20b":
            return has_high_signal
        return has_high_signal or overlap >= 2

    def _filter_rows_by_quality(
        self,
        *,
        rows: Sequence[Any],
        profile: str,
        high_signal_terms: set[str],
        cue_tokens: set[str],
    ) -> list[Any]:
        """Filter SQL-fused rows through the shared retrieval quality policy."""
        rank_limit = self._profile_rank_limit(profile)
        filtered = []
        for index, row in enumerate(rows, start=1):
            if self._row_passes_quality_gate(
                row=row,
                fused_rank=index,
                rank_limit=rank_limit,
                profile=profile,
                high_signal_terms=high_signal_terms,
                cue_tokens=cue_tokens,
            ):
                filtered.append(row)
        return filtered

    def _rerank_snippets(
        self, *, query_text: str, snippets: Sequence[ContextSnippet]
    ) -> list[ContextSnippet]:
        """Optionally rerank snippets with a BGE-style cross encoder."""
        if not self.config.rerank_enabled or len(snippets) <= 1:
            return list(snippets)
        try:
            model = self._reranker_model_instance()
            pairs = [(query_text, snippet.excerpt) for snippet in snippets]
            scores = model.predict(pairs)
            ranked = sorted(
                zip(snippets, scores),
                key=lambda item: float(item[1]),
                reverse=True,
            )
            return [snippet for snippet, _score in ranked]
        except Exception as exc:
            logger.warning("RAG reranking failed; using hybrid rank order: %s", exc)
            if self.config.fail_closed:
                raise
            return list(snippets)

    def build_context(self, *, alert_text: str, llm_model_name: str) -> str:
        """Build rendered SOC operational context block from Postgres retrieval."""
        try:
            entity_terms = _extract_entity_terms(alert_text)
            detection_tokens = _extract_detection_tokens(alert_text)
            suspicious_tokens = _extract_suspicious_action_tokens(alert_text)
            cue_tokens = _unique_non_stop_tokens(alert_text)
            high_signal_terms = set(entity_terms + detection_tokens + suspicious_tokens)
            query_tokens = _ordered_unique(
                entity_terms + detection_tokens + suspicious_tokens + cue_tokens,
                max_items=64,
            )
            if not query_tokens:
                return ""

            profile = self._profile(llm_model_name)
            query_text = " ".join(query_tokens)
            vector_literal = self._encode_query(query_text)
            rows = self._query_rows(query_text, vector_literal)
            rows = self._filter_rows_by_quality(
                rows=rows,
                profile=profile,
                high_signal_terms=high_signal_terms,
                cue_tokens=set(cue_tokens),
            )
            snippets = self._rows_to_snippets(rows)
            snippets = self._rerank_snippets(query_text=query_text, snippets=snippets)
            snippets = self._dedupe_snippets(snippets)

            max_snippets, budget_chars = self._profile_limits(
                profile
            )
            rendered = render_context_block(
                header=self.config.context_header,
                snippets=snippets,
                max_snippets=max_snippets,
                budget_chars=budget_chars,
            )
            return rendered.text
        except Exception as exc:
            logger.warning(
                "Postgres RAG context build failed; continuing without context: %s",
                exc,
            )
            if self.config.fail_closed:
                raise
            return ""
