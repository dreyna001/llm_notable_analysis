"""Build preview portal cases 1-5 from pre-generated analyzer bundles on disk.

Raw alerts live in ``data/preview_scenarios/alerts/``. Analysis JSON is generated
offline by ``scripts/generate_preview_scenarios.py`` (real ``analyze_alert`` prompt
path) and stored in ``data/preview_scenarios/bundles/``.

Opening the preview portal only reads those bundles. The only live LLM calls in
preview are chatbot synthesis (Bedrock/OpenAI/stub), not case analysis.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from llm_notable_analysis_onprem_systemd.onprem_service.case_store import (
    CaseArchiveRecord,
    build_case_archive_record,
)
from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.local_llm_client import (
    _normalize_and_fill_defaults,
    validate_response_schema,
)

_PREVIEW_SCENARIO_COUNT = 5
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCENARIOS_ROOT = _REPO_ROOT / "data" / "preview_scenarios"


@dataclass(frozen=True)
class PreviewAlertSpec:
    index: int
    slug: str
    search_name: str

    @property
    def alert_path(self) -> Path:
        return _SCENARIOS_ROOT / "alerts" / f"case-{self.index}-{self.slug}.json"


PREVIEW_ALERT_SPECS: tuple[PreviewAlertSpec, ...] = (
    PreviewAlertSpec(1, "beaconing", "Endpoint Beaconing to Newly Registered Domain"),
    PreviewAlertSpec(2, "impossible-travel", "Microsoft Entra ID Impossible Travel with MFA"),
    PreviewAlertSpec(3, "powershell", "Office Application Spawning Encoded PowerShell"),
    PreviewAlertSpec(4, "privilege-escalation", "Non-Privileged User Added to Local Administrators"),
    PreviewAlertSpec(5, "lateral-movement-rdp", "Service Account Interactive RDP to Tier-0 Asset"),
)


def preview_scenarios_root() -> Path:
    return _SCENARIOS_ROOT


def preview_bundle_path(scenario_index: int) -> Path:
    return _SCENARIOS_ROOT / "bundles" / f"case-{scenario_index}.json"


def prepare_preview_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    """Validate stored analysis matches the analyzer schema."""
    normalized = _normalize_and_fill_defaults(
        analysis,
        spl_query_enabled=False,
        elastic_query_enabled=False,
    )
    ok, err = validate_response_schema(normalized)
    if not ok:
        raise ValueError(f"Preview analysis failed schema validation: {err}")
    metadata = normalized.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        normalized["metadata"] = metadata
    metadata["preview_synthetic"] = True
    metadata.setdefault("preview_source", "stored_analyzer_bundle")
    return normalized


def missing_preview_bundle_paths() -> list[Path]:
    """Return bundle files that must exist before preview can serve cases 1-5."""
    missing: list[Path] = []
    for spec in PREVIEW_ALERT_SPECS:
        path = preview_bundle_path(spec.index)
        if not path.is_file():
            missing.append(path)
    return missing


def ensure_preview_bundles_present() -> None:
    """Fail fast when stored analysis bundles are missing."""
    missing = missing_preview_bundle_paths()
    if not missing:
        return
    lines = "\n".join(f"  - {path}" for path in missing)
    raise SystemExit(
        "Preview cases 1-5 require stored analyzer bundles.\n"
        f"Missing:\n{lines}\n\n"
        "Write stored prompt-aligned bundles (no LLM required):\n"
        "  python llm_notable_analysis_onprem_systemd/scripts/write_preview_bundles.py\n"
        "Or generate via live analyzer LLM (LLM_API_URL):\n"
        "  python llm_notable_analysis_onprem_systemd/scripts/generate_preview_scenarios.py\n"
        "Then restart preview. Only chatbot LLM calls run at portal open time."
    )


def load_preview_bundle(scenario_index: int) -> dict[str, Any]:
    """Load a stored alert+analysis bundle from disk."""
    bundle_path = preview_bundle_path(scenario_index)
    if not bundle_path.is_file():
        raise FileNotFoundError(f"Missing preview bundle: {bundle_path}")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["analysis"] = prepare_preview_analysis(bundle["analysis"])
    return bundle


def build_synthetic_preview_record(
    *,
    config: Config,
    scenario_index: int,
    case_id: str,
    finding_id: str,
    source_filename: str,
    processed_at: datetime,
) -> CaseArchiveRecord:
    """Build one preview archive row from a stored analyzer bundle."""
    bundle = load_preview_bundle(scenario_index)
    record = build_case_archive_record(
        config=config,
        case_id=case_id,
        finding_id=finding_id,
        source_filename=source_filename,
        alert_payload=bundle["alert"],
        analysis=bundle["analysis"],
        report_md_path=f"/reports/{case_id}.md",
        report_html_path=None,
        processed_at=processed_at,
    )
    return replace(record, retrieval_status="ready")


def preview_scenario_count() -> int:
    return _PREVIEW_SCENARIO_COUNT


def list_preview_alert_specs() -> tuple[PreviewAlertSpec, ...]:
    return PREVIEW_ALERT_SPECS
