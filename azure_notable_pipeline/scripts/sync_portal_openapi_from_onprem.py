#!/usr/bin/env python3
"""Sync the shared portal OpenAPI contract into the Azure package."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ONPREM_OPENAPI = (
    REPO_ROOT
    / "llm_notable_analysis_onprem_systemd"
    / "frontend"
    / "analyst-portal"
    / "openapi"
    / "portal.openapi.json"
)
TARGETS = (
    PROJECT_ROOT / "docs" / "contracts" / "portal.openapi.json",
    PROJECT_ROOT / "frontend" / "analyst-portal" / "openapi" / "portal.openapi.json",
)


def main() -> int:
    if not ONPREM_OPENAPI.is_file():
        print(f"Missing on-prem OpenAPI export: {ONPREM_OPENAPI}", file=sys.stderr)
        return 1

    contract = json.loads(ONPREM_OPENAPI.read_text(encoding="utf-8"))
    # The OpenAPI document is a locked cross-cloud contract copied verbatim
    # from the shipped AWS package, including its existing title.
    contract["info"]["title"] = "AWS Notable Analyst Portal API"
    rendered = json.dumps(contract, indent=2, sort_keys=True) + "\n"
    for target in TARGETS:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
        print(f"Wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
