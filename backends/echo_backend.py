from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from .base import ChatChunk, LlmBackend, ModelInfo, RunningModel
from ._tools import convert_tools_to_openai


class EchoMockBackend(LlmBackend):
    """A mock backend that echoes user messages back. Used for testing."""

    def __init__(self, host: Optional[str] = None, api_key: Optional[str] = None, **kwargs: Any) -> None:
        pass

    @property
    def name(self) -> str:
        return "echo"

    @property
    def supports_keep_alive(self) -> bool:
        return False

    def chat(
        self,
        model: str,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        stream: bool = True,
        options: Optional[Dict] = None,
        keep_alive: Optional[Any] = None,
    ) -> Iterator[ChatChunk]:
        last_user_content = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_content = msg.get("content", "")
                break

        wants_thinking = any(
            "thinking" in (m.get("content") or "")
            for m in messages
            if m.get("role") == "system"
        )

        if wants_thinking:
            yield ChatChunk(thinking="*thinking*", done=False)

        if tools and "call_tool:" in last_user_content:
            tool_name = last_user_content.split("call_tool:", 1)[1].strip().split()[0]
            yield ChatChunk(
                tool_calls=[{"function": {"name": tool_name, "arguments": {}}}],
                done=False,
            )
            yield ChatChunk(content=f"Tool called: {tool_name}", done=False)
            yield ChatChunk(done=True)
        else:
            yield ChatChunk(content=last_user_content, done=False)
            yield ChatChunk(done=True)

    def convert_tools(self, tools: List[Any]) -> Optional[List[Dict]]:
        return convert_tools_to_openai(tools)

    def list_models(self) -> List[ModelInfo]:
        return [ModelInfo(name="echo-mock")]

    def list_running(self) -> List[RunningModel]:
        return [RunningModel(name="echo-mock")]

    def show_model(self, model: str) -> Optional[ModelInfo]:
        return ModelInfo(name=model, context_length=4096)

    def stop_model(self, model: str) -> bool:
        return True
