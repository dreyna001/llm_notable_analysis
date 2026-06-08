import unittest
import uuid
from datetime import datetime, timedelta, timezone

# Tests run with PYTHONPATH pointing at the src layout.
# pylint: disable=import-error,no-name-in-module

from fastapi.testclient import TestClient

from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.portal_app import build_portal_app

from .test_case_chat_history import _HistoryFakeConnection

_USER_HEADERS = {"X-Forwarded-User": "analyst@example.com"}
_AUTH_HEADERS = {
    **_USER_HEADERS,
    "X-Notable-Portal-Proxy-Secret": "portal-secret",
}
_OTHER_AUTH_HEADERS = {
    "X-Forwarded-User": "other@example.com",
    "X-Notable-Portal-Proxy-Secret": "portal-secret",
}


class _FakeEmbeddingModel:
    def encode(self, texts, show_progress_bar=False, convert_to_numpy=True):
        del show_progress_bar, convert_to_numpy
        return [[1.0] + [0.0] * 767 for _text in texts]


def _history_config(**overrides: object) -> Config:
    defaults: dict[str, object] = {
        "PORTAL_ENABLED": True,
        "CASE_ARCHIVE_ENABLED": True,
        "CASE_QA_ENABLED": True,
        "CASE_QA_GLOBAL_RETRIEVAL_ENABLED": True,
        "CASE_QA_GENERAL_KNOWLEDGE_ENABLED": False,
        "CASE_QA_CHAT_HISTORY_ENABLED": True,
        "CASE_QA_MAX_MESSAGES_PER_SESSION": 20,
        "PORTAL_PROXY_SECRET": "portal-secret",
    }
    defaults.update(overrides)
    return Config(**defaults)


def _chunk_row() -> tuple:
    return (
        "case-1:case_analysis:analysis.evidence_vs_inference:0",
        "case-1",
        "case_analysis",
        "analysis.evidence_vs_inference",
        "$.evidence_vs_inference.evidence[0]",
        "Evidence text.",
        {"field_path": "$.evidence_vs_inference.evidence[0]"},
        0.9,
    )


def _session_bundle(
    *,
    user_id: str = "analyst@example.com",
    mode: str = "global_archive",
    selected_case_id: str | None = None,
    message_pairs: int = 2,
) -> tuple[str, _HistoryFakeConnection]:
    session_id = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    messages = []
    for index in range(message_pairs):
        messages.append(
            (f"u{index}", session_id, "user", f"question-{index}", "[]")
        )
        messages.append(
            (f"a{index}", session_id, "assistant", f"answer-{index}", "[]", "answered")
        )
    connection = _HistoryFakeConnection(
        sessions={
            session_id: (
                session_id,
                user_id,
                mode,
                selected_case_id,
                expires_at,
            )
        },
        messages=messages,
    )
    return session_id, connection


