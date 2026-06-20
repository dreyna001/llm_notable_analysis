#!/usr/bin/env python3
"""Sync the shared portal OpenAPI contract from the on-prem export into AWS packages."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ONPREM_OPENAPI = (
    REPO_ROOT
    / "llm_notable_analysis_onprem_systemd"
    / "frontend"
    / "analyst-portal"
    / "openapi"
    / "portal.openapi.json"
)
AWS_TARGETS = (
    REPO_ROOT / "s3_notable_pipeline" / "docs" / "contracts" / "portal.openapi.json",
    REPO_ROOT
    / "s3_notable_pipeline"
    / "frontend"
    / "analyst-portal"
    / "openapi"
    / "portal.openapi.json",
)
AWS_TITLE = "AWS Notable Analyst Portal API"


def main() -> int:
    if not ONPREM_OPENAPI.is_file():
        print(
            f"Missing on-prem OpenAPI export: {ONPREM_OPENAPI}",
            file=sys.stderr,
        )
        print(
            "Run llm_notable_analysis_onprem_systemd/scripts/export_portal_openapi.py first.",
            file=sys.stderr,
        )
        return 1

    contract = json.loads(ONPREM_OPENAPI.read_text(encoding="utf-8"))
    contract["info"]["title"] = AWS_TITLE
    rendered = json.dumps(contract, indent=2, sort_keys=True) + "\n"

    for target in AWS_TARGETS:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
        print(f"Wrote {target}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
