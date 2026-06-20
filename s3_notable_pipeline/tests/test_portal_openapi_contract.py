"""Tests for the vendored portal OpenAPI contract."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
CONTRACT_PATH = PROJECT_ROOT / "docs" / "contracts" / "portal.openapi.json"
FRONTEND_OPENAPI_PATH = (
    PROJECT_ROOT / "frontend" / "analyst-portal" / "openapi" / "portal.openapi.json"
)
ONPREM_OPENAPI_PATH = (
    REPO_ROOT
    / "llm_notable_analysis_onprem_systemd"
    / "frontend"
    / "analyst-portal"
    / "openapi"
    / "portal.openapi.json"
)
SYNC_SCRIPT = PROJECT_ROOT / "scripts" / "sync_portal_openapi_from_onprem.py"

REQUIRED_PATHS = (
    "/health",
    "/ready",
    "/api/capabilities",
    "/api/diagnostics/chat-readiness",
    "/api/cases",
    "/api/cases/{case_id}",
    "/api/cases/{case_id}/raw/{section}",
    "/api/chat",
    "/api/chat/sessions",
    "/api/chat/sessions/{session_id}",
    "/api/chat/sessions/{session_id}/messages",
    "/api/chat/sessions/{session_id}/turns/last",
)

REQUIRED_SCHEMAS = (
    "HealthResponse",
    "PortalCapabilitiesResponse",
    "ChatDependencyStatusResponse",
    "CaseListResponse",
    "CaseDetailResponse",
    "CaseRawSectionResponse",
    "ChatResponseModel",
    "ChatSessionsResponse",
    "ChatSessionMessagesResponse",
    "DeleteChatSessionResponse",
    "DeleteLastChatTurnResponse",
)


class PortalOpenApiContractTests(unittest.TestCase):
    """OpenAPI contract shape tests."""

    def test_required_paths_are_present(self) -> None:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

        self.assertIn(contract["openapi"], {"3.0.3", "3.1.0"})
        for path in REQUIRED_PATHS:
            self.assertIn(path, contract["paths"])

    def test_contract_matches_frontend_vendored_openapi(self) -> None:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        frontend = json.loads(FRONTEND_OPENAPI_PATH.read_text(encoding="utf-8"))
        self.assertEqual(contract, frontend)

    def test_contract_matches_onprem_export_except_title(self) -> None:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        onprem = json.loads(ONPREM_OPENAPI_PATH.read_text(encoding="utf-8"))

        contract_without_title = dict(contract)
        onprem_without_title = dict(onprem)
        contract_without_title["info"] = {
            **contract["info"],
            "title": onprem["info"]["title"],
        }
        self.assertEqual(contract_without_title, onprem_without_title)

    def test_chat_response_schema_has_no_citations(self) -> None:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        chat_schema = contract["components"]["schemas"]["ChatResponseModel"]

        self.assertNotIn("citations", chat_schema.get("properties", {}))
        self.assertEqual(
            set(chat_schema.get("required", [])),
            {"answer", "answer_status"},
        )

    def test_required_component_schemas_are_present(self) -> None:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        schemas = contract["components"]["schemas"]
        for name in REQUIRED_SCHEMAS:
            self.assertIn(name, schemas)

    def test_sync_script_reproduces_committed_contract(self) -> None:
        before = CONTRACT_PATH.read_text(encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(SYNC_SCRIPT)],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        after = CONTRACT_PATH.read_text(encoding="utf-8")
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
