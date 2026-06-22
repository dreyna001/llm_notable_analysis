"""Synthetic Knowledge Base provider for analyst portal preview.

Production portal chat can attach advisory KB snippets via Postgres RAG when
``RAG_ENABLED`` (and related flags) are set. Preview uses committed markdown
fixtures and simple keyword matching instead of embeddings or pgvector.

Docs live under ``data/preview_scenarios/knowledge_base/``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from llm_notable_analysis_onprem_systemd.onprem_service.case_chat import (
    RetrievedSource,
)

_PREVIEW_KB_DIR = (
    Path(__file__).resolve().parents[1] / "data" / "preview_scenarios" / "knowledge_base"
)

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")


@dataclass(frozen=True)
class PreviewKnowledgeBaseDoc:
    """One committed preview KB document."""

    doc_id: str
    section: str
    path: Path
    triggers: tuple[str, ...]


_PREVIEW_KB_DOCS: tuple[PreviewKnowledgeBaseDoc, ...] = (
    PreviewKnowledgeBaseDoc(
        doc_id="sop-host-isolation",
        section="knowledge_base.sop_host_isolation",
        path=_PREVIEW_KB_DIR / "sop-host-isolation.md",
        triggers=(
            "isolate",
            "isolation",
            "contain",
            "containment",
            "turn off",
            "shutdown",
            "shut down",
            "power off",
            "disconnect",
            "network isolate",
            "edr",
        ),
    ),
    PreviewKnowledgeBaseDoc(
        doc_id="sop-tier2-escalation",
        section="knowledge_base.sop_tier2_escalation",
        path=_PREVIEW_KB_DIR / "sop-tier2-escalation.md",
        triggers=(
            "escalate",
            "escalation",
            "tier 2",
            "tier-2",
            "tier2",
            "t2",
            "hand off",
            "handoff",
            "pagerduty",
            "soc-tier2",
        ),
    ),
    PreviewKnowledgeBaseDoc(
        doc_id="corp-network-architecture",
        section="knowledge_base.network_architecture",
        path=_PREVIEW_KB_DIR / "corp-network-architecture.md",
        triggers=(
            "network",
            "architecture",
            "vlan",
            "segment",
            "subnet",
            "cidr",
            "jump path",
            "jump-01",
            "lateral",
            "10.30",
            "10.44",
            "corp.local",
        ),
    ),
    PreviewKnowledgeBaseDoc(
        doc_id="hva-registry",
        section="knowledge_base.hva_registry",
        path=_PREVIEW_KB_DIR / "hva-registry.md",
        triggers=(
            "hva",
            "high value",
            "high-value",
            "critical asset",
            "db-prod-01",
            "db-prod",
            "payment-gateway",
            "dc-01",
            "app-server-03",
            "asset registry",
            "pci",
        ),
    ),
)


def _normalize_question(question: str) -> str:
    return " ".join(str(question or "").lower().split())


def _question_tokens(question: str) -> set[str]:
    return set(_TOKEN_RE.findall(_normalize_question(question)))


def _doc_matches(question: str, doc: PreviewKnowledgeBaseDoc) -> bool:
    normalized = _normalize_question(question)
    tokens = _question_tokens(question)
    for trigger in doc.triggers:
        trigger_norm = trigger.lower().strip()
        if " " in trigger_norm:
            if trigger_norm in normalized:
                return True
            continue
        if trigger_norm in tokens:
            return True
    return False


def _load_doc_text(doc: PreviewKnowledgeBaseDoc) -> str:
    if not doc.path.is_file():
        return ""
    return doc.path.read_text(encoding="utf-8").strip()


def retrieve_preview_knowledge_base(question: str) -> list[RetrievedSource]:
    """Return advisory KB snippets matched to the analyst question."""
    sources: list[RetrievedSource] = []
    for doc in _PREVIEW_KB_DOCS:
        if not _doc_matches(question, doc):
            continue
        text = _load_doc_text(doc)
        if not text:
            continue
        sources.append(
            RetrievedSource(
                source_lane="knowledge_base",
                section=doc.section,
                field_path=f"preview_kb/{doc.doc_id}",
                text=text,
                score=0.0,
            )
        )
    return sources


def build_preview_knowledge_base_provider():
    """Callable suitable for ``build_portal_app(chat_knowledge_base_provider=...)``."""

    def _provider(question: str) -> list[RetrievedSource]:
        return retrieve_preview_knowledge_base(question)

    return _provider
