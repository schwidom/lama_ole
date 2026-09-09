"""Tests for the Eliza backend's built-in named scripts.

Covers model-name -> script resolution (``--backend eliza -m <script>``),
the ``read_test`` tool-calling dialogue, the 10-sentence ``chitchat``
dialogue, exhaustion after the script ends, and that an explicit ``script=``
always wins over a model name.
"""

from __future__ import annotations

import os
import sys

current_file = os.path.abspath(__file__)
lama_ole_dir = os.path.abspath(os.path.join(os.path.dirname(current_file), ".."))
if lama_ole_dir not in sys.path:
    sys.path.insert(0, lama_ole_dir)

from backends.base import ChatChunk
from backends.eliza_scripts import ELIZA_SCRIPTS
from backends.factory import create_backend
from tool_base.engine import run_with_tools
from tool_base.registry import load_tools


def _content_of(chunks):
    return "".join(c.content or "" for c in chunks if isinstance(c, ChatChunk))


def test_named_scripts_listed_as_models():
    models = [m.name for m in create_backend("eliza").list_models()]
    assert models == ["eliza-mock", "read_test", "chitchat"]


def test_resolve_script_by_model_name():
    backend = create_backend("eliza")
    chunks = list(backend.chat(model="chitchat", messages=[{"role": "user", "content": "hi"}]))
    assert _content_of(chunks) == ELIZA_SCRIPTS["chitchat"][0]["content"]


def test_explicit_script_wins_over_model_name():
    backend = create_backend("eliza", script=[{"content": "explicit script"}])
    chunks = list(backend.chat(model="read_test", messages=[{"role": "user", "content": "hi"}]))
    assert _content_of(chunks) == "explicit script"


def test_unknown_model_name_is_exhausted_not_crash():
    backend = create_backend("eliza")
    chunks = list(backend.chat(model="does-not-exist", messages=[{"role": "user", "content": "hi"}]))
    assert _content_of(chunks) == "[Eliza: script exhausted]"


def test_read_test_dialogue(tmp_path, monkeypatch, capsys):
    """The read_test script calls read_file(path=test.txt) and then answers."""
    monkeypatch.chdir(tmp_path)
    tmp_path.joinpath("test.txt").write_text(
        "THE UNIQUE CONTENT 987654321\n", encoding="utf-8"
    )

    backend = create_backend("eliza")  # no explicit script -> resolved via model
    tools = load_tools("tools.example_tools")

    run_with_tools(
        client=backend,
        model="read_test",
        messages=[{"role": "user", "content": "Please read test.txt."}],
        loaded_tools=tools,
        backend_tools=backend.convert_tools(tools),
        options={},
        keep_alive=None,
        show_thinking=False,
        no_safety_system_prompt=True,
        verbose=1,
    )

    out = capsys.readouterr()
    # Sentence 1 streamed before the tool round, sentence 2 after the result.
    assert "Let me read the file test.txt for you." in out.out
    assert "I read test.txt; its contents were shown in the tool result." in out.out
    # The tool really ran against ./test.txt and surfaced its content.
    assert "[tool: read_file(path='test.txt')]" in out.err
    assert "THE UNIQUE CONTENT 987654321" in out.err


def test_chitchat_dialogue_ten_sentences():
    """The chitchat script plays exactly its 10 sentences, one per chat() call."""
    backend = create_backend("eliza")
    expected = ELIZA_SCRIPTS["chitchat"]
    assert len(expected) == 10

    for i, sentence in enumerate(expected):
        chunks = list(
            backend.chat(
                model="chitchat",
                messages=[{"role": "user", "content": "turn %d" % i}],
            )
        )
        assert _content_of(chunks) == sentence["content"], "sentence %d" % i

    # 11th call: script is exhausted.
    chunks = list(backend.chat(model="chitchat", messages=[{"role": "user", "content": "again"}]))
    assert _content_of(chunks) == "[Eliza: script exhausted]"