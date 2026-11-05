import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from scout_ai import llm


def test_refuses_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    with pytest.raises(llm.LLMError, match="ANTHROPIC_API_KEY"):
        asyncio.run(llm.complete("hi"))


def test_joins_text_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def fake_query(**kwargs: Any) -> AsyncIterator[AssistantMessage]:
        assert kwargs["options"].tools == []
        yield AssistantMessage(
            content=[TextBlock(text="Hello, "), TextBlock(text="world")], model="m"
        )

    monkeypatch.setattr(llm, "query", fake_query)
    assert asyncio.run(llm.complete("hi")) == "Hello, world"


def _result(**kwargs: Any) -> ResultMessage:
    base: dict[str, Any] = {
        "subtype": "success",
        "duration_ms": 1,
        "duration_api_ms": 1,
        "is_error": False,
        "num_turns": 2,
        "session_id": "s",
    }
    return ResultMessage(**(base | kwargs))


def test_complete_json_returns_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}}

    async def fake_query(**kwargs: Any) -> AsyncIterator[ResultMessage]:
        assert kwargs["options"].output_format == {"type": "json_schema", "schema": schema}
        assert kwargs["options"].tools == []
        yield _result(structured_output={"n": 7})

    monkeypatch.setattr(llm, "query", fake_query)
    assert asyncio.run(llm.complete_json("hi", schema=schema)) == {"n": 7}


@pytest.mark.parametrize(
    "message", [_result(is_error=True, result="overloaded"), _result(structured_output=None)]
)
def test_complete_json_errors(monkeypatch: pytest.MonkeyPatch, message: ResultMessage) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def fake_query(**kwargs: Any) -> AsyncIterator[ResultMessage]:
        yield message

    monkeypatch.setattr(llm, "query", fake_query)
    with pytest.raises(llm.LLMError):
        asyncio.run(llm.complete_json("hi", schema={}))
