"""Tests for text-based tool calls (`call:name{...}`) inside the stream.

Some models emit function calls as plain text instead of populating the
structured ``tool_calls`` channel — when those tokens land in the backend's
thinking stream they previously were printed verbatim inside the thought block,
never executed, and leaked back into the context. Covers the parsing helpers
and the ``run_with_tools()`` integration.
"""

import os
import sys

import pytest

current_file = os.path.abspath(__file__)
lama_ole_dir = os.path.abspath(os.path.join(os.path.dirname(current_file), ".."))
if lama_ole_dir not in sys.path:
    sys.path.insert(0, lama_ole_dir)

from backends.base import ChatChunk  # noqa: E402
from tool_base import run_with_tools  # noqa: E402
from tool_base.engine import (  # noqa: E402
    _brace_balanced,
    _clean_stream_text,
    _extract_text_tool_calls,
    _flush_pending_display,
    _lenient_json_fix,
    _parse_tool_arguments,
    _stream_to_display,
    _text_call_tail_start,
)
from tool_base.loop_states import StateManager  # noqa: E402
from tool_base.models import Tool  # noqa: E402

POLLUTED_DIRECTIVE = (
    "call:create_new_file{"
    "content:<|\"|>Name: Bob Ross\nAnschrift: Westminster Allee. 15\nE-Mail: bob@gmx.uk<|\"|>,"
    "path:<|\"|>contacts.txt<|\"|>}"
)

POLLUTED_THINKING = (
    "I have both files now.\n"
    "</thought><|tool_call|>" + POLLUTED_DIRECTIVE + "<tool_call|><|tool_response>"
)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


class TestCleanStreamText:
    def test_strips_marker_tokens(self):
        text = "</thought><|tool_call|>call:read_file{\"path\":\"a.txt\"}<tool_call|><|tool_response>"
        assert "<|tool_call|>" not in _clean_stream_text(text)
        assert "<tool_call|>" not in _clean_stream_text(text)
        assert "</thought>" not in _clean_stream_text(text)
        assert "<|tool_response>" not in _clean_stream_text(text)
        assert "call:read_file" in _clean_stream_text(text)

    def test_restores_quote_token(self):
        cleaned = _clean_stream_text('content:<|"|>x<|"|>')
        assert cleaned == 'content:"x"'

    def test_strips_qwen3_native_thinking_tokens(self):
        text = "<|begin_of_thought|>let me think<|end_of_thought|>inner"
        cleaned = _clean_stream_text(text)
        assert "begin_of_thought" not in cleaned
        assert "end_of_thought" not in cleaned
        assert "let me think" in cleaned
        assert "inner" in cleaned

    def test_empty_input(self):
        assert _clean_stream_text("") == ""
        assert _clean_stream_text(None) == ""


class TestBraceBalanced:
    def test_simple_object(self):
        text = 'call:foo{"a":1}'
        close = _brace_balanced(text, text.index("{"))
        assert text[close] == "}"

    def test_nested_objects(self):
        text = 'call:foo{"a":{"b":[1,2]},"c":3}'
        close = _brace_balanced(text, text.index("{"))
        assert text[close] == "}"

    def test_braces_inside_string_ignored(self):
        text = 'call:foo{"a":"x { not a brace } y"}'
        close = _brace_balanced(text, text.index("{"))
        assert text[close] == "}"
        assert len(text) - 1 == close

    def test_unclosed_returns_none(self):
        assert _brace_balanced("call:foo{a:1", "call:foo{".index("{")) is None


class TestLenientJsonFix:
    def test_quotes_bare_keys(self):
        fixed = _lenient_json_fix('{content:"x",path:"y"}')
        assert fixed == '{"content":"x","path":"y"}'

    def test_unquoted_keys_with_newlines_in_string(self):
        obj = "{ " + POLLUTED_DIRECTIVE.split("{", 1)[1]
        fixed = _lenient_json_fix(obj)
        assert '"content"' in fixed
        assert '"path"' in fixed

    def test_escapes_control_chars_in_strings(self):
        fixed = _lenient_json_fix('{a:"x\ny"}')
        assert '"x\\ny"' in fixed

    def test_quoted_json_passes_through(self):
        fixed = _lenient_json_fix('{"city": "Berlin", "n": 3}')
        assert fixed == '{"city": "Berlin", "n": 3}'

    def test_colon_inside_string_not_treated_as_key(self):
        fixed = _lenient_json_fix('{keep:"x, y:z"}')
        assert fixed == '{"keep":"x, y:z"}'


