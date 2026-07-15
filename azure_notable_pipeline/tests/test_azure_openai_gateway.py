from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from azure_notable_pipeline import azure_openai_gateway as gateway


def vector(value: float = 0.0, *, dimensions: int = 1024) -> list[float]:
    return [value] * dimensions


class FakeEmbeddings:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


class FakeCompletions:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


def test_embed_texts_requests_and_enforces_1024_dimensions() -> None:
    embeddings = FakeEmbeddings(
        SimpleNamespace(
            data=[
                SimpleNamespace(index=1, embedding=vector(2.0)),
                SimpleNamespace(index=0, embedding=vector(1.0)),
            ]
        )
    )
    client = SimpleNamespace(embeddings=embeddings)

    result = gateway.embed_texts(
        ["first", "second"],
        gateway=client,
        deployment="embedding-deployment",
    )

    assert len(result) == 2
    assert result[0][0] == 1.0
    assert result[1][0] == 2.0
    assert embeddings.calls == [
        {
            "model": "embedding-deployment",
            "input": ["first", "second"],
            "dimensions": 1024,
            "timeout": 60,
        }
    ]


def test_embed_texts_rejects_dimension_mismatch() -> None:
    client = SimpleNamespace(
        embeddings=FakeEmbeddings(
            SimpleNamespace(data=[SimpleNamespace(index=0, embedding=vector(dimensions=3))])
        )
    )

    with pytest.raises(gateway.AzureOpenAIResponseError, match="dimension mismatch"):
        gateway.embed_texts(["text"], gateway=client, deployment="embedding-deployment")


def test_embeddings_never_fall_back_to_analyzer_deployment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_ANALYSIS_DEPLOYMENT", "customer-analysis-deployment")

    with pytest.raises(
        gateway.AzureOpenAIConfigurationError,
        match="AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT is required",
    ):
        gateway.embed_texts(
            ["text"],
            gateway=SimpleNamespace(embeddings=FakeEmbeddings(None)),
        )


def test_chat_completion_normalizes_text_tools_and_usage() -> None:
    response = SimpleNamespace(
        id="completion-1",
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(
                    content="Review the query before running it.",
                    refusal=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call-1",
                            type="function",
                            function=SimpleNamespace(
                                name="draft_query",
                                arguments='{"backend":"splunk"}',
                            ),
                        )
                    ],
                ),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=6, total_tokens=16),
    )
    completions = FakeCompletions(response)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    tools = [{"type": "function", "function": {"name": "draft_query"}}]

    result = gateway.create_chat_completion(
        messages=[{"role": "user", "content": "Draft SPL"}],
        gateway=client,
        deployment="portal-chat-deployment",
        max_tokens=123,
        tools=tools,
        tool_choice="auto",
    )

    assert result == {
        "id": "completion-1",
        "text": "Review the query before running it.",
        "finish_reason": "tool_calls",
        "refusal": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "draft_query",
                    "arguments": '{"backend":"splunk"}',
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 6, "total_tokens": 16},
    }
    assert completions.calls[0]["model"] == "portal-chat-deployment"
    assert completions.calls[0]["max_tokens"] == 123
    assert completions.calls[0]["timeout"] == 220
    assert completions.calls[0]["tools"] == tools


def test_chat_never_falls_back_to_analyzer_deployment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AZURE_OPENAI_PORTAL_CHAT_DEPLOYMENT", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_ANALYSIS_DEPLOYMENT", "customer-analysis-deployment")

    with pytest.raises(
        gateway.AzureOpenAIConfigurationError,
        match="AZURE_OPENAI_PORTAL_CHAT_DEPLOYMENT is required",
    ):
        gateway.create_chat_completion(
            messages=[{"role": "user", "content": "hello"}],
            gateway=SimpleNamespace(),
        )


def test_chat_timeout_cannot_exceed_function_http_contract() -> None:
    with pytest.raises(gateway.AzureOpenAIRequestError, match="between 1 and 225"):
        gateway.create_chat_completion(
            messages=[{"role": "user", "content": "hello"}],
            gateway=SimpleNamespace(),
            deployment="portal-chat-deployment",
            timeout_seconds=226,
        )
