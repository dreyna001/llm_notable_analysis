#!/usr/bin/env python3
"""Export the analyst portal OpenAPI schema for frontend contract generation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.portal_app import build_portal_app


def _export_config() -> Config:
    return Config(
        PORTAL_ENABLED=True,
        CASE_ARCHIVE_ENABLED=True,
        PORTAL_BIND_HOST="127.0.0.1",
        PORTAL_PAGE_SIZE=50,
        PORTAL_TRUSTED_USER_HEADER="X-Forwarded-User",
        PORTAL_PROXY_SECRET="portal-secret",
    )


def main() -> int:
    app = build_portal_app(_export_config())
    schema = app.openapi()
    output_path = (
        PROJECT_ROOT
        / "frontend"
        / "analyst-portal"
        / "openapi"
        / "portal.openapi.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
