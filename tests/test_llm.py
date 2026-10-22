import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock

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
