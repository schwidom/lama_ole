"""Unit tests for backends/openai_compat_backend.py.

Covers SSE event parsing, message sanitization (extra-key stripping,
system-merging, tool_call_id pairing), reasoning_content -> thinking
mapping, incremental tool_call accumulation, list_models/show_model
parse, convert_tools, and the LlamaCppBackend subclass.
"""

from __future__ import annotations

import json
import os
import sys
from io import BytesIO

import pytest

current_file = os.path.abspath(__file__)
lama_ole_dir = os.path.abspath(os.path.join(os.path.dirname(current_file), ".."))
if lama_ole_dir not in sys.path:
    sys.path.insert(0, lama_ole_dir)

from backends.base import ChatChunk
from backends.llamacpp_backend import LlamaCppBackend
from backends.openai_compat_backend import OpenAICompatBackend, _read_sse_events


def _sse_raw(*lines: str) -> BytesIO:
    """Build a BytesIO from lines as SSE wire bytes, ending with ``[DONE]``."""
    text = "\n".join(lines) + "\n"
    return BytesIO(text.encode("utf-8"))


class TestReadSSEEvents:
    def test_single_event(self):
        resp = _sse_raw("data: {\"id\": 1}")
        assert list(_read_sse_events(resp)) == ['{"id": 1}']

    def test_two_events(self):
        resp = _sse_raw('data: {"a":1}', 'data: {"b":2}')
        assert list(_read_sse_events(resp)) == ['{"a":1}', '{"b":2}']

    def test_done_sentinel_stops(self):
        resp = _sse_raw('data: {"a":1}', 'data: [DONE]', 'data: {"b":2}')
        assert list(_read_sse_events(resp)) == ['{"a":1}']

    def test_blank_lines_ignored(self):
        resp = _sse_raw('', 'data: {"x":true}', '')
        assert list(_read_sse_events(resp)) == ['{"x":true}']

    def test_comment_lines_ignored(self):
        resp = _sse_raw(': keep-alive', 'data: {"ok":true}')
        assert list(_read_sse_events(resp)) == ['{"ok":true}']

    def test_trailing_payload_no_newline(self):
        data = b'data: {"tail": true}\n'
        assert list(_read_sse_events(BytesIO(data))) == ['{"tail": true}']

    def test_single_line_no_trailing_newline(self):
        data = b'data: {"chunked": true}'
        assert list(_read_sse_events(BytesIO(data))) == ['{"chunked": true}']


class TestSanitizeMessages:
    def _san(self, messages):
        return OpenAICompatBackend._sanitize_messages(messages)

    def test_single_system_preserved(self):
        msgs = [{"role": "system", "content": "sys"}]
        clean = self._san(msgs)
        assert clean == [{"role": "system", "content": "sys"}]

    def test_multiple_systems_merged(self):
        msgs = [
            {"role": "system", "content": "a"},
            {"role": "user", "content": "hi"},
            {"role": "system", "content": "b"},
        ]
        clean = self._san(msgs)
        system_msg = clean[0]
        assert system_msg["role"] == "system"
        assert "a\n\nb" == system_msg["content"]

    def test_thinking_key_stripped_from_assistant(self):
        msgs = [{"role": "assistant", "content": "ok", "thinking": "hidden", "timestamp": "2026-01-01"}]
        clean = self._san(msgs)
        assert clean[0]["role"] == "assistant"
        assert "thinking" not in clean[0]
        assert "timestamp" not in clean[0]

    def test_tool_call_id_pairing(self):
        msgs = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"function": {"name": "get_weather", "arguments": {"city": "Berlin"}}}],
            },
            {
                "role": "tool",
                "content": "sunny",
                "tool_name": "get_weather",
            },
        ]
        clean = self._san(msgs)
        tc = clean[0]["tool_calls"][0]
        assert tc["id"] == "call_0"
        assert tc["function"]["name"] == "get_weather"
        assert clean[1]["tool_call_id"] == "call_0"

    def test_tool_message_preserves_existing_tool_call_id(self):
        msgs = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"function": {"name": "fn", "arguments": {}}}],
            },
            {
                "role": "tool",
                "content": "ok",
                "tool_call_id": "preserved_id",
            },
        ]
        clean = self._san(msgs)
        assert clean[1]["tool_call_id"] == "preserved_id"

    def test_assistant_dict_arguments_stringified(self):
        msgs = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"function": {"name": "fn", "arguments": {"x": 1}}}],
            },
        ]
        clean = self._san(msgs)
        fn = clean[0]["tool_calls"][0]["function"]
        assert fn["arguments"] == '{"x": 1}'


