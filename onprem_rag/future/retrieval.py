"""Hybrid retrieval and context-selection logic for on-prem grounding."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np

from .keyword_index import LexicalHit, fetch_chunks_by_row_ids, lexical_search
from .prompt_context_builder import ContextSnippet, render_context_block
from .rag_config import RAGConfig
from .vector_index import VectorSearchClient

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_DOMAIN_RE = re.compile(r"\b(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\b")
_URL_RE = re.compile(r"\bhttps?://[^\s<>\"]+\b", re.IGNORECASE)
_HASH_RE = re.compile(r"\b[a-f0-9]{32,64}\b", re.IGNORECASE)
_USER_RE = re.compile(r"\b[a-z0-9._-]+@[a-z0-9.-]+\.[a-z]{2,63}\b", re.IGNORECASE)
_PROCESS_RE = re.compile(r"\b[a-z0-9._-]+\.(?:exe|dll|bat|cmd|ps1|sh)\b", re.IGNORECASE)

# Fixed v1 allowlist referenced by the OUTLINE.
_SUSPICIOUS_ACTION_ALLOWLIST: Set[str] = {
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

# Fixed in-service stopword set for deterministic behavior.
_STOPWORDS: Set[str] = {
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


def _collapse_ws(text: str) -> str:
    """Collapse repeated whitespace into single spaces.

    Args:
        text: Input text.

    Returns:
        Whitespace-normalized text.
    """
    return _WHITESPACE_RE.sub(" ", (text or "").strip())


def _tokenize_normalized(text: str) -> List[str]:
    """Tokenize text using the v1 normalization contract.

    Args:
        text: Input text to tokenize.

    Returns:
        Casefolded, punctuation-trimmed tokens split on whitespace while
        preserving internal indicator characters.
    """
    cleaned = _collapse_ws(text).casefold()
    if not cleaned:
        return []
    out: List[str] = []
    for raw in cleaned.split():
        token = raw.strip("()[]{}<>,;!?\"'`")
        token = token.strip()
        if not token:
            continue
        out.append(token)
    return out


def _unique_non_stop_tokens(text: str) -> Set[str]:
    """Return unique normalized tokens excluding configured stopwords.

    Args:
        text: Input text to tokenize/filter.

    Returns:
        Set of non-stopword tokens.
    """
    return {t for t in _tokenize_normalized(text) if t not in _STOPWORDS}


def _extract_entity_terms(alert_text: str) -> Set[str]:
    """Extract high-signal entity terms from alert text.

    Args:
        alert_text: Prompt-formatted alert text.

    Returns:
        Set of extracted entity terms (IPs/domains/URLs/hashes/users/processes).
    """
    text = alert_text or ""
    entities: Set[str] = set()
    for pattern in (_IP_RE, _DOMAIN_RE, _URL_RE, _HASH_RE, _USER_RE, _PROCESS_RE):
        entities.update(x.casefold() for x in pattern.findall(text))
    return entities


def _extract_detection_tokens(alert_text: str) -> Set[str]:
    """Extract detection cue tokens from leading alert lines.

    Args:
        alert_text: Prompt-formatted alert text.

    Returns:
        Set of non-stopword tokens from the first lines.
    """
    # Try to focus on top summary-ish lines from formatted prompt input.
    lines = (alert_text or "").splitlines()
    first_lines = " ".join(lines[:8])
    return _unique_non_stop_tokens(first_lines)


def _extract_suspicious_action_tokens(alert_text: str) -> Set[str]:
    """Extract suspicious-action tokens from configured allowlist.

    Args:
        alert_text: Prompt-formatted alert text.

    Returns:
        Set of suspicious action tokens present in the alert.
    """
    toks = _unique_non_stop_tokens(alert_text)
    return {t for t in toks if t in _SUSPICIOUS_ACTION_ALLOWLIST}


def _ordered_unique(items: Iterable[str], max_items: int) -> List[str]:
    """Deduplicate items while preserving first-seen order.

    Args:
        items: Candidate token sequence.
        max_items: Maximum output size.

    Returns:
        Ordered unique list truncated to `max_items`.
    """
    seen: Set[str] = set()
    out: List[str] = []
    for item in items:
        t = (item or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= max_items:
            break
    return out


def _coherent_excerpt(text: str, max_chars: int = 700) -> str:
    """Trim text into a coherent excerpt without harsh mid-token clipping.

    Args:
        text: Source text.
        max_chars: Maximum excerpt length.

    Returns:
        Best-effort coherent excerpt.
    """
    body = _collapse_ws(text)
    if len(body) <= max_chars:
        return body
    # Try to cut at a natural boundary.
    boundary_chars = [". ", "; ", " | ", " - ", "\n"]
    best = -1
    for marker in boundary_chars:
        idx = body.rfind(marker, 0, max_chars + 1)
        if idx > best:
            best = idx
    if best >= int(max_chars * 0.5):
        return body[: best + 1].strip()
    # Last resort: cut at nearest previous space.
    space_idx = body.rfind(" ", 0, max_chars + 1)
    if space_idx > 0:
        return body[:space_idx].strip()
    return body[:max_chars].strip()


@dataclass
class _Candidate:
    """Internal hybrid-candidate representation used during fusion.

    Attributes:
        row_id: SQLite chunk row ID.
        text: Chunk text content.
        source_file: Source filename.
        section_path: Source section path/title.
        lexical_rank: FTS rank (1-based) when present.
        vector_rank: Vector rank (1-based) when present.
        fused_score: Reciprocal-rank-fusion score.
    """

    row_id: int
    text: str
    source_file: str
    section_path: str
    lexical_rank: Optional[int] = None
    vector_rank: Optional[int] = None
    fused_score: float = 0.0


class RAGContextProvider:
    """Query-time retrieval and prompt-context composer."""

    def __init__(self, config: RAGConfig):
        """Initialize retrieval provider from runtime config.

        Args:
            config: Retrieval runtime configuration.
        """
        self.config = config
        self._vector_client = VectorSearchClient(
            sqlite_path=config.sqlite_path,
            faiss_path=config.faiss_path,
            embedding_model_name=config.embedding_model_name,
        )

    @classmethod
    def from_config(cls, config: RAGConfig) -> Optional["RAGContextProvider"]:
        """Create provider when retrieval is enabled and artifacts exist.

        Args:
            config: Retrieval runtime configuration.

        Returns:
            Provider instance or None when disabled/invalid.
        """
        if not config.enabled:
            return None
        if not config.is_valid:
            logger.warning(
                "RAG enabled but index artifacts are missing: sqlite=%s faiss=%s",
                config.sqlite_path,
                config.faiss_path,
            )
            return None
        return cls(config)

    def _profile(self, llm_model_name: str) -> str:
        """Map model name to retrieval profile bucket.

        Args:
            llm_model_name: Configured LLM model name.

        Returns:
            `20b` or `120b` profile key.
        """
        m = (llm_model_name or "").casefold()
        return "20b" if "20b" in m else "120b"

    def _profile_limits(self, profile: str) -> Tuple[int, int, int]:
        """Return snippet, budget, and rank limits for a profile.

        Args:
            profile: Retrieval profile key (`20b` or `120b`).

        Returns:
            Tuple of `(max_snippets, budget_chars, rank_limit)`.
        """
        if profile == "20b":
            return (
                self.config.max_snippets_20b,
                self.config.context_budget_chars_20b,
                self.config.fused_rank_limit_20b,
            )
        return (
            self.config.max_snippets_120b,
            self.config.context_budget_chars_120b,
            self.config.fused_rank_limit_120b,
        )

    def _build_candidates(self, query_tokens: Sequence[str]) -> List[_Candidate]:
        """Build and rank hybrid retrieval candidates using RRF.

        Args:
            query_tokens: Ordered query token list.

        Returns:
            Fused and rank-sorted candidate list.
        """
        lex_hits = lexical_search(
            self.config.sqlite_path, query_tokens, self.config.lexical_top_k
        )
        # Use query tokens text for semantic embedding.
        query_text = " ".join(query_tokens)
        vec_hits = self._vector_client.search(query_text, self.config.vector_top_k)
        vec_row_ids = [h.row_id for h in vec_hits]
        vec_rows = fetch_chunks_by_row_ids(self.config.sqlite_path, vec_row_ids)
        vec_rows_by_id = {r.row_id: r for r in vec_rows}

        candidates: Dict[int, _Candidate] = {}

        for i, hit in enumerate(lex_hits, start=1):
            c = candidates.get(hit.row_id)
            if c is None:
                c = _Candidate(
                    row_id=hit.row_id,
                    text=hit.text,
                    source_file=hit.source_file,
                    section_path=hit.section_path,
                )
                candidates[hit.row_id] = c
            c.lexical_rank = i

        for i, v in enumerate(vec_hits, start=1):
            row = vec_rows_by_id.get(v.row_id)
            if row is None:
                continue
            c = candidates.get(v.row_id)
            if c is None:
                c = _Candidate(
                    row_id=row.row_id,
                    text=row.text,
                    source_file=row.source_file,
                    section_path=row.section_path,
                )
                candidates[v.row_id] = c
            c.vector_rank = i

        for c in candidates.values():
            score = 0.0
            if c.lexical_rank is not None:
                score += 1.0 / (self.config.rrf_k + c.lexical_rank)
            if c.vector_rank is not None:
                score += 1.0 / (self.config.rrf_k + c.vector_rank)
            c.fused_score = score

        ranked = sorted(candidates.values(), key=lambda x: x.fused_score, reverse=True)
        return ranked[: self.config.candidate_pool_limit]

    def _passes_quality_gate(
        self,
        *,
        candidate: _Candidate,
        fused_rank: int,
        rank_limit: int,
        profile: str,
        high_signal_terms: Set[str],
        cue_tokens: Set[str],
    ) -> bool:
        """Apply model-profile quality gate to a candidate snippet.

        Args:
            candidate: Candidate retrieval row.
            fused_rank: Candidate position in fused ranking.
            rank_limit: Maximum fused rank allowed.
            profile: Retrieval profile key.
            high_signal_terms: High-signal terms extracted from the alert.
            cue_tokens: Normalized non-stopword cue tokens from the alert.

        Returns:
            True when candidate passes quality gate for the profile.
        """
        if fused_rank > rank_limit:
            return False

        candidate_tokens = _unique_non_stop_tokens(candidate.text)
        has_high_signal = bool(candidate_tokens.intersection(high_signal_terms))
        overlap = len(candidate_tokens.intersection(cue_tokens))

        if profile == "20b":
            return has_high_signal
        # 120b gate: high-signal OR overlap >= 2
        return has_high_signal or overlap >= 2

    def _dedupe_snippets(self, snippets: List[ContextSnippet]) -> List[ContextSnippet]:
        """Remove near-duplicate snippets using embedding similarity.

        Args:
            snippets: Candidate snippets in priority order.

        Returns:
            De-duplicated snippet list.
        """
        if not snippets:
            return []
        try:
            kept: List[ContextSnippet] = []
            kept_texts: List[str] = []
            for snip in snippets:
                excerpt = (snip.excerpt or "").strip()
                if not excerpt:
                    continue
                if not kept_texts:
                    kept.append(snip)
                    kept_texts.append(excerpt)
                    continue
                vecs = self._vector_client.encode_texts(kept_texts + [excerpt])
                cand = vecs[-1]
                prior = vecs[:-1]
                max_sim = float(np.max(prior @ cand)) if prior.size else 0.0
                if max_sim >= self.config.near_duplicate_similarity_threshold:
                    continue
                kept.append(snip)
                kept_texts.append(excerpt)
            return kept
        except Exception:
            # Fail-open for robustness: better to keep context than fail request path.
            return snippets

    def build_context(self, *, alert_text: str, llm_model_name: str) -> str:
        """Build rendered SOC operational context block for prompt grounding.

        Args:
            alert_text: Prompt-formatted alert text.
            llm_model_name: Active LLM model name for profile selection.

        Returns:
            Rendered `SOC_OPERATIONAL_CONTEXT` block, or an empty string when
            retrieval fails or no snippet passes quality gates.
        """
        try:
            entity_terms = _extract_entity_terms(alert_text)
            detection_tokens = _extract_detection_tokens(alert_text)
            suspicious_tokens = _extract_suspicious_action_tokens(alert_text)
            high_signal_terms = set(entity_terms) | set(detection_tokens) | set(
                suspicious_tokens
            )
            cue_tokens = _unique_non_stop_tokens(alert_text)
            # Query term order: high-signal first, then remaining cues.
            query_tokens = _ordered_unique(
                list(high_signal_terms) + list(cue_tokens), max_items=64
            )
            if not query_tokens:
                return ""

            profile = self._profile(llm_model_name)
            max_snippets, budget_chars, rank_limit = self._profile_limits(profile)

            ranked = self._build_candidates(query_tokens)
            prelim: List[ContextSnippet] = []
            for i, c in enumerate(ranked, start=1):
                if not self._passes_quality_gate(
                    candidate=c,
                    fused_rank=i,
                    rank_limit=rank_limit,
                    profile=profile,
                    high_signal_terms=high_signal_terms,
                    cue_tokens=cue_tokens,
                ):
                    continue
                excerpt = _coherent_excerpt(c.text)
                if not excerpt:
                    continue
                prelim.append(
                    ContextSnippet(
                        source_file=c.source_file,
                        section_path=c.section_path or "root",
                        excerpt=excerpt,
                    )
                )

            deduped = self._dedupe_snippets(prelim)
            rendered = render_context_block(
                header=self.config.context_header,
                snippets=deduped,
                max_snippets=max_snippets,
                budget_chars=budget_chars,
            )
            return rendered.text
        except Exception as exc:
            logger.warning("RAG context build failed; continuing without context: %s", exc)
            return ""

