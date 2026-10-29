"""Tests for doc_search.search (lisp + vector/lexical/hybrid)."""

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

from doc_search.lisp import parse, validate, LispParseError
from doc_search.search import search, index_path, cosine


def test_lisp_parse_autowrap():
    assert parse("hello world") == ["q", "hello world"]


def test_lisp_parse_ops():
    ast = parse('(and (q "vec") (r "re.*"))')
    assert ast == ["and", ["q", "vec"], ["r", "re.*"]]


def test_lisp_validate_bad():
    try:
        validate(["foo", "x"])
        assert False
    except LispParseError:
        pass


def test_cosine():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_search_missing_index(tmp_path):
    db = str(tmp_path / "db")
    os.environ["LAMA_OLE_DOCSEARCH_DB"] = db
    res = search("hello", db_root=db)
    assert res["status"] == "error"


def test_index_and_vector_search(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("# Hello\nkeep_alive config here\n", encoding="utf-8")
    db = str(tmp_path / "db")
    os.environ["LAMA_OLE_DOCSEARCH_DB"] = db
    res = index_path(str(docs), db_root=db)
    assert res["status"] == "success"
    assert res["data"]["files_indexed"] == 1
    res = search("keep_alive", db_root=db)
    assert res["status"] == "success"
    assert res["data"]["mode"] == "vector"
    assert res["data"]["total_found"] >= 1


def test_regex_search(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("line one\nkeep_alive here\n", encoding="utf-8")
    db = str(tmp_path / "db")
    os.environ["LAMA_OLE_DOCSEARCH_DB"] = db
    index_path(str(docs), db_root=db)
    res = search('(r "keep_alive")', db_root=db)
    assert res["status"] == "success"
    assert res["data"]["mode"] == "lexical"
    assert res["data"]["total_found"] == 1
    assert res["data"]["results"][0]["match_spans"]


def test_model_mismatch(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("hello\n", encoding="utf-8")
    db = str(tmp_path / "db")
    os.environ["LAMA_OLE_DOCSEARCH_DB"] = db
    os.environ["LAMA_OLE_DOCSEARCH_MODEL"] = "echo-mock"
    index_path(str(docs), db_root=db)
    os.environ["LAMA_OLE_DOCSEARCH_MODEL"] = "other-model"
    res = search('(q "hello")', db_root=db)
    # vector mode should error on mismatch
    assert res["status"] == "error"