class TestPortalChatHistoryHttp(unittest.TestCase):
    def test_list_chat_sessions_requires_auth(self) -> None:
        client = TestClient(
            build_portal_app(
                _history_config(),
                connect=lambda _dsn: _HistoryFakeConnection(),
            )
        )
        response = client.get("/api/chat/sessions")
        self.assertEqual(response.status_code, 401)

    def test_list_chat_sessions_returns_saved_sessions(self) -> None:
        session_id, connection = _session_bundle(message_pairs=1)
        client = TestClient(
            build_portal_app(
                _history_config(),
                connect=lambda _dsn: connection,
            )
        )
        response = client.get("/api/chat/sessions", headers=_AUTH_HEADERS)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["history_enabled"])
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["session_id"], session_id)

    def test_get_chat_session_messages_success(self) -> None:
        session_id, connection = _session_bundle(message_pairs=2)
        client = TestClient(
            build_portal_app(
                _history_config(),
                connect=lambda _dsn: connection,
            )
        )
        response = client.get(
            f"/api/chat/sessions/{session_id}/messages",
            headers=_AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["session_id"], session_id)
        self.assertEqual(len(payload["messages"]), 4)
        assistant_messages = [
            message for message in payload["messages"] if message["role"] == "assistant"
        ]
        self.assertEqual(len(assistant_messages), 2)
        self.assertEqual(assistant_messages[0]["answer_status"], "answered")

    def test_get_chat_session_messages_user_isolation(self) -> None:
        session_id, connection = _session_bundle()
        client = TestClient(
            build_portal_app(
                _history_config(),
                connect=lambda _dsn: connection,
            )
        )
        response = client.get(
            f"/api/chat/sessions/{session_id}/messages",
            headers=_OTHER_AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_chat_session_success(self) -> None:
        session_id, connection = _session_bundle()
        client = TestClient(
            build_portal_app(
                _history_config(),
                connect=lambda _dsn: connection,
            )
        )
        response = client.delete(
            f"/api/chat/sessions/{session_id}",
            headers=_AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["deleted"])
        self.assertNotIn(session_id, connection.sessions)

    def test_delete_last_chat_turn_requires_auth(self) -> None:
        session_id, connection = _session_bundle()
        client = TestClient(
            build_portal_app(
                _history_config(),
                connect=lambda _dsn: connection,
            )
        )
        response = client.delete(f"/api/chat/sessions/{session_id}/turns/last")
        self.assertEqual(response.status_code, 401)

    def test_delete_last_chat_turn_success(self) -> None:
        session_id, connection = _session_bundle(message_pairs=2)
        client = TestClient(
            build_portal_app(
                _history_config(),
                connect=lambda _dsn: connection,
            )
        )
        response = client.delete(
            f"/api/chat/sessions/{session_id}/turns/last",
            headers=_AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["deleted"])
        self.assertEqual(payload["deleted_messages"], 2)
        self.assertEqual(len(connection.messages), 2)

    def test_delete_last_chat_turn_404_for_unknown_session(self) -> None:
        client = TestClient(
            build_portal_app(
                _history_config(),
                connect=lambda _dsn: _HistoryFakeConnection(),
            )
        )
        response = client.delete(
            f"/api/chat/sessions/{uuid.uuid4()}/turns/last",
            headers=_AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_last_chat_turn_409_on_message_count_mismatch(self) -> None:
        session_id, connection = _session_bundle(message_pairs=2)
        client = TestClient(
            build_portal_app(
                _history_config(),
                connect=lambda _dsn: connection,
            )
        )
        response = client.delete(
            f"/api/chat/sessions/{session_id}/turns/last?expected_message_count=2",
            headers=_AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 409)

    def test_delete_last_chat_turn_user_isolation(self) -> None:
        session_id, connection = _session_bundle()
        client = TestClient(
            build_portal_app(
                _history_config(),
                connect=lambda _dsn: connection,
            )
        )
        response = client.delete(
            f"/api/chat/sessions/{session_id}/turns/last",
            headers=_OTHER_AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(len(connection.messages), 4)

    def test_post_chat_resumes_existing_session(self) -> None:
        session_id, connection = _session_bundle(
            mode="global_archive",
            message_pairs=1,
        )
        connection.row_pages = [[_chunk_row()], []]
        client = TestClient(
            build_portal_app(
                _history_config(),
                connect=lambda _dsn: connection,
                chat_embedding_model=_FakeEmbeddingModel(),
                chat_synthesizer=lambda _question, _sources: "Follow-up answer.",
            )
        )
        response = client.post(
            "/api/chat",
            json={
                "mode": "global_archive",
                "question": "What else should I review?",
                "session_id": session_id,
            },
            headers=_AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_id"], session_id)
        self.assertEqual(len(connection.messages), 4)

    def test_post_chat_rejects_session_scope_mismatch(self) -> None:
        session_id, connection = _session_bundle(
            mode="selected_case",
            selected_case_id="case-1",
        )
        connection.row_pages = [[_chunk_row()], []]
        synthesize_calls = 0

        def synthesize(_question, _sources):
            nonlocal synthesize_calls
            synthesize_calls += 1
            return "Should not run."

        client = TestClient(
            build_portal_app(
                _history_config(),
                connect=lambda _dsn: connection,
                chat_embedding_model=_FakeEmbeddingModel(),
                chat_synthesizer=synthesize,
            )
        )
        response = client.post(
            "/api/chat",
            json={
                "mode": "global_archive",
                "question": "Wrong mode follow-up?",
                "session_id": session_id,
            },
            headers=_AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("scope", response.json()["detail"])
        self.assertEqual(synthesize_calls, 0)

    def test_post_chat_rejects_expired_session(self) -> None:
        session_id = str(uuid.uuid4())
        expired_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        synthesize_calls = 0

        def synthesize(_question, _sources):
            nonlocal synthesize_calls
            synthesize_calls += 1
            return "Should not run."

        connection = _HistoryFakeConnection(
            row_pages=[[_chunk_row()], []],
            sessions={
                session_id: (
                    session_id,
                    "analyst@example.com",
                    "global_archive",
                    None,
                    expired_at,
                )
            },
        )
        client = TestClient(
            build_portal_app(
                _history_config(),
                connect=lambda _dsn: connection,
                chat_embedding_model=_FakeEmbeddingModel(),
                chat_synthesizer=synthesize,
            )
        )
        response = client.post(
            "/api/chat",
            json={
                "mode": "global_archive",
                "question": "Follow-up on expired session?",
                "session_id": session_id,
            },
            headers=_AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 410)
        self.assertIn("expired", response.json()["detail"])
        self.assertEqual(synthesize_calls, 0)

    def test_post_chat_returns_404_for_missing_session(self) -> None:
        connection = _HistoryFakeConnection(row_pages=[[_chunk_row()], []])
        synthesize_calls = 0

        def synthesize(_question, _sources):
            nonlocal synthesize_calls
            synthesize_calls += 1
            return "Should not run."

        client = TestClient(
            build_portal_app(
                _history_config(),
                connect=lambda _dsn: connection,
                chat_embedding_model=_FakeEmbeddingModel(),
                chat_synthesizer=synthesize,
            )
        )
        response = client.post(
            "/api/chat",
            json={
                "mode": "global_archive",
                "question": "Follow-up on missing session?",
                "session_id": "00000000-0000-0000-0000-000000000001",
            },
            headers=_AUTH_HEADERS,
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("not found", response.json()["detail"])
        self.assertEqual(synthesize_calls, 0)

    def test_post_chat_rejects_full_session_before_synthesis(self) -> None:
        session_id, connection = _session_bundle(
            mode="global_archive",
            message_pairs=2,
        )
        connection.row_pages = [[_chunk_row()], []]
        synthesize_calls = 0

        def synthesize(_question, _sources):
            nonlocal synthesize_calls
            synthesize_calls += 1
            return "Should not run."

        client = TestClient(
            build_portal_app(
                _history_config(CASE_QA_MAX_MESSAGES_PER_SESSION=4),
                connect=lambda _dsn: connection,
                chat_embedding_model=_FakeEmbeddingModel(),
                chat_synthesizer=synthesize,
            )
        )
        response = client.post(
            "/api/chat",
            json={
                "mode": "global_archive",
                "question": "Will this fit?",
                "session_id": session_id,
            },
            headers=_AUTH_HEADERS,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("message limit", response.json()["detail"])
        self.assertEqual(synthesize_calls, 0)


if __name__ == "__main__":
    unittest.main()
