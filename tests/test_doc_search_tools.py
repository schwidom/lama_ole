"""Tests for tools.doc_search_tools."""

import os
import sys
import tempfile

current_file = os.path.abspath(__file__)
lama_ole_dir = os.path.abspath(os.path.join(os.path.dirname(current_file), ".."))
if lama_ole_dir not in sys.path:
    sys.path.insert(0, lama_ole_dir)

from tools_security.validate_path import register_basepath
register_basepath("/tmp")

os.environ["LAMA_OLE_DOCSEARCH_BACKEND"] = "echo"
os.environ["LAMA_OLE_DOCSEARCH_MODEL"] = "echo-mock"

from tools.doc_search_tools import (
    doc_index, doc_search, doc_search_next_results, doc_search_status,
    doc_get_chunk, doc_index_status, doc_index_clear,
)


def test_module_contract():
    import tools.doc_search_tools as m
    assert m.__tool_readonly__ is True
    assert "LAMA_OLE_DOCSEARCH_DB" in m.__tool_env__


def test_doc_index_and_status(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("hello keep_alive\n", encoding="utf-8")
    db = str(tmp_path / "db")
    os.environ["LAMA_OLE_DOCSEARCH_DB"] = db
    res = doc_index(str(docs))
    assert res["status"] == "success"
    assert res["data"]["files_indexed"] == 1
    st = doc_index_status()
    assert st["status"] == "success"
    assert st["data"]["file_count"] == 1


def test_doc_search_empty_query():
    res = doc_search("")
    assert res["status"] == "error"


def test_doc_search_and_pagination(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("hello keep_alive\n", encoding="utf-8")
    (docs / "b.md").write_text("another keep_alive line\n", encoding="utf-8")
    db = str(tmp_path / "db")
    os.environ["LAMA_OLE_DOCSEARCH_DB"] = db
    doc_index(str(docs))
    res = doc_search("keep_alive", top_k=1)
    assert res["status"] == "success"
    assert res["data"]["returned"] == 1
    assert res["data"]["has_more"] is True
    sid = res["data"]["search_id"]
    nxt = doc_search_next_results(maxcount=5, search_id=sid)
    assert nxt["status"] == "success"
    assert nxt["data"]["returned"] >= 1
    st = doc_search_status()
    assert st["data"]["search_id"] == sid


def test_doc_get_chunk(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("hello keep_alive\n", encoding="utf-8")
    db = str(tmp_path / "db")
    os.environ["LAMA_OLE_DOCSEARCH_DB"] = db
    doc_index(str(docs))
    res = doc_search("keep_alive")
    cid = res["data"]["results"][0]["chunk_id"]
    gc = doc_get_chunk(cid)
    assert gc["status"] == "success"
    assert "text" in gc["data"]


def test_doc_index_clear(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("hello\n", encoding="utf-8")
    db = str(tmp_path / "db")
    os.environ["LAMA_OLE_DOCSEARCH_DB"] = db
    doc_index(str(docs))
    res = doc_index_clear()
    assert res["status"] == "success"
    st = doc_index_status()
    assert st["data"]["exists"] is False


def test_path_validation():
    res = doc_index("/etc/passwd")
    assert res["status"] == "error"