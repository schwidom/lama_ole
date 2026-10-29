"""Tests for doc_search.chunker."""

import os
import sys

current_file = os.path.abspath(__file__)
lama_ole_dir = os.path.abspath(os.path.join(os.path.dirname(current_file), ".."))
if lama_ole_dir not in sys.path:
    sys.path.insert(0, lama_ole_dir)

from doc_search.chunker import chunk_text, is_binary, read_text_file


def test_chunk_text_basic():
    text = "line1\nline2\nline3\nline4\nline5"
    chunks = chunk_text(text, chunk_lines=2, overlap=0, max_chars=2000)
    assert len(chunks) == 3
    assert chunks[0]["line_start"] == 1
    assert chunks[0]["line_end"] == 2
    assert chunks[0]["text"] == "line1\nline2"
    assert chunks[1]["line_start"] == 3
    assert chunks[1]["line_end"] == 4


def test_chunk_text_overlap():
    text = "\n".join(f"l{i}" for i in range(1, 11))
    chunks = chunk_text(text, chunk_lines=4, overlap=2, max_chars=2000)
    # step = 2
    assert chunks[0]["line_start"] == 1
    assert chunks[0]["line_end"] == 4
    assert chunks[1]["line_start"] == 3
    assert chunks[1]["line_end"] == 6


def test_chunk_text_max_chars():
    text = "a" * 100 + "\n" + "b" * 100
    chunks = chunk_text(text, chunk_lines=10, overlap=0, max_chars=50)
    assert all(len(c["text"]) <= 50 for c in chunks)


def test_chunk_text_empty():
    # empty string: split produces one empty line -> one chunk
    assert chunk_text("", chunk_lines=5, overlap=1, max_chars=100) == [{"line_start": 1, "line_end": 1, "text": ""}]
    assert chunk_text("\n", chunk_lines=5, overlap=1, max_chars=100) == [{"line_start": 1, "line_end": 2, "text": "\n"}]


def test_is_binary():
    assert is_binary(b"hello\x00world") is True
    assert is_binary(b"hello world") is False


def test_read_text_file_binary(tmp_path):
    p = tmp_path / "bin.bin"
    p.write_bytes(b"hello\x00world")
    assert read_text_file(str(p)) is None


def test_read_text_file_text(tmp_path):
    p = tmp_path / "t.txt"
    p.write_text("hello world\n", encoding="utf-8")
    assert read_text_file(str(p)) == "hello world\n"