class TestParseToolArguments:
    def test_plain_json(self):
        assert _parse_tool_arguments('{"city": "Berlin"}') == {"city": "Berlin"}

    def test_unquoted_keys_and_quote_tokens(self):
        raw = "{" + POLLUTED_DIRECTIVE.split("{", 1)[1]  # the {…} argument object
        parsed = _parse_tool_arguments(raw)
        assert parsed == {
            "content": "Name: Bob Ross\nAnschrift: Westminster Allee. 15\nE-Mail: bob@gmx.uk",
            "path": "contacts.txt",
        }

    def test_invalid_returns_none(self):
        assert _parse_tool_arguments("this is not json") is None
        assert _parse_tool_arguments("{a:") is None

    def test_non_dict_returns_none(self):
        assert _parse_tool_arguments("[1, 2]") is None


class TestTextCallTailStart:
    def test_no_call_returns_none(self):
        assert _text_call_tail_start("just some thinking") is None

    def test_unterminated_call_is_held(self):
        text = "think call:foo{\"a\":1"
        start = _text_call_tail_start(text)
        assert start is not None
        assert text[start:].startswith("call:foo")

    def test_just_closed_call_at_end_is_held(self):
        text = "think call:foo{\"a\":1}"
        start = _text_call_tail_start(text)
        assert start is not None
        assert text[start:].startswith("call:foo")

    def test_completed_call_followed_by_prose_is_not_held(self):
        text = "think call:foo{\"a\":1} and then more"
        assert _text_call_tail_start(text) is None


class TestExtractTextToolCalls:
    def test_extracts_and_removes_directive(self):
        text = "reasoning... " + POLLUTED_DIRECTIVE + " more"
        remaining, calls = _extract_text_tool_calls(text)
        assert calls == [
            {
                "function": {
                    "name": "create_new_file",
                    "arguments": {
                        "content": "Name: Bob Ross\nAnschrift: Westminster Allee. 15\nE-Mail: bob@gmx.uk",
                        "path": "contacts.txt",
                    },
                }
            }
        ]
        assert "call:" not in remaining
        assert remaining == "reasoning...  more"

    def test_multiple_calls(self):
        text = 'call:get_weather{"city":"x"} and call:get_time{}'
        remaining, calls = _extract_text_tool_calls(text)
        assert len(calls) == 2
        assert calls[0]["function"]["name"] == "get_weather"
        assert calls[1]["function"]["name"] == "get_time"
        assert calls[1]["function"]["arguments"] == {}
        assert remaining == " and "

    def test_unparseable_left_intact(self):
        text = "call:foo{this is not json}"
        remaining, calls = _extract_text_tool_calls(text)
        assert calls == []
        assert remaining == text

    def test_empty_input(self):
        assert _extract_text_tool_calls("") == ("", [])
        assert _extract_text_tool_calls(None) == (None, [])


class TestStreamToDisplay:
    def test_plain_text_flushes_immediately(self):
        seen = []
        pending = _stream_to_display("", "hello world", seen.append)
        assert pending == ""
        assert seen == ["hello world"]

    def test_open_directive_held_back(self):
        seen = []
        pending = _stream_to_display("", 'think call:foo{"a":1', seen.append)
        assert pending == 'call:foo{"a":1'
        assert seen == ["think "]

    def test_held_directive_flushed_after_prose(self):
        seen = []
        pending = _stream_to_display("", 'call:foo{"a":1}', seen.append)
        pending = _stream_to_display(pending, " and done", seen.append)
        assert pending == ""
        assert seen == ['call:foo{"a":1} and done']


class TestFlushPendingDisplay:
    def test_directive_suppressed_remainder_emitted(self):
        seen = []
        _flush_pending_display("note " + POLLUTED_DIRECTIVE, seen.append)
        assert seen == ["note "]
        assert "call:" not in "".join(seen)

    def test_empty_pending(self):
        seen = []
        assert _flush_pending_display("", seen.append) == ""
        assert seen == []


# ---------------------------------------------------------------------------
# run_with_tools() integration
# ---------------------------------------------------------------------------


def _chunk(thinking=None, content=None, tool_calls=None):
    return ChatChunk(thinking=thinking, content=content, tool_calls=tool_calls)


class StreamClient:
    def __init__(self, streams):
        self._streams = list(streams)
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self._streams.pop(0)


