"""Tests for approval-gated ServiceNow incident creation."""

from __future__ import annotations

import unittest
from typing import Any, Mapping

from updated_notable_analysis.adapters import ServiceNowIncidentCreateAdapter
from updated_notable_analysis.core.models import WritebackDraft
from updated_notable_analysis.core.vocabulary import WritebackStatus
from updated_notable_analysis.core.writeback import (
    WritebackApproval,
    execute_writeback_with_approval,
)


class _FakeServiceNowIncidentTransport:
    """Fake ServiceNow incident transport that records create calls."""

    def __init__(self, response: Mapping[str, Any] | object) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def create_incident(
        self,
        *,
        payload: Mapping[str, Any],
        timeout_seconds: int,
    ) -> Mapping[str, Any]:
        self.calls.append(
            {
                "payload": dict(payload),
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.response  # type: ignore[return-value]


class TestServiceNowIncidentCreateAdapter(unittest.TestCase):
    """Behavior-focused tests for ServiceNow create writeback."""

    def _draft(self) -> WritebackDraft:
        """Return a valid ServiceNow incident draft fixture."""
        return WritebackDraft(
            target_system="servicenow",
            target_operation="incident_draft",
            summary="Security notable notable-123: triaged",
            body="Updated Notable Analysis Report\n\nCredential misuse likely.",
            routing_key="Security Operations",
            external_ref="notable-123",
            fields={
                "short_description": "Security notable notable-123: triaged",
                "description": "Updated Notable Analysis Report",
                "assignment_group": "Default SOC",
                "category": "security",
                "subcategory": "notable_analysis",
                "impact": "2",
                "urgency": "2",
                "source_system": "splunk",
                "source_record_ref": "notable-123",
                "draft_only": True,
            },
        )

    def test_denied_writeback_does_not_call_servicenow_transport(self) -> None:
        """Missing runtime approval should deny before ServiceNow side effects."""
        transport = _FakeServiceNowIncidentTransport({"sys_id": "should-not-create"})

        result = execute_writeback_with_approval(
            draft=self._draft(),
            adapter=ServiceNowIncidentCreateAdapter(transport=transport),
            approval=WritebackApproval(approved=False),
        )

        self.assertEqual(result.status, WritebackStatus.DENIED)
        self.assertEqual(result.target_system, "servicenow")
        self.assertEqual(result.external_id, "notable-123")
        self.assertEqual(transport.calls, [])

    def test_approved_writeback_creates_servicenow_incident(self) -> None:
        """Approved drafts should create ServiceNow incidents through the transport."""
        transport = _FakeServiceNowIncidentTransport(
            {
                "status": "success",
                "sys_id": "sys-123",
                "number": "INC0010001",
                "message": "Incident created.",
                "metadata": {"request_id": "req-456"},
            }
        )

        result = execute_writeback_with_approval(
            draft=self._draft(),
            adapter=ServiceNowIncidentCreateAdapter(
                transport=transport,
                timeout_seconds=11,
            ),
            approval=WritebackApproval(
                approved=True,
                approved_by="analyst@example.com",
                approval_ref="approval-001",
            ),
        )

        self.assertEqual(
            transport.calls,
            [
                {
                    "payload": {
                        "short_description": "Security notable notable-123: triaged",
                        "description": (
                            "Updated Notable Analysis Report\n\nCredential misuse likely."
                        ),
                        "assignment_group": "Security Operations",
                        "category": "security",
                        "subcategory": "notable_analysis",
                        "impact": "2",
                        "urgency": "2",
                        "source_system": "splunk",
                        "source_record_ref": "notable-123",
                        "correlation_id": "notable-123",
                        "correlation_display": "updated_notable_analysis",
                    },
                    "timeout_seconds": 11,
                }
            ],
        )
        self.assertEqual(result.status, WritebackStatus.SUCCESS)
        self.assertEqual(result.target_system, "servicenow")
        self.assertEqual(result.external_id, "sys-123")
        self.assertEqual(result.message, "Incident created.")
        self.assertEqual(result.metadata["adapter"], "servicenow_incident_create")
        self.assertEqual(result.metadata["number"], "INC0010001")
        self.assertEqual(result.metadata["sys_id"], "sys-123")
        self.assertEqual(result.metadata["request_id"], "req-456")
        self.assertEqual(result.metadata["approved_by"], "analyst@example.com")
        self.assertEqual(result.metadata["approval_ref"], "approval-001")

    def test_adapter_normalizes_error_response(self) -> None:
        """ServiceNow error responses should normalize to WritebackResult."""
        result = ServiceNowIncidentCreateAdapter(
            transport=_FakeServiceNowIncidentTransport(
                {
                    "status": "error",
                    "message": "ServiceNow rejected the payload.",
                    "metadata": {"code": "bad_request"},
                }
            )
        ).write(self._draft())

        self.assertEqual(result.status, WritebackStatus.ERROR)
        self.assertEqual(result.external_id, "notable-123")
        self.assertEqual(result.message, "ServiceNow rejected the payload.")
        self.assertEqual(result.metadata["code"], "bad_request")

    def test_adapter_rejects_non_servicenow_target(self) -> None:
        """ServiceNow create adapter should fail closed for other targets."""
        draft = self._draft()
        draft.target_system = "splunk"

        with self.assertRaises(ValueError):
            ServiceNowIncidentCreateAdapter(
                transport=_FakeServiceNowIncidentTransport({"status": "success"})
            ).write(draft)

    def test_adapter_rejects_non_draft_operation(self) -> None:
        """ServiceNow create adapter should only consume incident drafts."""
        draft = self._draft()
        draft.target_operation = "incident_create"

        with self.assertRaises(ValueError):
            ServiceNowIncidentCreateAdapter(
                transport=_FakeServiceNowIncidentTransport({"status": "success"})
            ).write(draft)

    def test_adapter_rejects_missing_or_non_draft_fields(self) -> None:
        """ServiceNow create adapter requires draft-only ServiceNow fields."""
        missing_fields = self._draft()
        missing_fields.fields = {}

        with self.assertRaises(ValueError):
            ServiceNowIncidentCreateAdapter(
                transport=_FakeServiceNowIncidentTransport({"status": "success"})
            ).write(missing_fields)

        non_draft = self._draft()
        non_draft.fields = {**non_draft.fields, "draft_only": False}

        with self.assertRaises(ValueError):
            ServiceNowIncidentCreateAdapter(
                transport=_FakeServiceNowIncidentTransport({"status": "success"})
            ).write(non_draft)

    def test_adapter_rejects_malformed_transport_response(self) -> None:
        """Transport responses must be mapping-like with supported status values."""
        with self.assertRaises(ValueError):
            ServiceNowIncidentCreateAdapter(
                transport=_FakeServiceNowIncidentTransport(["not", "mapping"])
            ).write(self._draft())

        with self.assertRaises(ValueError):
            ServiceNowIncidentCreateAdapter(
                transport=_FakeServiceNowIncidentTransport({"status": "pending"})
            ).write(self._draft())

    def test_adapter_requires_transport_contract_and_valid_timeout(self) -> None:
        """Adapter construction should validate transport and timeout inputs."""
        with self.assertRaises(ValueError):
            ServiceNowIncidentCreateAdapter(transport=object())  # type: ignore[arg-type]

        with self.assertRaises(ValueError):
            ServiceNowIncidentCreateAdapter(
                transport=_FakeServiceNowIncidentTransport({"status": "success"}),
                timeout_seconds=0,
            )


if __name__ == "__main__":
    unittest.main()
