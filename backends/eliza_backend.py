from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from .base import ChatChunk, LlmBackend, ModelInfo, RunningModel
from ._tools import convert_tools_to_openai
from .eliza_scripts import ELIZA_SCRIPTS


class ElizaBackend(LlmBackend):
    """A deterministic scripted backend. Accepts a script of predefined responses.

    A script can be supplied explicitly (``script=[...]``) or resolved by model
    name: if no explicit script is given, a ``chat()`` call whose ``model``
    matches a key in ``ELIZA_SCRIPTS`` loads that named script on first use.
    This is what makes ``--backend eliza -m read_test`` (etc.) work.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        api_key: Optional[str] = None,
        script: Optional[List[Dict]] = None,
        **kwargs: Any,
    ) -> None:
        self._script = list(script or [])
        self._index = 0

    @property
    def name(self) -> str:
        return "eliza"

    @property
    def supports_keep_alive(self) -> bool:
        return False

    def _resolve_script(self, model: str) -> None:
        """Load a named script by model name if none was given explicitly."""
        if not self._script:
            named = ELIZA_SCRIPTS.get(model)
            if named:
                self._script = list(named)
                self._index = 0

    def chat(
        self,
        model: str,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        stream: bool = True,
        options: Optional[Dict] = None,
        keep_alive: Optional[Any] = None,
    ) -> Iterator[ChatChunk]:
        self._resolve_script(model)
        wants_thinking = any(
            "thinking" in (m.get("content") or "")
            for m in messages
            if m.get("role") == "system"
        )

        if wants_thinking:
            yield ChatChunk(thinking="*thinking*", done=False)

        if self._index < len(self._script):
            entry = self._script[self._index]
            self._index += 1
            yield ChatChunk(
                content=entry["content"],
                tool_calls=entry.get("tool_calls"),
                done=False,
            )
            yield ChatChunk(done=True)
        else:
            yield ChatChunk(content="[Eliza: script exhausted]", done=False)
            yield ChatChunk(done=True)

    def convert_tools(self, tools: List[Any]) -> Optional[List[Dict]]:
        return convert_tools_to_openai(tools)

    def list_models(self) -> List[ModelInfo]:
        named = [ModelInfo(name=name) for name in ELIZA_SCRIPTS]
        return [ModelInfo(name="eliza-mock")] + named

    def list_running(self) -> List[RunningModel]:
        return [RunningModel(name="eliza-mock")]

    def show_model(self, model: str) -> Optional[ModelInfo]:
        return ModelInfo(name=model, context_length=4096)

    def stop_model(self, model: str) -> bool:
        return True