def _run_kwargs(client, messages, loaded_tools=(), **extra):
    kwargs = dict(
        client=client,
        model="test",
        messages=messages,
        loaded_tools=list(loaded_tools),
        backend_tools=None,
        options={},
        keep_alive=None,
        show_thinking=True,
        no_safety_system_prompt=True,
        system_prompt=None,
        skill_text=None,
        color="never",
        state_manager=StateManager(),
    )
    kwargs.update(extra)
    return kwargs


def _echo_tool(name):
    def fn(**kwargs):
        return {"status": "success", "data": str(kwargs)}

    return Tool(name=name, description="echo", parameters={}, fn=fn)


def test_text_tool_call_in_thinking_is_executed():
    streams = [
        iter([_chunk(thinking=POLLUTED_THINKING)]),
        iter([_chunk(content="done")]),
    ]
    client = StreamClient(streams)
    messages = [{"role": "user", "content": "write contacts.txt"}]
    run_with_tools(
        **_run_kwargs(client, messages, loaded_tools=[_echo_tool("create_new_file")])
    )
    # The directive must appear as a structured assistant tool call.
    assistant = [m for m in messages if m.get("role") == "assistant"][0]
    assert assistant["tool_calls"][0]["function"]["name"] == "create_new_file"
    assert assistant["tool_calls"][0]["function"]["arguments"]["path"] == "contacts.txt"
    # The raw directive is gone from stored thinking / content.
    stored = assistant.get("thinking", "") + (assistant.get("content") or "")
    assert "call:create_new_file" not in stored
    assert "<|tool_call|>" not in stored
    # The tool result round-trips and a final answer follows.
    roles = [m["role"] for m in messages]
    assert roles == ["system", "user", "assistant", "tool", "assistant"]


def test_text_tool_call_markers_not_printed_in_thought_block(capsys):
    streams = [
        iter([_chunk(thinking=POLLUTED_THINKING)]),
        iter([_chunk(content="done")]),
    ]
    client = StreamClient(streams)
    messages = [{"role": "user", "content": "write contacts.txt"}]
    run_with_tools(
        **_run_kwargs(
            client, messages, loaded_tools=[_echo_tool("create_new_file")], verbose=1
        )
    )
    out = capsys.readouterr().out
    assert "<|tool_call|>" not in out
    assert "call:create_new_file" not in out
    assert "I have both files now." in out


def test_tool_round_thinking_not_reinjected_into_content():
    streams = [
        iter(
            [
                _chunk(
                    thinking="plan the move",
                    tool_calls=[
                        {
                            "function": {
                                "name": "create_new_file",
                                "arguments": {"path": "a.txt"},
                            }
                        }
                    ],
                )
            ]
        ),
        iter([_chunk(content="done")]),
    ]
    client = StreamClient(streams)
    messages = [{"role": "user", "content": "hi"}]
    run_with_tools(
        **_run_kwargs(client, messages, loaded_tools=[_echo_tool("create_new_file")])
    )
    assistant = [m for m in messages if m.get("role") == "assistant"][0]
    assert assistant["thinking"] == "plan the move"
    assert "<thought>" not in (assistant.get("content") or "")
    # Round 2 re-sends the conversation to the backend; no <thought> leaks in.
    sent = client.calls[1]["messages"]
    assert all("<thought>" not in (m.get("content") or "") for m in sent)


def test_structured_tool_calls_take_priority_over_text_calls():
    streams = [
        iter(
            [
                _chunk(
                    thinking="plan",
                    tool_calls=[{"function": {"name": "structured_tool", "arguments": {}}}],
                )
            ]
        ),
        iter([_chunk(content="done")]),
    ]
    client = StreamClient(streams)
    messages = [{"role": "user", "content": "hi"}]
    run_with_tools(
        **_run_kwargs(
            client,
            messages,
            loaded_tools=[
                _echo_tool("structured_tool"),
                _echo_tool("text_tool"),
            ],
        )
    )
    assistant = [m for m in messages if m.get("role") == "assistant"][0]
    names = [tc["function"]["name"] for tc in assistant["tool_calls"]]
    assert names == ["structured_tool"]
    assert "text_tool" not in names


def test_unparseable_directive_stays_visible():
    text = 'not a real call:foo{this is not json} but prose'
    streams = [iter([_chunk(thinking=text)]), iter([_chunk(content="ok")])]
    client = StreamClient(streams)
    messages = [{"role": "user", "content": "hi"}]
    run_with_tools(
        **_run_kwargs(client, messages, loaded_tools=[_echo_tool("foo")])
    )
    assistant = [m for m in messages if m.get("role") == "assistant"][0]
    assert "tool_calls" not in assistant
    assert "foo" in assistant.get("thinking", "")