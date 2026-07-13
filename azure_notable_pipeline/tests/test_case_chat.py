"""Selected-case portal Q&A over native Azure application boundaries."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from azure_notable_pipeline import case_chat
from azure_notable_pipeline.config import Config
from azure_notable_pipeline.portal_chat import PortalAnswer


class FakeCaseStore:
    def __init__(self, retrieval_status: str = "ready") -> None:
        self.retrieval_status = retrieval_status
        self.get_case_calls: list[tuple[str, str]] = []

    def get_case(self, container_name: str, case_id: str):
        self.get_case_calls.append((container_name, case_id))
        return {"case_id": case_id, "retrieval_status": self.retrieval_status}


class FakeChunkSource:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def load_chunks(self, case_id: str, *, limit: int):
        self.calls.append((case_id, limit))
        return [
            {
                "case_id": case_id,
                "chunk_id": "chunk-1",
                "section": "alert.summary",
                "search_text": "dest_host=db-prod-01 user=svc-backup suspicious login",
                "embedding": [0.0] * 1024,
            }
        ]


class FakeEmbeddingGateway:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.embeddings = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(
            data=[SimpleNamespace(index=0, embedding=[0.0] * 1024)]
        )


def qa_config(**overrides) -> Config:
    values = {
        "PORTAL_ENABLED": True,
        "PORTAL_AUTH_MODE": "iam",
        "PORTAL_ENTRA_REQUIRED_APP_ROLE": "Portal.Analyst",
        "CASE_QA_ENABLED": True,
        "CASE_EMBED_QUEUE_NAME": "case-embed-invocations",
        "CASE_INDEX_CONTAINER": "case-index",
        "CASE_ARCHIVE_CONTAINER": "output",
        "CASE_ARCHIVE_CHUNKS_PREFIX": "case_chunks",
        "AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT": "embeddings",
        "AZURE_OPENAI_PORTAL_CHAT_DEPLOYMENT": "portal-chat",
        "CASE_QA_MAX_QUESTION_CHARS": 2_000,
        "CASE_QA_MAX_TOTAL_CHUNKS": 18,
        "CASE_QA_MAX_CHUNKS_PER_LANE": 6,
        "CASE_QA_CONTEXT_BUDGET_CHARS": 12_000,
        "CASE_QA_GENERAL_KNOWLEDGE_ENABLED": False,
    }
    values.update(overrides)
    return Config(**values)


def test_pending_case_returns_empty_list_order_retrieval() -> None:
    chunks = case_chat.retrieve_selected_case_chunks(
        case_id="case-1",
        config=qa_config(),
        case_store=FakeCaseStore("pending"),
        chunk_source=FakeChunkSource(),
    )
    assert chunks == []


def test_selected_case_uses_1024_dimension_query_embedding(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_synthesize(**kwargs):
        captured.update(kwargs)
        return PortalAnswer(answer="Summary.", answer_status="answered")

    monkeypatch.setattr(case_chat, "build_chat_knowledge_sources", lambda **_kwargs: [])
    monkeypatch.setattr(case_chat, "synthesize_case_answer", fake_synthesize)
    embedding = FakeEmbeddingGateway()
    case_store = FakeCaseStore()
    result = case_chat.answer_selected_case_question(
        case_id="case-1",
        question="What happened to db-prod-01?",
        config=qa_config(),
        case_store=case_store,
        chunk_source=FakeChunkSource(),
        embedding_gateway=embedding,
    )
    assert result.answer_status == "answered"
    assert embedding.requests[0]["dimensions"] == 1024
    assert embedding.requests[0]["model"] == "embeddings"
    assert case_store.get_case_calls == [("case-index", "case-1")]
    sources = captured["sources"]
    assert sources[0]["source_lane"] == "current_case"
    assert "db-prod-01" in sources[0]["text"]


def test_selected_case_builds_attached_case_aware_kb_query(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_kb_sources(*, question: str, **_kwargs):
        captured["question"] = question
        return []

    monkeypatch.setattr(case_chat, "build_chat_knowledge_sources", fake_kb_sources)
    monkeypatch.setattr(
        case_chat,
        "synthesize_case_answer",
        lambda **_kwargs: PortalAnswer(answer="Summary.", answer_status="answered"),
    )
    case_chat.answer_selected_case_question(
        case_id="case-5",
        question="Summarize this case.",
        config=qa_config(),
        case_store=FakeCaseStore(),
        chunk_source=FakeChunkSource(),
        embedding_gateway=FakeEmbeddingGateway(),
    )
    assert "Summarize this case." in captured["question"]
    assert "db-prod-01" in captured["question"]
    assert "selected_case_id=case-5" in captured["question"]


def test_disabled_case_qa_does_not_touch_native_dependencies() -> None:
    result = case_chat.answer_selected_case_question(
        case_id="case-1",
        question="What happened?",
        config=qa_config(CASE_QA_ENABLED=False),
        case_store=object(),
    )
    assert result == PortalAnswer(answer="Case Q&A is disabled.", answer_status="unknown")


def test_handler_adapter_requires_authenticated_user() -> None:
    with pytest.raises(ValueError, match="authenticated user"):
        case_chat.answer_portal_chat(
            selected_case_id="case-1",
            question="What happened?",
            config=qa_config(),
            cosmos_store=FakeCaseStore(),
            user_id="",
        )


def test_handler_adapter_bounds_plain_prior_transcript(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_answer(**kwargs):
        captured.update(kwargs)
        return PortalAnswer(answer="Follow-up.", answer_status="answered")

    monkeypatch.setattr(case_chat, "answer_selected_case_question", fake_answer)
    result = case_chat.answer_portal_chat(
        selected_case_id="case-1",
        question="Expand on that.",
        config=qa_config(
            CASE_QA_CHAT_HISTORY_ENABLED=True,
            CHAT_SESSIONS_CONTAINER="chat-sessions",
            CHAT_MESSAGES_CONTAINER="chat-messages",
            CASE_QA_MAX_CONVERSATION_TURNS=2,
        ),
        cosmos_store=FakeCaseStore(),
        blob_store=object(),
        user_id="user-1",
        prior_transcript=[
            {"role": "user", "content": "First"},
            {"role": "assistant", "content": "Second"},
            {"role": "user", "content": "Third"},
        ],
    )
    assert result.answer == "Follow-up."
    assert [turn.content for turn in captured["conversation_history"]] == ["Second", "Third"]
    assert captured["case_store"].retrieval_status == "ready"
