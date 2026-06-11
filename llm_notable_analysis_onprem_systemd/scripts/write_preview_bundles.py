"""Write validated preview bundles from stored analyzer-shaped analysis."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SRC = _SCRIPTS.parent / "src"
for path in (_SCRIPTS, _SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from preview_stored_analysis import STORED_PREVIEW_ANALYSIS  # noqa: E402
from preview_synthetic_pipeline import (  # noqa: E402
    PREVIEW_ALERT_SPECS,
    prepare_preview_analysis,
    preview_bundle_path,
    preview_scenarios_root,
)


def write_preview_bundles() -> list[Path]:
    bundles_dir = preview_scenarios_root() / "bundles"
    bundles_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for spec in PREVIEW_ALERT_SPECS:
        builder = STORED_PREVIEW_ANALYSIS.get(spec.index)
        if builder is None:
            raise KeyError(f"No stored analysis for case-{spec.index}")
        alert = json.loads(spec.alert_path.read_text(encoding="utf-8"))
        analysis = prepare_preview_analysis(builder(alert))
        analysis["metadata"]["preview_source"] = "stored_prompt_aligned_fixture"
        bundle = {
            "scenario_index": spec.index,
            "case_id": f"case-{spec.index}",
            "finding_id": str(alert.get("notable_id") or f"syn-{spec.index:03d}"),
            "search_name": spec.search_name,
            "source_filename": spec.alert_path.name,
            "alert": alert,
            "analysis": analysis,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        out_path = preview_bundle_path(spec.index)
        out_path.write_text(json.dumps(bundle, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        written.append(out_path)
        print(f"wrote {out_path}")
    return written


if __name__ == "__main__":
    paths = write_preview_bundles()
    print(f"Done. Wrote {len(paths)} bundle(s).")
