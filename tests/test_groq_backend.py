"""Unit tests for backends/groq_backend.py.

Covers message sanitization (name removal, system-merging, tool_call_id pairing),
option mapping & temperature clamping, reasoning handling (parsed format,
delta.reasoning, <think> tag handling), tool calling, and model info extraction.
"""

from __future__ import annotations

import json
import os
import sys
from io import BytesIO
from unittest.mock import patch

import pytest

current_file = os.path.abspath(__file__)
lama_ole_dir = os.path.abspath(os.path.join(os.path.dirname(current_file), ".."))
if lama_ole_dir not in sys.path:
    sys.path.insert(0, lama_ole_dir)

from backends.base import ChatChunk
from backends.factory import create_backend
from backends.groq_backend import GroqBackend
from tool_base.models import Tool


def _sse_raw(*lines: str) -> BytesIO:
    """Build a BytesIO from lines as SSE wire bytes, ending with [DONE]."""
    text = "\n".join(lines) + "\n"
    return BytesIO(text.encode("utf-8"))


class TestGroqSanitizeMessages:
    def _san(self, messages):
        return GroqBackend._sanitize_messages(messages)

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
        assert clean[0]["role"] == "system"
        assert clean[0]["content"] == "a\n\nb"

    def test_name_and_internal_keys_stripped(self):
        msgs = [
            {
                "role": "user",
                "name": "alice",
                "content": "hello",
                "thinking": "hidden",
                "timestamp": "2026-09-11",
            }
        ]
        clean = self._san(msgs)
        assert clean[0]["role"] == "user"
        assert "name" not in clean[0]
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


class TestGroqChatStreaming:
    @staticmethod
    def _make_chunk_event(content=None, reasoning=None, reasoning_content=None, tool_calls=None, finish=None, usage=None):
        delta: dict = {}
        if content is not None:
            delta["content"] = content
        if reasoning is not None:
            delta["reasoning"] = reasoning
        if reasoning_content is not None:
            delta["reasoning_content"] = reasoning_content
        if tool_calls is not None:
            delta["tool_calls"] = tool_calls
        choice: dict = {"delta": delta}
        if finish:
            choice["finish_reason"] = finish
        ev: dict = {"choices": [choice]}
        if usage:
            ev["usage"] = usage
        return json.dumps(ev)

    def _run_chat(self, events_json, options=None, tools=None, model="qwen/qwen3.6-27b"):
        backend = GroqBackend(host="https://api.groq.com/openai", api_key="fake_key")
        sse_body = BytesIO(
            ("".join(f"data: {e}\n" for e in events_json) + "data: [DONE]\n").encode("utf-8")
        )
        with patch("backends.groq_backend.urlopen", return_value=sse_body):
            chunks = list(
                backend.chat(
                    model=model,
                    messages=[{"role": "user", "content": "hi"}],
                    options=options,
                    tools=tools,
                )
            )
        return chunks

    def test_content_and_done(self):
        chunks = self._run_chat([
            self._make_chunk_event(content="hello"),
            self._make_chunk_event(finish="stop", usage={"prompt_tokens": 10, "completion_tokens": 5}),
        ])
        assert any(c.content == "hello" for c in chunks)
        assert chunks[-1].done is True
        assert chunks[-1].prompt_eval_count == 10
        assert chunks[-1].eval_count == 5

    def test_reasoning_stream_yields_thinking(self):
        chunks = self._run_chat([
            self._make_chunk_event(reasoning="I am thinking"),
            self._make_chunk_event(content="The answer is 42"),
            self._make_chunk_event(finish="stop"),
        ])
        think_chunks = [c for c in chunks if c.thinking]
        assert len(think_chunks) == 1
        assert think_chunks[0].thinking == "I am thinking"
        assert any(c.content == "The answer is 42" for c in chunks)

    def test_think_tag_stream_yields_thinking(self):
        chunks = self._run_chat([
            self._make_chunk_event(content="<think>internal thought</think>result"),
            self._make_chunk_event(finish="stop"),
        ])
        think_chunks = [c for c in chunks if c.thinking]
        content_chunks = [c for c in chunks if c.content]
        assert think_chunks[0].thinking == "internal thought"
        assert content_chunks[0].content == "result"

    def test_tool_call_accumulation(self):
        chunks = self._run_chat([
            self._make_chunk_event(
                tool_calls=[{"index": 0, "id": "call_123", "function": {"name": "calc", "arguments": ""}}]
            ),
            self._make_chunk_event(
                tool_calls=[{"index": 0, "function": {"arguments": '{"x": 10}'}}]
            ),
            self._make_chunk_event(finish="tool_calls"),
        ])
        tc_chunks = [c for c in chunks if c.tool_calls]
        assert len(tc_chunks) == 1
        tc = tc_chunks[0].tool_calls[0]
        assert tc["id"] == "call_123"
        assert tc["function"]["name"] == "calc"
        assert tc["function"]["arguments"] == '{"x": 10}'


