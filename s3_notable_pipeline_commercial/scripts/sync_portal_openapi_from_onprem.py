#!/usr/bin/env python3
"""Sync the shared portal OpenAPI contract into the commercial AWS package."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
ONPREM_OPENAPI = (
    REPO_ROOT
    / "llm_notable_analysis_onprem_systemd"
    / "frontend"
    / "analyst-portal"
    / "openapi"
    / "portal.openapi.json"
)
COMMERCIAL_AWS_TARGETS = (
    PROJECT_ROOT / "docs" / "contracts" / "portal.openapi.json",
    PROJECT_ROOT / "frontend" / "analyst-portal" / "openapi" / "portal.openapi.json",
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
    try:
        chat_request = contract["paths"]["/api/chat"]["post"]["requestBody"]["content"][
            "application/json"
        ]["schema"]
    except (KeyError, TypeError) as exc:
        raise ValueError("on-prem OpenAPI contract is missing the /api/chat request schema") from exc
    chat_request.update(
        {
            "additionalProperties": True,
            "properties": {
                "mode": {"enum": ["selected_case"], "type": "string"},
                "question": {"minLength": 1, "type": "string"},
                "selected_case_id": {"type": "string"},
                "session_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "client_request_id": {
                    "description": "Stable idempotency key for one logical durable chat submission.",
                    "minLength": 8,
                    "maxLength": 128,
                    "pattern": "^[A-Za-z0-9._-]+$",
                    "type": "string",
                },
            },
            "required": ["question", "selected_case_id"],
            "title": "ChatRequest",
            "type": "object",
        }
    )
    rendered = json.dumps(contract, indent=2, sort_keys=True) + "\n"

    for target in COMMERCIAL_AWS_TARGETS:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
        print(f"Wrote {target}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
