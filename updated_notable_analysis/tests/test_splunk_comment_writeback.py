"""Tests for approval-gated Splunk comment writeback."""

from __future__ import annotations

import unittest
from typing import Any, Mapping

from updated_notable_analysis.adapters import SplunkCommentWritebackAdapter
from updated_notable_analysis.core.models import WritebackDraft
from updated_notable_analysis.core.vocabulary import WritebackStatus
from updated_notable_analysis.core.writeback import (
    WritebackApproval,
    execute_writeback_with_approval,
)


class _FakeSplunkCommentTransport:
    """Fake Splunk comment transport that records calls."""

    def __init__(self, response: Mapping[str, Any] | object) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def post_comment(
        self,
        *,
        notable_id: str,
        comment: str,
        timeout_seconds: int,
        metadata: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self.calls.append(
            {
                "notable_id": notable_id,
                "comment": comment,
                "timeout_seconds": timeout_seconds,
                "metadata": dict(metadata),
            }
        )
        return self.response  # type: ignore[return-value]


class TestSplunkCommentWriteback(unittest.TestCase):
    """Behavior-focused tests for Splunk comment writeback."""

    def _draft(self, body: str = "Analyst summary: suspicious auth pattern.") -> WritebackDraft:
        """Return a valid Splunk comment draft fixture."""
        return WritebackDraft(
            target_system="splunk",
            target_operation="notable_comment",
            summary="Suspicious auth investigation summary",
            body=body,
            routing_key="security_content",
            external_ref="notable-123",
            fields={"source": "updated_notable_analysis"},
        )

    def test_denied_writeback_does_not_call_transport(self) -> None:
        """Missing runtime approval should deny before adapter side effects."""
        transport = _FakeSplunkCommentTransport({"comment_id": "should-not-write"})

        result = execute_writeback_with_approval(
            draft=self._draft(),
            adapter=SplunkCommentWritebackAdapter(transport=transport),
            approval=WritebackApproval(approved=False),
        )

        self.assertEqual(result.status, WritebackStatus.DENIED)
        self.assertEqual(result.target_system, "splunk")
        self.assertEqual(result.external_id, "notable-123")
        self.assertEqual(transport.calls, [])

    def test_approved_writeback_posts_bounded_comment(self) -> None:
        """Approved Splunk comment drafts should be posted and normalized."""
        transport = _FakeSplunkCommentTransport(
            {
                "status": "success",
                "comment_id": "comment-456",
                "message": "Comment created.",
                "metadata": {"request_id": "req-789"},
            }
        )

        result = execute_writeback_with_approval(
            draft=self._draft(),
            adapter=SplunkCommentWritebackAdapter(
                transport=transport,
                max_comment_chars=100,
                timeout_seconds=7,
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
                    "notable_id": "notable-123",
                    "comment": "Analyst summary: suspicious auth pattern.",
                    "timeout_seconds": 7,
                    "metadata": {
                        "source": "updated_notable_analysis",
                        "routing_key": "security_content",
                        "target_operation": "notable_comment",
                        "summary": "Suspicious auth investigation summary",
                    },
                }
            ],
        )
        self.assertEqual(result.status, WritebackStatus.SUCCESS)
        self.assertEqual(result.target_system, "splunk")
        self.assertEqual(result.external_id, "comment-456")
        self.assertEqual(result.metadata["adapter"], "splunk_comment")
        self.assertEqual(result.metadata["notable_id"], "notable-123")
        self.assertEqual(result.metadata["request_id"], "req-789")
        self.assertEqual(result.metadata["approved_by"], "analyst@example.com")
        self.assertEqual(result.metadata["approval_ref"], "approval-001")

    def test_approval_requires_approver_and_reference(self) -> None:
        """Approved runtime writeback state requires audit identifiers."""
        with self.assertRaises(ValueError):
            WritebackApproval(approved=True, approved_by="analyst@example.com")

        with self.assertRaises(ValueError):
            WritebackApproval(approved=True, approval_ref="approval-001")

    def test_adapter_rejects_non_splunk_target(self) -> None:
        """Splunk comment adapter should fail closed for other targets."""
        draft = self._draft()
        draft.target_system = "servicenow"

        with self.assertRaises(ValueError):
            SplunkCommentWritebackAdapter(
                transport=_FakeSplunkCommentTransport({"status": "success"})
            ).write(draft)

    def test_adapter_rejects_non_comment_operation(self) -> None:
        """Splunk comment adapter should only allow notable comment operations."""
        draft = self._draft()
        draft.target_operation = "notable_update"

        with self.assertRaises(ValueError):
            SplunkCommentWritebackAdapter(
                transport=_FakeSplunkCommentTransport({"status": "success"})
            ).write(draft)

    def test_adapter_rejects_missing_notable_id(self) -> None:
        """Splunk comment drafts require external_ref as the notable id."""
        draft = self._draft()
        draft.external_ref = None

        with self.assertRaises(ValueError):
            SplunkCommentWritebackAdapter(
                transport=_FakeSplunkCommentTransport({"status": "success"})
            ).write(draft)

    def test_adapter_rejects_oversized_comment_body(self) -> None:
        """Splunk comment body length should be bounded before transport calls."""
        transport = _FakeSplunkCommentTransport({"status": "success"})

        with self.assertRaises(ValueError):
            SplunkCommentWritebackAdapter(
                transport=transport,
                max_comment_chars=5,
            ).write(self._draft(body="too long"))

        self.assertEqual(transport.calls, [])

    def test_adapter_normalizes_error_response(self) -> None:
        """Transport error responses should still normalize to WritebackResult."""
        result = SplunkCommentWritebackAdapter(
            transport=_FakeSplunkCommentTransport(
                {
                    "status": "error",
                    "message": "Splunk rejected the comment.",
                    "metadata": {"code": "bad_request"},
                }
            )
        ).write(self._draft())

        self.assertEqual(result.status, WritebackStatus.ERROR)
        self.assertEqual(result.external_id, "notable-123")
        self.assertEqual(result.message, "Splunk rejected the comment.")
        self.assertEqual(result.metadata["code"], "bad_request")

    def test_adapter_rejects_malformed_transport_response(self) -> None:
        """Transport responses must be mapping-like with supported status values."""
        with self.assertRaises(ValueError):
            SplunkCommentWritebackAdapter(
                transport=_FakeSplunkCommentTransport(["not", "mapping"])
            ).write(self._draft())

        with self.assertRaises(ValueError):
            SplunkCommentWritebackAdapter(
                transport=_FakeSplunkCommentTransport({"status": "pending"})
            ).write(self._draft())


if __name__ == "__main__":
    unittest.main()