class TestGroqOptionsAndPayloads:
    def test_temperature_zero_clamped(self):
        backend = GroqBackend(host="https://api.groq.com/openai", api_key="fake_key")
        captured_payload = None

        def fake_urlopen(req, timeout=None):
            nonlocal captured_payload
            captured_payload = json.loads(req.data.decode("utf-8"))
            return _sse_raw('data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}')

        with patch("backends.groq_backend.urlopen", side_effect=fake_urlopen):
            list(backend.chat(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": "hi"}], options={"temperature": 0.0, "max_tokens": 100}))

        assert captured_payload is not None
        assert captured_payload["temperature"] == 1e-5
        assert captured_payload["max_completion_tokens"] == 100
        assert "max_tokens" not in captured_payload

    def test_tool_use_enforces_parsed_reasoning(self):
        backend = GroqBackend(host="https://api.groq.com/openai", api_key="fake_key")
        captured_payload = None

        def fake_urlopen(req, timeout=None):
            nonlocal captured_payload
            captured_payload = json.loads(req.data.decode("utf-8"))
            return _sse_raw('data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}')

        tools = [{"type": "function", "function": {"name": "test", "parameters": {}}}]
        with patch("backends.groq_backend.urlopen", side_effect=fake_urlopen):
            list(backend.chat(model="qwen/qwen3.6-27b", messages=[{"role": "user", "content": "hi"}], tools=tools))

        assert captured_payload is not None
        assert captured_payload["reasoning_format"] == "parsed"
        assert captured_payload["tool_choice"] == "auto"


class TestGroqModelManagement:
    def test_list_models_and_show_model(self):
        backend = GroqBackend(host="https://api.groq.com/openai", api_key="fake_key")
        fake_models_resp = {
            "data": [
                {"id": "llama-3.3-70b-versatile", "context_window": 131072},
                {"id": "whisper-large-v3", "context_window": 448},
            ]
        }

        with patch.object(backend, "_get_json", return_value=fake_models_resp):
            models = backend.list_models()
            assert len(models) == 2
            assert models[0].name == "llama-3.3-70b-versatile"
            assert models[0].context_length == 131072

            info = backend.show_model("llama-3.3-70b-versatile")
            assert info is not None
            assert info.name == "llama-3.3-70b-versatile"
            assert info.context_length == 131072


class TestGroqFactoryAndCompat:
    def test_create_backend_groq(self):
        b = create_backend("groq", api_key="test_key")
        assert b.name == "groq"
        assert b.supports_keep_alive is False
        assert b.supports_thinking is True
        assert b._base_url == "https://api.groq.com/openai"

    def test_convert_tools(self):
        backend = create_backend("groq", api_key="test_key")
        tool = Tool(name="fn", description="d", parameters={}, fn=lambda: None)
        result = backend.convert_tools([tool])
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "fn"
        assert backend.convert_tools([]) is None
