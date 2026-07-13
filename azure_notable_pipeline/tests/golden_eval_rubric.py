"""Golden eval rubric loader and scorer for analyzer disposition checks."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from azure_notable_pipeline.ttp_analyzer import validate_response_schema  # pylint: disable=import-error
from s3_notable_pipeline.verdicts import ALLOWED_VERDICTS, normalize_verdict  # pylint: disable=import-error

GOLDEN_EVAL_ROOT = PROJECT_ROOT / "data" / "golden_eval"


@dataclass(frozen=True)
class GoldenEvalCase:
    """One golden alert plus rubric expectations."""

    id: str
    title: str
    alert_path: Path
    reference_analysis_path: Path
    expected_verdict: str
    evidence_any: tuple[str, ...]


def load_manifest(root: Path | None = None) -> list[GoldenEvalCase]:
    """Load golden eval cases from manifest.json."""
    base = root or GOLDEN_EVAL_ROOT
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest.get("cases"), list) or not manifest["cases"]:
        raise ValueError("manifest.json must contain a non-empty cases array")

    cases: list[GoldenEvalCase] = []
    seen_ids: set[str] = set()
    for row in manifest["cases"]:
        case_id = str(row["id"])
        if case_id in seen_ids:
            raise ValueError(f"duplicate golden eval case id: {case_id}")
        seen_ids.add(case_id)

        expected_verdict = normalize_verdict(str(row["expected_verdict"]))
        if expected_verdict not in ALLOWED_VERDICTS:
            raise ValueError(
                f"{case_id}: unsupported expected_verdict {expected_verdict!r}"
            )

        alert_path = base / str(row["alert"])
        reference_analysis_path = base / str(row["reference_analysis"])
        for path in (alert_path, reference_analysis_path):
            if not path.is_file():
                raise FileNotFoundError(f"missing golden eval fixture: {path}")

        reference = load_json(reference_analysis_path)
        reference_verdict = normalize_verdict(
            str(reference.get("alert_reconciliation", {}).get("verdict", ""))
        )
        if reference_verdict != expected_verdict:
            raise ValueError(
                f"{case_id}: manifest expected_verdict={expected_verdict} "
                f"but reference has {reference_verdict}"
            )

        evidence_any = tuple(str(item) for item in row.get("evidence_any", []))
        if not evidence_any:
            raise ValueError(f"{case_id}: evidence_any must be non-empty")

        cases.append(
            GoldenEvalCase(
                id=case_id,
                title=str(row["title"]),
                alert_path=alert_path,
                reference_analysis_path=reference_analysis_path,
                expected_verdict=expected_verdict,
                evidence_any=evidence_any,
            )
        )
    return cases


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from disk."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def evaluate_analysis_rubric(
    analysis: dict[str, Any],
    *,
    expected_verdict: str,
    evidence_any: tuple[str, ...],
) -> list[str]:
    """Return rubric failure messages; empty list means pass."""
    failures: list[str] = []

    ok, err = validate_response_schema(analysis)
    if not ok:
        failures.append(f"schema: {err}")

    expected = normalize_verdict(expected_verdict)
    actual = normalize_verdict(
        str(analysis.get("alert_reconciliation", {}).get("verdict", ""))
    )
    if actual != expected:
        failures.append(f"verdict: got {actual}, want {expected}")

    blob = json.dumps(analysis, ensure_ascii=True).lower()
    for token in evidence_any:
        if token.lower() not in blob:
            failures.append(f"missing evidence token: {token}")

    return failures