class TestChatReasoningAndToolCalls:
    """Test the chat() SSE-to-ChatChunk streaming by mocking urlopen."""

    @staticmethod
    def _make_chunk_event(content=None, reasoning=None, tool_calls=None, finish=None, usage=None):
        delta: dict = {}
        if content is not None:
            delta["content"] = content
        if reasoning is not None:
            delta["reasoning_content"] = reasoning
        if tool_calls is not None:
            delta["tool_calls"] = tool_calls
        choice: dict = {"delta": delta}
        if finish:
            choice["finish_reason"] = finish
        ev: dict = {"choices": [choice]}
        if usage:
            ev["usage"] = usage
        return json.dumps(ev)

    def _run_chat(self, events_json):
        backend = OpenAICompatBackend(host="http://fake:1234")
        sse_body = BytesIO(
            ("".join(f"data: {e}\n" for e in events_json) + "data: [DONE]\n").encode("utf-8")
        )
        # Patch urlopen to return our fake sse_body
        from unittest.mock import patch
        with patch("backends.openai_compat_backend.urlopen", return_value=sse_body):
            chunks = list(backend.chat(model="m", messages=[{"role": "user", "content": "hi"}]))
        return chunks

    def test_content_and_done(self):
        chunks = self._run_chat([
            self._make_chunk_event(content="hello"),
            self._make_chunk_event(finish="stop", usage={"prompt_tokens": 10, "completion_tokens": 5}),
        ])
        assert any(c.content == "hello" for c in chunks)
        assert chunks[-1].done is True
        assert chunks[-1].eval_count == 5

    def test_reasoning_maps_to_thinking(self):
        chunks = self._run_chat([
            self._make_chunk_event(reasoning="let me think"),
            self._make_chunk_event(content="the answer is 42"),
            self._make_chunk_event(finish="stop"),
        ])
        think_chunks = [c for c in chunks if c.thinking]
        assert think_chunks[0].thinking == "let me think"
        assert any(c.content == "the answer is 42" for c in chunks)

    def test_tool_call_accumulation(self):
        chunks = self._run_chat([
            self._make_chunk_event(
                tool_calls=[{"index": 0, "id": "call_0", "function": {"name": "get_weather", "arguments": ""}}]
            ),
            self._make_chunk_event(
                tool_calls=[{"index": 0, "function": {"arguments": '{"city":"X"}'}}]
            ),
            self._make_chunk_event(finish="tool_calls"),
        ])
        tc_chunks = [c for c in chunks if c.tool_calls]
        assert len(tc_chunks) == 1
        tc = tc_chunks[0].tool_calls[0]
        assert tc["function"]["name"] == "get_weather"
        assert tc["function"]["arguments"] == '{"city":"X"}'


class TestLLamaCppSubclass:
    def test_name(self):
        b = LlamaCppBackend.__new__(LlamaCppBackend)
        assert b._default_backend_name == "llamacpp"

    def test_inherits_sanitize(self):
        assert hasattr(OpenAICompatBackend, "_sanitize_messages")

    def test_instance_name_property(self):
        import importlib
        from backends.factory import create_backend
        b = create_backend("llamacpp", host="http://x:8080")
        assert b.name == "llamacpp"
        assert b.supports_keep_alive is False

    def test_convert_tools(self):
        from tool_base.models import Tool
        from backends.factory import create_backend
        backend = create_backend("llamacpp", host="http://x:8080")
        t = Tool(name="fn", description="d", parameters={}, fn=lambda: None)
        result = backend.convert_tools([t])
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "fn"
        assert backend.convert_tools([]) is None