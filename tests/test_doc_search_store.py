"""Tests for doc_search.store."""

import os
import sys
import urllib.parse

current_file = os.path.abspath(__file__)
lama_ole_dir = os.path.abspath(os.path.join(os.path.dirname(current_file), ".."))
if lama_ole_dir not in sys.path:
    sys.path.insert(0, lama_ole_dir)

from doc_search.store import (
    connect, db_path_for, _model_dir_name, upsert_file, get_file,
    upsert_chunk, get_all_chunks, get_chunk, count_files, count_chunks,
    clear_all, delete_subtree, get_meta, set_meta, check_schema_version,
)


def test_db_path_for_encoding():
    assert _model_dir_name("nomic-embed-text") == "nomic-embed-text"
    assert "%2F" in _model_dir_name("a/b")
    p = db_path_for("/tmp/db", "m")
    assert p.endswith("m/db.sqlite") or p.endswith("m\\db.sqlite")


def test_connect_and_schema(tmp_path):
    db = str(tmp_path / "db.sqlite")
    conn = connect(db)
    assert check_schema_version(conn) is True
    assert get_meta(conn, "schema_version") == "1"
    conn.close()


def test_upsert_and_get(tmp_path):
    db = str(tmp_path / "db.sqlite")
    conn = connect(db)
    upsert_file(conn, "/a.txt", 1.0, 10, 2.0)
    assert get_file(conn, "/a.txt") == (1.0, 10)
    assert count_files(conn) == 1
    upsert_chunk(conn, "cid1", "/a.txt", 1, 2, "hello", [0.1, 0.2])
    assert count_chunks(conn) == 1
    chunks = get_all_chunks(conn)
    assert chunks[0]["chunk_id"] == "cid1"
    assert chunks[0]["embedding"] == [0.1, 0.2]
    assert get_chunk(conn, "cid1")["text"] == "hello"
    conn.close()


def test_clear_and_subtree(tmp_path):
    db = str(tmp_path / "db.sqlite")
    conn = connect(db)
    upsert_file(conn, "/a/x.txt", 1.0, 10, 2.0)
    upsert_chunk(conn, "c1", "/a/x.txt", 1, 2, "t", [0.1])
    upsert_file(conn, "/b/y.txt", 1.0, 10, 2.0)
    upsert_chunk(conn, "c2", "/b/y.txt", 1, 2, "t", [0.1])
    n = delete_subtree(conn, "/a")
    assert n == 1
    assert count_files(conn) == 1
    assert count_chunks(conn) == 1
    clear_all(conn)
    assert count_files(conn) == 0
    assert count_chunks(conn) == 0
    conn.close()