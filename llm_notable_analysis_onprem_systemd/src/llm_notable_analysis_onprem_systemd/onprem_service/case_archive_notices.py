"""Deterministic analyst-facing notices for degraded case archive rows."""

from __future__ import annotations

from typing import Any


def build_case_archive_notices(
    *,
    retrieval_status: str | None,
    source_completeness: str | None,
    archive_metadata: dict[str, Any] | None = None,
) -> list[str]:
    """Return operator/analyst notices when archive or chat indexing is degraded."""
    notices: list[str] = []
    status = str(retrieval_status or "").strip().lower()
    completeness = str(source_completeness or "").strip().lower()
    metadata = archive_metadata if isinstance(archive_metadata, dict) else {}

    if status == "failed":
        notices.append(
            "Analyzer processing finished, but portal chat indexing failed for "
            "this case. The case is listed here but is not searchable in chat "
            "until an operator rebuilds case chunks."
        )
    elif status == "pending":
        notices.append(
            "Case archive indexing is still pending. Chat may be limited until "
            "indexing completes."
        )
    elif status == "not_indexed":
        notices.append(
            "This case is not indexed for portal chat retrieval."
        )

    if completeness == "missing_analysis":
        notices.append(
            "Structured analysis was not stored in the case archive. Chat can "
            "use the alert payload only."
        )
    elif completeness == "missing_alert":
        notices.append(
            "The original alert payload is missing from the case archive. Chat "
            "answers may be incomplete."
        )
    elif completeness == "markdown_only":
        notices.append(
            "This case was imported from a legacy markdown report only. Archive "
            "detail and chat coverage may be incomplete."
        )

    if metadata.get("poc_unstructured_output") and completeness != "missing_analysis":
        notices.append(
            "Analyzer output was stored without validated structured analysis."
        )

    return _dedupe_notices(notices)


def _dedupe_notices(notices: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for notice in notices:
        text = str(notice).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered
