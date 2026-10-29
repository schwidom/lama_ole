"""Doc search tools for lama_ole — semantic + lexical documentation search.

Load as a toolset: ``--tool tools.doc_search_tools`` or ``/tools load doc_search_tools``.
"""

__tool_readonly__ = True

import os
from typing import Any, Dict, List, Optional, Union

def _env_str(name, default):
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v

from tool_base import tool
from tools_security.validate_path import validate_path as _validate_path

from parameters import ParameterSpec

__tool_env__ = {
    "LAMA_OLE_DOCSEARCH_DB": "DB root directory (default: ./docsearch)",
    "LAMA_OLE_DOCSEARCH_BACKEND": "Embedding backend: ollama | openai_compat | ... (default: ollama)",
    "LAMA_OLE_DOCSEARCH_HOST": "Host endpoint of the embedding backend",
    "LAMA_OLE_DOCSEARCH_MODEL": "Embedding model name (default: nomic-embed-text)",
    "LAMA_OLE_DOCSEARCH_API_KEY": "API key for remote embedding backends (no fallback)",
    "LAMA_OLE_DOCSEARCH_CHUNK_LINES": "Lines per chunk (default: 40)",
    "LAMA_OLE_DOCSEARCH_CHUNK_OVERLAP": "Overlapping lines between chunks (default: 8)",
    "LAMA_OLE_DOCSEARCH_MAX_CHUNK_CHARS": "Hard cap on chunk text length (default: 2000)",
    "LAMA_OLE_DOCSEARCH_TOP_K": "Default number of chunks returned (default: 8)",
    "LAMA_OLE_DOCSEARCH_MAX_RESULTS": "Hard cap on results per call (default: 20)",
    "LAMA_OLE_DOCSEARCH_MIN_SCORE": "Minimum cosine similarity (soft, default: 0.25)",
    "LAMA_OLE_DOCSEARCH_SNIPPET_CHARS": "Max chars of chunk text returned (default: 600)",
    "LAMA_OLE_DOCSEARCH_INCLUDE": "Glob of files to index (default: *)",
    "LAMA_OLE_DOCSEARCH_EXCLUDE": "Glob of files/dirs to skip (default: empty)",
    "LAMA_OLE_DOCSEARCH_MAX_FILE_BYTES": "Skip files larger than this (default: 2000000)",
    "LAMA_OLE_DOCSEARCH_EMBED_BATCH": "Embedding batch size (default: 32)",
    "LAMA_OLE_DOCSEARCH_EMBED_TIMEOUT": "Embedding request timeout seconds (default: 60)",
}

__tool_params__ = [
    ParameterSpec(name="docsearch", flags=["--docsearch"], default=None,
                  help="Run a one-shot doc search query and exit"),
    ParameterSpec(name="docscan", flags=["--docscan"], default=None,
                  help="Index docs at PATH and exit"),
    ParameterSpec(name="docdb", flags=["--docdb"], default=None,
                  help="Override the doc-search DB root directory"),
]


# Cached search state
_cached_query = ""
_cached_results = []
_cached_cursor = 0
_cached_search_id = None


def _env_int(name, default):
    v = os.environ.get(name)
    if v is None:
        return default
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


@tool(description="Index documents under a path for doc search. Returns counts.")
def doc_index(path: str, include: str = None, exclude: str = "", recursive: bool = True, force: bool = False) -> Dict[str, Any]:
    global _cached_query, _cached_results, _cached_cursor, _cached_search_id
    safety_error = _validate_path(path)
    if safety_error:
        return {"status": "error", "message": [safety_error]}
    if include is None:
        include = None  # let index_path resolve default + env
    from doc_search.search import index_path
    res = index_path(path, include=include, exclude=exclude, recursive=recursive, force=force)
    if res.get("status") == "success":
        # invalidate cached search results
        _cached_query = ""
        _cached_results = []
        _cached_cursor = 0
        _cached_search_id = None
    return res


@tool(description="Search indexed documentation using a lisp query or plain string. Returns located chunks.")
def doc_search(query: str, top_k: int = None, max_chars: int = 400) -> Dict[str, Any]:
    global _cached_query, _cached_results, _cached_cursor, _cached_search_id
    if not query or not str(query).strip():
        return {"status": "error", "message": ["query is required; pass a lisp expression or plain string"]}
    import uuid
    from doc_search.search import search as _search
    snippet_chars = _env_int("LAMA_OLE_DOCSEARCH_SNIPPET_CHARS", 600)
    max_results = _env_int("LAMA_OLE_DOCSEARCH_MAX_RESULTS", 20)
    if top_k is None:
        top_k = _env_int("LAMA_OLE_DOCSEARCH_TOP_K", 8)
    top_k = max(1, min(top_k, max_results))
    # clamp max_chars
    max_chunk_chars = _env_int("LAMA_OLE_DOCSEARCH_MAX_CHUNK_CHARS", 2000)
    max_chars = max(100, min(max_chars, max_chunk_chars))
    # Fetch all results for caching; return only top_k
    result = _search(query, top_k=max_results, max_chars=max_chars, snippet_chars=snippet_chars)
    if result.get("status") == "success":
        data = result["data"]
        all_results = data.get("results", [])
        _cached_query = query
        _cached_results = all_results
        _cached_search_id = uuid.uuid4().hex[:12]
        page = all_results[:top_k]
        data["results"] = page
        data["returned"] = len(page)
        data["search_id"] = _cached_search_id
        data["has_more"] = len(all_results) > top_k
        data["current_range"] = f"0 to {len(page)-1}" if page else "0 to 0"
        _cached_cursor = len(page)
    return result


@tool(description="Get the next page of results from the previous doc_search call.")
def doc_search_next_results(maxcount: int = 10, search_id: Optional[str] = None) -> Dict[str, Any]:
    global _cached_cursor
    if not _cached_results and _cached_query == "":
        return {"status": "error", "message": ["no active search. Please run doc_search first."]}
    if search_id is not None and search_id != _cached_search_id:
        return {"status": "error", "message": ["search_id mismatch; run doc_search again"]}
    maxcount = max(1, min(maxcount, 10))
    remaining = _cached_results[_cached_cursor:]
    if not remaining:
        return {"status": "error", "message": ["no more data"]}
    page = remaining[:maxcount]
    _cached_cursor += len(page)
    return {"status": "success", "data": {
        "search_id": _cached_search_id,
        "results": page,
        "returned": len(page),
        "has_more": _cached_cursor < len(_cached_results),
    }}


@tool(description="Get the full text of a chunk by its chunk_id.")
def doc_get_chunk(chunk_id: str) -> Dict[str, Any]:
    from doc_search.search import get_chunk_text
    return get_chunk_text(chunk_id)


@tool(description="Show state of the last doc_search (query, total, cursor, search_id).")
def doc_search_status() -> Dict[str, Any]:
    global _cached_query, _cached_results, _cached_cursor, _cached_search_id
    return {"status": "success", "data": {
        "query": _cached_query,
        "total": len(_cached_results),
        "cursor": _cached_cursor,
        "search_id": _cached_search_id,
        "has_more": _cached_cursor < len(_cached_results),
    }}


@tool(description="Show index status (file/chunk counts, model, staleness).")
def doc_index_status() -> Dict[str, Any]:
    from doc_search.search import index_status
    return index_status()


@tool(description="Clear the index (whole DB if path is None, else a subtree).")
def doc_index_clear(path: Optional[str] = None) -> Dict[str, Any]:
    if path is not None:
        safety_error = _validate_path(path)
        if safety_error:
            return {"status": "error", "message": [safety_error]}
    from doc_search.search import clear_index
    return clear_index(path=path)