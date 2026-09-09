"""Unit tests for the ChatChunk, ModelInfo, and RunningModel dataclasses.

Verifies default values, mutability, and that the objects can be used as
simple containers throughout the engine and chat layers.
"""

from __future__ import annotations

import os
import sys

current_file = os.path.abspath(__file__)
lama_ole_dir = os.path.abspath(os.path.join(os.path.dirname(current_file), ".."))
if lama_ole_dir not in sys.path:
    sys.path.insert(0, lama_ole_dir)

from backends.base import ChatChunk, ModelInfo, RunningModel


class TestChatChunk:
    def test_defaults(self):
        c = ChatChunk()
        assert c.content is None
        assert c.thinking is None
        assert c.tool_calls is None
        assert c.done is False
        assert c.prompt_eval_count is None
        assert c.eval_count is None

    def test_kwargs(self):
        c = ChatChunk(content="hi", done=True, eval_count=5)
        assert c.content == "hi"
        assert c.done is True
        assert c.eval_count == 5
        assert c.thinking is None

    def test_update(self):
        c = ChatChunk()
        c.content = "hello"
        c.done = True
        assert c.content == "hello"


class TestModelInfo:
    def test_minimal(self):
        m = ModelInfo(name="test:model")
        assert m.name == "test:model"
        assert m.size is None
        assert m.context_length is None
        assert m.backend_specific == {}

    def test_full(self):
        m = ModelInfo(
            name="m",
            size=4096,
            context_length=32768,
            backend_specific={"key": 1},
        )
        assert m.context_length == 32768


class TestRunningModel:
    def test_minimal(self):
        r = RunningModel(name="running:model")
        assert r.name == "running:model"
        assert r.context_length is None

    def test_with_context(self):
        r = RunningModel(name="r", context_length=2048, backend_specific={"k": 2})
        assert r.context_length == 2048