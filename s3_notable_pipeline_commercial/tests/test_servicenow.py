"""Tests for ServiceNow draft/create helpers."""
# pylint: disable=import-error,no-name-in-module

from __future__ import annotations

import sys
import unittest
import hmac
import hashlib
from pathlib import Path
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.config import Config
from s3_notable_pipeline.servicenow import (
    _approval_signature_payload,
    build_servicenow_incident_draft,
    create_servicenow_incident,
    extract_servicenow_create_approval,
)


def _analysis() -> dict[str, object]:
    return {
        "alert_reconciliation": {
            "verdict": "unknown",
            "confidence": 0.5,
            "one_sentence_summary": "Suspicious login requires triage.",
            "decision_drivers": ["user=alice"],
            "recommended_actions": ["Review VPN logs"],
        }
    }


def _signed_approval(correlation_id: str = "finding-1") -> dict[str, object]:
    approval = {
        "approved": True,
        "approved_by": "analyst@example.test",
        "approval_ref": "CHANGE-1",
        "approved_at": "2026-05-29T00:00:00Z",
    }
    approval["signature"] = hmac.new(
        b"approval-secret",
        _approval_signature_payload(approval, correlation_id=correlation_id).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return approval


class ServiceNowTests(unittest.TestCase):
    """ServiceNow helper behavior tests."""

    def test_draft_creation_has_no_network_side_effect(self) -> None:
        with patch("s3_notable_pipeline.servicenow.requests.post") as mock_post:
            draft = build_servicenow_incident_draft(
                _analysis(),
                config=Config(
                    SERVICENOW_DRAFT_ENABLED=True,
                    SERVICENOW_ASSIGNMENT_GROUP="SOC",
                ),
                notable_id="notable-1",
                finding_id="finding-1",
            )

        self.assertEqual(draft["status"], "success")
        self.assertEqual(draft["incident_payload"]["assignment_group"], "SOC")
        mock_post.assert_not_called()

    def test_create_requires_approval_by_default(self) -> None:
        result = create_servicenow_incident(
            {"correlation_id": "finding-1"},
            config=Config(
                SERVICENOW_CREATE_ENABLED=True,
                SERVICENOW_APPROVAL_HMAC_SECRET_ARN="arn:aws:secretsmanager:us-east-1:123456789012:secret:snow-approval",
            ),
            api_token="token",
            approval={},
        )

        self.assertEqual(result["status"], "denied")
        self.assertIn("approval", result["message"])

    def test_create_posts_approved_incident(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"result": {"sys_id": "sys-1", "number": "INC001"}}

        with patch("s3_notable_pipeline.servicenow.requests.post", return_value=response) as mock_post:
            result = create_servicenow_incident(
                {"correlation_id": "finding-1", "short_description": "test"},
                config=Config(
                    SERVICENOW_CREATE_ENABLED=True,
                    SERVICENOW_BASE_URL="https://snow.example.test",
                    SERVICENOW_APPROVAL_HMAC_SECRET_ARN="arn:aws:secretsmanager:us-east-1:123456789012:secret:snow-approval",
                    SIDE_EFFECT_IDEMPOTENCY_ENABLED=False,
                ),
                api_token="token",
                approval=_signed_approval(),
                approval_hmac_key="approval-secret",
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["number"], "INC001")
        mock_post.assert_called_once()

    def test_extract_approval_metadata(self) -> None:
        approval = extract_servicenow_create_approval(
            {
                "servicenow_create_approval": {
                    "approved": True,
                    "approved_by": "analyst@example.test",
                    "approval_ref": "CHANGE-1",
                }
            }
        )

        self.assertTrue(approval["approved"])
        self.assertEqual(approval["approved_by"], "analyst@example.test")
        self.assertEqual(approval["approval_ref"], "CHANGE-1")

    def test_string_false_approval_is_denied(self) -> None:
        result = create_servicenow_incident(
            {"correlation_id": "finding-1"},
            config=Config(
                SERVICENOW_CREATE_ENABLED=True,
                SERVICENOW_APPROVAL_HMAC_SECRET_ARN="arn:aws:secretsmanager:us-east-1:123456789012:secret:snow-approval",
            ),
            api_token="token",
            approval={"approved": "false", "approved_by": "analyst@example.test"},
            approval_hmac_key="approval-secret",
        )

        self.assertEqual(result["status"], "denied")


if __name__ == "__main__":
    unittest.main()
