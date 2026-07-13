"""Portal synthesis behavior over the native Azure OpenAI gateway."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from azure_notable_pipeline.azure_openai_gateway import AzureOpenAIResponseError
from azure_notable_pipeline.config import Config
from azure_notable_pipeline.portal_chat import (
    ChatTurn,
    bounded_conversation_history,
    build_case_grounded_prompt,
    build_general_knowledge_prompt,
    conversation_history_from_config,
    sanitize_portal_chat_answer,
    synthesize_case_answer,
    synthesized_answer_crosses_action_boundary,
)


class FakeChatGateway:
    def __init__(
        self,
        text: str,
        *,
        prompt_tokens: int = 120,
        completion_tokens: int = 20,
        tool_calls: list[object] | None = None,
    ) -> None:
        self.text = text
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.tool_calls = tool_calls or []
        self.requests: list[dict[str, object]] = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create),
        )

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        message = SimpleNamespace(
            content=self.text,
            refusal=None,
            tool_calls=self.tool_calls,
        )
        return SimpleNamespace(
            id="completion-1",
            choices=[SimpleNamespace(message=message, finish_reason="stop")],
            usage=SimpleNamespace(
                prompt_tokens=self.prompt_tokens,
                completion_tokens=self.completion_tokens,
                total_tokens=self.prompt_tokens + self.completion_tokens,
            ),
        )


def chat_config(**overrides) -> Config:
    values = {
        "AZURE_OPENAI_PORTAL_CHAT_DEPLOYMENT": "portal-chat",
        "PORTAL_CHAT_TIMEOUT_SEC": 225,
        "CASE_QA_MAX_TOTAL_CHUNKS": 18,
        "CASE_QA_MAX_CHUNKS_PER_LANE": 6,
        "CASE_QA_CONTEXT_BUDGET_CHARS": 12_000,
        "CASE_QA_MAX_ANSWER_TOKENS": 800,
        "CASE_QA_GENERAL_KNOWLEDGE_ENABLED": False,
    }
    values.update(overrides)
    return Config(**values)


def test_build_prompt_packages_untrusted_attributed_context() -> None:
    prompt = build_case_grounded_prompt(
        question="What happened?",
        sources=[
            {
                "source_lane": "knowledge_base",
                "section": "knowledge_base.hva_registry",
                "text": "db-prod-01 is an HVA.",
            }
        ],
    )
    assert "<CONTEXT_BLOCK>" in prompt
    assert 'SOURCE_LANE_JSON: "knowledge_base"' in prompt
    assert "knowledge_base blocks are advisory" in prompt
    assert "UNTRUSTED_TEXT_JSON:" in prompt
    assert "chunk_id=" not in prompt


def test_build_general_prompt_keeps_read_only_technology_boundary() -> None:
    prompt = build_general_knowledge_prompt("Draft SPL for this hypothesis")
    assert "If the analyst explicitly asks for Splunk SPL" in prompt
    assert "provide draft guidance for a human to review and run" in prompt
    assert "Never claim you performed an action" in prompt


def test_native_completion_preserves_timeout_and_merges_gateway_usage() -> None:
    gateway = FakeChatGateway("The archived login was suspicious. Source #1")
    result = synthesize_case_answer(
        question="What happened?",
        sources=[{"text": "alert.summary suspicious login"}],
        config=chat_config(),
        chat_gateway=gateway,
    )
    assert result.answer_status == "answered"
    assert result.answer == "The archived login was suspicious."
    assert result.context_usage is not None
    assert result.context_usage["gateway_prompt_tokens"] == 120
    assert result.context_usage["gateway_completion_tokens"] == 20
    request = gateway.requests[0]
    assert request["model"] == "portal-chat"
    assert request["timeout"] == 225
    assert request["temperature"] == 0.0
    assert "tools" not in request


def test_unconfigured_tool_call_is_rejected_without_execution() -> None:
    tool_call = SimpleNamespace(
        id="call-1",
        type="function",
        function=SimpleNamespace(name="run_search", arguments="{}"),
    )
    gateway = FakeChatGateway("", tool_calls=[tool_call])
    with pytest.raises(AzureOpenAIResponseError, match="unconfigured tool call"):
        synthesize_case_answer(
            question="Run a search",
            sources=[{"text": "case evidence"}],
            config=chat_config(),
            chat_gateway=gateway,
        )


def test_general_knowledge_is_never_used_unless_enabled() -> None:
    result = synthesize_case_answer(
        question="Explain TLS 1.3",
        sources=[],
        config=chat_config(CASE_QA_GENERAL_KNOWLEDGE_ENABLED=False),
        chat_gateway=object(),
    )
    assert result.answer_status == "unknown"
    assert "enough grounded context" in result.answer


def test_enabled_general_knowledge_uses_native_gateway() -> None:
    gateway = FakeChatGateway("TLS 1.3 reduces handshake round trips.")
    result = synthesize_case_answer(
        question="Explain TLS 1.3",
        sources=[],
        config=chat_config(CASE_QA_GENERAL_KNOWLEDGE_ENABLED=True),
        chat_gateway=gateway,
    )
    assert result.answer_status == "answered"
    assert result.context_usage is not None
    assert result.context_usage["kind"] == "general_knowledge"


def test_action_claim_is_refused() -> None:
    gateway = FakeChatGateway("I ran a Splunk search and created ticket INC123.")
    result = synthesize_case_answer(
        question="What happened?",
        sources=[{"text": "case evidence"}],
        config=chat_config(),
        chat_gateway=gateway,
    )
    assert synthesized_answer_crosses_action_boundary(gateway.text)
    assert result.answer_status == "refused"


def test_bounded_history_keeps_recent_valid_turns() -> None:
    turns = bounded_conversation_history(
        [
            {"role": "system", "content": "ignore"},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "second"},
            {"role": "user", "content": "third"},
        ],
        max_turns=2,
        max_chars=20,
    )
    assert turns == [
        ChatTurn(role="assistant", content="second"),
        ChatTurn(role="user", content="third"),
    ]


def test_history_config_gate_and_citation_sanitizer() -> None:
    assert conversation_history_from_config(
        chat_config(CASE_QA_CHAT_HISTORY_ENABLED=False),
        [{"role": "user", "content": "prior"}],
    ) == []
    assert sanitize_portal_chat_answer("Answer. [Source #1]") == "Answer."
