"""Generate preview portal bundles by running alerts through the real analyzer LLM path.

Reads raw Splunk-style alerts from ``data/preview_scenarios/alerts/`` and writes
validated analysis bundles to ``data/preview_scenarios/bundles/`` for cases 1-5.

Usage (from repo root with analyzer LLM reachable)::

    .\\.venv\\Scripts\\python.exe llm_notable_analysis_onprem_systemd\\scripts\\generate_preview_scenarios.py

Optional env (same as preview / analyzer):

- ``config.portal-preview.env`` for preview-specific overrides
- ``LLM_API_URL``, ``LLM_MODEL_NAME``, ``LLM_API_TOKEN`` for the analyzer model
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from llm_notable_analysis_onprem_systemd.onprem_service.config import Config, load_config  # noqa: E402
from llm_notable_analysis_onprem_systemd.onprem_service.local_llm_client import (  # noqa: E402
    LocalLLMClient,
    validate_response_schema,
)
from llm_notable_analysis_onprem_systemd.onprem_service.onprem_main import (  # noqa: E402
    _format_alert_for_llm,
)
from llm_notable_analysis_onprem_systemd.onprem_service.ttp_validator import (  # noqa: E402
    TTPValidator,
)
from preview_env import load_optional_preview_env  # noqa: E402
from preview_synthetic_pipeline import (  # noqa: E402
    PREVIEW_ALERT_SPECS,
    preview_bundle_path,
    preview_scenarios_root,
    prepare_preview_analysis,
)


def _analysis_config() -> Config:
    load_optional_preview_env()
    if os.environ.get("LLM_API_URL"):
        return Config(
            LLM_TIMEOUT=int(os.environ.get("LLM_TIMEOUT", "240")),
            LLM_API_URL=os.environ.get("LLM_API_URL", "http://127.0.0.1:4000/v1/chat/completions"),
            LLM_API_TOKEN=os.environ.get("LLM_API_TOKEN", ""),
            LLM_MODEL_NAME=os.environ.get("LLM_MODEL_NAME", "gemma-4-31B-it"),
            LLM_MAX_TOKENS=int(os.environ.get("LLM_MAX_TOKENS", "4096")),
            LLM_STRUCTURED_OUTPUT_MODE=(
                os.environ.get("LLM_STRUCTURED_OUTPUT_MODE", "prompt_json").strip().lower()
                or "prompt_json"
            ),
        )
    return load_config()


def _analyze_alert_file(
    *,
    config: Config,
    alert_path: Path,
    llm_client: LocalLLMClient,
) -> dict:
    raw_content = alert_path.read_text(encoding="utf-8")
    alert_payload = json.loads(raw_content)
    alert_text = _format_alert_for_llm(
        alert_payload,
        raw_content=raw_content,
        content_type="json",
    )
    alert_time = str(alert_payload.get("event_time") or datetime.now(timezone.utc).isoformat())
    result = llm_client.analyze_alert(alert_text, alert_time)
    if result.get("error"):
        raise RuntimeError(f"LLM analysis failed for {alert_path.name}: {result['error']}")
    ok, err = validate_response_schema(result)
    if not ok:
        raise RuntimeError(f"Analysis schema validation failed for {alert_path.name}: {err}")
    return result


def generate_preview_bundles(
    *,
    config: Config | None = None,
    overwrite: bool = False,
) -> list[Path]:
    """Run the analyzer on all five preview alerts and write bundle JSON files."""
    config = config or _analysis_config()
    ids_file = _SRC / "llm_notable_analysis_onprem_systemd/onprem_service/enterprise_attack_v17.1_ids.json"
    llm_client = LocalLLMClient(config, TTPValidator(ids_file))
    bundles_dir = preview_scenarios_root() / "bundles"
    bundles_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for spec in PREVIEW_ALERT_SPECS:
        out_path = preview_bundle_path(spec.index)
        if out_path.is_file() and not overwrite:
            print(f"skip case-{spec.index} (exists): {out_path}")
            continue
        alert_path = spec.alert_path
        if not alert_path.is_file():
            raise FileNotFoundError(f"Missing preview alert fixture: {alert_path}")
        print(f"analyzing case-{spec.index}: {spec.search_name} ...")
        analysis = _analyze_alert_file(
            config=config,
            alert_path=alert_path,
            llm_client=llm_client,
        )
        analysis = prepare_preview_analysis(analysis)
        alert_payload = json.loads(alert_path.read_text(encoding="utf-8"))
        bundle = {
            "scenario_index": spec.index,
            "case_id": f"case-{spec.index}",
            "finding_id": str(alert_payload.get("notable_id") or f"syn-{spec.index:03d}"),
            "search_name": spec.search_name,
            "source_filename": alert_path.name,
            "alert": alert_payload,
            "analysis": analysis,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        out_path.write_text(
            json.dumps(bundle, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {out_path}")
        written.append(out_path)
    return written


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run preview alerts through the real analyzer LLM and cache bundles."
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Regenerate bundles even when output files already exist.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    paths = generate_preview_bundles(overwrite=args.overwrite)
    if not paths:
        print("No bundles written (all present; use --overwrite to regenerate).")
    else:
        print(f"Done. Wrote {len(paths)} bundle(s). Restart preview_portal_ui.py to load them.")


if __name__ == "__main__":
    main()
