"""Stable alert reconciliation verdict contract."""

from __future__ import annotations

from typing import Any

LIKELY_BENIGN = "likely_benign"
LIKELY_MALICIOUS = "likely_malicious"
UNKNOWN = "unknown"

ALLOWED_VERDICTS = (LIKELY_BENIGN, LIKELY_MALICIOUS, UNKNOWN)

_VERDICT_LABELS = {
    LIKELY_BENIGN: "Likely benign",
    LIKELY_MALICIOUS: "Likely malicious",
    UNKNOWN: "Unknown",
}


def normalize_verdict(value: Any) -> str:
    """Normalize model or legacy verdict text into the stable verdict enum."""
    if value is None:
        return UNKNOWN

    text = str(value).strip().casefold()
    if not text:
        return UNKNOWN

    normalized = text.replace("-", "_").replace(" ", "_")
    if normalized in ALLOWED_VERDICTS:
        return normalized

    if (
        "malicious" in text
        or "true positive" in text
        or "true_positive" in normalized
    ):
        return LIKELY_MALICIOUS
    if (
        "benign" in text
        or "false positive" in text
        or "false_positive" in normalized
    ):
        return LIKELY_BENIGN
    return UNKNOWN


def verdict_label(value: Any) -> str:
    """Return a user-facing label for a verdict value."""
    return _VERDICT_LABELS[normalize_verdict(value)]
