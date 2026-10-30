"""Search engine for doc_search: vector, lexical, hybrid."""

from __future__ import annotations

import math
import os
import re
import time
from typing import Any, Dict, List, Optional

from doc_search.chunker import chunk_text
from doc_search.lisp import parse as lisp_parse, validate as lisp_validate, LispParseError
from doc_search.store import (
    connect, db_path_for, get_all_chunks, get_chunk, get_meta, set_meta,
    get_newest_mtime, check_schema_version, get_file, delete_file_chunks,
    count_files, count_chunks, clear_all, delete_subtree, upsert_file, upsert_chunk,
)


def cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _env_int(name: str, default: int) -> int:
    import os
    v = os.environ.get(name)
    if v is None:
        return default
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


def _env_float(name: str, default: float) -> float:
    import os
    v = os.environ.get(name)
    if v is None:
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def _env_str(name: str, default: str) -> str:
    import os
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v


def get_db_root() -> str:
    return _env_str("LAMA_OLE_DOCSEARCH_DB", "./docsearch")


def get_backend_config() -> tuple:
    backend = _env_str("LAMA_OLE_DOCSEARCH_BACKEND", "ollama")
    host = os.environ.get("LAMA_OLE_DOCSEARCH_HOST") or None
    model = _env_str("LAMA_OLE_DOCSEARCH_MODEL", "nomic-embed-text")
    api_key = os.environ.get("LAMA_OLE_DOCSEARCH_API_KEY") or None
    return backend, host, model, api_key


def _create_backend():
    from backends.factory import create_backend
    backend, host, model, api_key = get_backend_config()
    return create_backend(backend, host=host, api_key=api_key), backend, model


def _regex_flags(op: str):
    # op: r, ri, rf, rfi
    ignore_case = "i" in op
    fixed = "f" in op
    flags = re.IGNORECASE if ignore_case else 0
    return flags, fixed


def _match_regex(pattern: str, text: str, op: str) -> bool:
    flags, fixed = _regex_flags(op)
    if fixed:
        pattern = re.escape(pattern)
    try:
        return re.search(pattern, text, flags) is not None
    except re.error:
        return False


def _match_keyword(kw: str, text: str, case_sensitive: bool = False) -> bool:
    if case_sensitive:
        return kw in text
    return kw.lower() in text.lower()


def _eval_ast(ast, chunk_text: str, chunk_embedding, query_embedding, scores_acc: dict) -> bool:
    """Evaluate a lisp AST against a chunk. Returns bool. Accumulates q scores."""
    if isinstance(ast, str):
        # bare string treated as keyword? In valid AST this shouldn't happen at top
        return ast.lower() in chunk_text.lower()
    if not isinstance(ast, list) or not ast:
        return False
    head = ast[0]
    args = ast[1:]
    if head == "q":
        # vector: always "matches" (candidate), score computed separately
        return True
    if head == "r":
        return _match_regex(args[0], chunk_text, "r")
    if head == "ri":
        return _match_regex(args[0], chunk_text, "ri")
    if head == "rf":
        return _match_regex(args[0], chunk_text, "rf")
    if head == "rfi":
        return _match_regex(args[0], chunk_text, "rfi")
    if head == "k":
        # OR of keywords (case-insensitive)
        return any(_match_keyword(kw, chunk_text, False) for kw in args)
    if head == "kc":
        return any(_match_keyword(kw, chunk_text, True) for kw in args)
    if head == "and":
        if not args:
            return True
        result = True
        for a in args:
            if not _eval_ast(a, chunk_text, chunk_embedding, query_embedding, scores_acc):
                result = False
                break
        return result
    if head == "or":
        if not args:
            return False
        for a in args:
            if _eval_ast(a, chunk_text, chunk_embedding, query_embedding, scores_acc):
                return True
        return False
    if head == "not":
        return not _eval_ast(args[0], chunk_text, chunk_embedding, query_embedding, scores_acc)
    return False


def _collect_q_strings(ast) -> List[str]:
    """Collect all q-strings from an AST."""
    if isinstance(ast, str):
        return []
    if not isinstance(ast, list) or not ast:
        return []
    head = ast[0]
    args = ast[1:]
    if head == "q":
        return [args[0]]
    result = []
    for a in args:
        result.extend(_collect_q_strings(a))
    return result


def _has_lexical(ast) -> bool:
    if isinstance(ast, str):
        return False
    if not isinstance(ast, list) or not ast:
        return False
    head = ast[0]
    if head in ("r", "ri", "rf", "rfi", "k", "kc"):
        return True
    if head in ("and", "or", "not"):
        return any(_has_lexical(a) for a in ast[1:])
    return False


def _has_vector(ast) -> bool:
    if isinstance(ast, str):
        return False
    if not isinstance(ast, list) or not ast:
        return False
    head = ast[0]
    if head == "q":
        return True
    if head in ("and", "or", "not"):
        return any(_has_vector(a) for a in ast[1:])
    return False


def search(
    query: str,
    db_root: Optional[str] = None,
    backend=None,
    model: Optional[str] = None,
    top_k: int = 8,
    max_chars: int = 400,
    snippet_chars: int = 600,
) -> dict:
    """Search the index. Returns standard result dict."""
    if db_root is None:
        db_root = get_db_root()
    if backend is None or model is None:
        b, _, m = _create_backend()
        if backend is None:
            backend = b
        if model is None:
            model = m

    # Parse lisp
    try:
        ast = lisp_parse(query)
        lisp_validate(ast)
    except (LispParseError, Exception) as e:
        return {"status": "error", "message": [f"query parse error: {e}"]}

    # Determine db path
    db_path = db_path_for(db_root, model)
    if not os.path.exists(db_path):
        return {"status": "error", "message": [f"no index found at {db_path}; run doc_index first"]}

    conn = connect(db_path)
    try:
        if not check_schema_version(conn):
            return {"status": "error", "message": ["incompatible index schema; run doc_index(force=True)"]}
        # model mismatch check
        stored_model = get_meta(conn, "model")
        if stored_model is not None and stored_model != model:
            # lexical still works; vector mode errors
            if _has_vector(ast):
                return {"status": "error", "message": [
                    f"model mismatch: index built with '{stored_model}', configured '{model}'. "
                    "Run doc_index(force=True) to rebuild, or use lexical-only query."
                ]}

        chunks = get_all_chunks(conn)
        if not chunks:
            return {"status": "success", "data": {
                "mode": _mode_str(ast),
                "query": query,
                "total_found": 0,
                "results": [],
            }}

        # Resolve effective snippet length: max_chars overrides snippet_chars when given.
        if max_chars is None:
            _eff_snippet = snippet_chars
        else:
            _mc = _env_int("LAMA_OLE_DOCSEARCH_MAX_CHUNK_CHARS", 2000)
            max_chars = max(100, min(max_chars, _mc))
            _eff_snippet = max_chars

        # Embed query if vector present
        q_strings = _collect_q_strings(ast)
        query_embeddings = []
        if q_strings:
            try:
                query_embeddings = backend.embed(q_strings, model)
            except Exception as e:
                return {"status": "error", "message": [f"embedding failed: {e}"]}

        # Compute per-chunk cosine score (average over q strings)
        # Precompute chunk embeddings
        chunk_embs = {}
        for c in chunks:
            chunk_embs[c["chunk_id"]] = c.get("embedding")

        # Evaluate each chunk
        has_lex = _has_lexical(ast)
        has_vec = _has_vector(ast)

        candidates = []
        for c in chunks:
            ctext = c["text"]
            cemb = chunk_embs.get(c["chunk_id"])
            # compute score
            score = 0.0
            if has_vec and query_embeddings and cemb:
                scores = []
                for qe in query_embeddings:
                    scores.append(cosine(qe, cemb))
                score = sum(scores) / len(scores) if scores else 0.0

            # lexical filter
            if has_lex:
                matched = _eval_ast(ast, ctext, cemb, query_embeddings, {})
                # _eval_ast returns bool for lexical; but q nodes return True
                # Need: if has_lex, the overall expression must be True considering
                # q as True (candidate). Re-evaluate treating q as True.
                # Already done above (q returns True).
                if not matched:
                    continue
            else:
                # pure vector: all chunks are candidates
                pass

            # min_score soft annotation
            min_score = _env_float("LAMA_OLE_DOCSEARCH_MIN_SCORE", 0.25)
            below = has_vec and score < min_score

            # snippet truncation
            text = c["text"]
            truncated = False
            if len(text) > _eff_snippet:
                text = text[:_eff_snippet] + "..."
                truncated = True

            # match_spans for lexical hits
            match_spans = []
            if has_lex:
                for m in re.finditer(re.escape(""), c["text"]):
                    pass
                # compute spans for r/k operators present
                spans = _compute_match_spans(ast, c["text"])
                match_spans = spans

            candidates.append({
                "chunk_id": c["chunk_id"],
                "path": c["path"],
                "line_start": c["line_start"],
                "line_end": c["line_end"],
                "score": round(score, 4) if has_vec else None,
                "below_threshold": below if has_vec else False,
                "matched_by": _matched_by(ast),
                "match_spans": match_spans,
                "text": text,
                "full_length": len(c["text"]),
                "truncated": truncated,
            })

        # Sort
        if has_vec:
            candidates.sort(key=lambda x: (x["score"] is None, -(x["score"] or 0)))
        else:
            candidates.sort(key=lambda x: (x["path"], x["line_start"]))

        # Dedup by (path, line_start) containment
        deduped = []
        seen_ranges = []
        for c in candidates:
            contained = False
            for (p, ls, le) in seen_ranges:
                if c["path"] == p and c["line_start"] >= ls and c["line_end"] <= le:
                    contained = True
                    break
            if not contained:
                deduped.append(c)
                seen_ranges.append((c["path"], c["line_start"], c["line_end"]))

        total = len(deduped)
        # pagination handled by caller/caching; here return all (capped)
        max_results = _env_int("LAMA_OLE_DOCSEARCH_MAX_RESULTS", 20)
        top_k = max(1, min(top_k, max_results))
        page = deduped[:top_k]

        # stale check
        index_stale = False
        try:
            stored_files = [r[0] for r in conn.execute("SELECT path FROM files").fetchall()]
            for fp in stored_files:
                try:
                    if os.path.exists(fp) and os.path.getmtime(fp) > (get_newest_mtime(conn) or 0):
                        index_stale = True
                        break
                except OSError:
                    pass
        except Exception:
            pass

        result_data = {
            "mode": _mode_str(ast),
            "query": query,
            "total_found": total,
            "returned": len(page),
            "index_stale": index_stale,
            "results": page,
        }
        return {"status": "success", "data": result_data}
    finally:
        conn.close()


def _mode_str(ast) -> str:
    hv = _has_vector(ast)
    hl = _has_lexical(ast)
    if hv and hl:
        return "hybrid"
    if hv:
        return "vector"
    return "lexical"


def _compute_match_spans(ast, text: str) -> List[dict]:
    """Compute match spans (char offsets) for lexical operators in ast."""
    spans = []
    if isinstance(ast, str):
        return spans
    if not isinstance(ast, list) or not ast:
        return spans
    head = ast[0]
    args = ast[1:]
    if head in ("r", "ri", "rf", "rfi"):
        flags, fixed = _regex_flags(head)
        pat = args[0]
        if fixed:
            pat = re.escape(pat)
        try:
            for m in re.finditer(pat, text, flags):
                spans.append({"start": m.start(), "end": m.end()})
        except re.error:
            pass
    elif head in ("k", "kc"):
        case_sensitive = (head == "kc")
        for kw in args:
            if case_sensitive:
                idx = 0
                while True:
                    i = text.find(kw, idx)
                    if i == -1:
                        break
                    spans.append({"start": i, "end": i + len(kw)})
                    idx = i + 1
            else:
                low = text.lower()
                kwl = kw.lower()
                idx = 0
                while True:
                    i = low.find(kwl, idx)
                    if i == -1:
                        break
                    spans.append({"start": i, "end": i + len(kw)})
                    idx = i + 1
    elif head in ("and", "or", "not"):
        for a in args:
            spans.extend(_compute_match_spans(a, text))
    # dedup overlapping identical spans
    out = []
    seen = set()
    for s in spans:
        key = (s["start"], s["end"])
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _matched_by(ast) -> List[str]:
    res = []
    if _has_vector(ast):
        res.append("vector")
    if _has_lexical(ast):
        res.append("lexical")
    return res


def index_path(
    path: str,
    db_root: Optional[str] = None,
    backend=None,
    model: Optional[str] = None,
    include: str = "*",
    exclude: str = "",
    recursive: bool = True,
    force: bool = False,
    chunk_lines: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
    max_chunk_chars: Optional[int] = None,
    max_file_bytes: Optional[int] = None,
) -> dict:
    """Index documents under *path*. Returns standard result dict."""
    import fnmatch
    import time as _time

    if db_root is None:
        db_root = get_db_root()
    if backend is None or model is None:
        b, _, m = _create_backend()
        if backend is None:
            backend = b
        if model is None:
            model = m

    if chunk_lines is None:
        chunk_lines = _env_int("LAMA_OLE_DOCSEARCH_CHUNK_LINES", 40)
    if chunk_overlap is None:
        chunk_overlap = _env_int("LAMA_OLE_DOCSEARCH_CHUNK_OVERLAP", 8)
    if max_chunk_chars is None:
        max_chunk_chars = _env_int("LAMA_OLE_DOCSEARCH_MAX_CHUNK_CHARS", 2000)
    if max_file_bytes is None:
        max_file_bytes = _env_int("LAMA_OLE_DOCSEARCH_MAX_FILE_BYTES", 2000000)

    if include is None:
        include = _env_str("LAMA_OLE_DOCSEARCH_INCLUDE", "*.md *.txt *.rst *.py *.json *.yaml *.yml *.toml *.cfg *.ini *.html")
    env_include = os.environ.get("LAMA_OLE_DOCSEARCH_INCLUDE")
    if env_include:
        include = env_include
    include_pats = include.split() if isinstance(include, str) else [include]
    exclude_pat = _env_str("LAMA_OLE_DOCSEARCH_EXCLUDE", exclude or "")
    if exclude:
        exclude_pat = exclude

    # validate path
    from tools_security.validate_path import validate_path
    err = validate_path(path)
    if err:
        return {"status": "error", "message": [err]}

    if not os.path.exists(path):
        return {"status": "error", "message": [f"path not found: {path}"]}

    db_path = db_path_for(db_root, model)
    conn = connect(db_path)

    # schema version check
    if not check_schema_version(conn):
        conn.close()
        return {"status": "error", "message": ["incompatible schema; delete index manually"]}

    # model mismatch check
    stored_model = get_meta(conn, "model")
    stored_cl = get_meta(conn, "chunk_lines")
    stored_co = get_meta(conn, "chunk_overlap")
    stored_mc = get_meta(conn, "max_chunk_chars")
    mismatch = False
    if stored_model is not None and stored_model != model:
        mismatch = True
    if stored_cl is not None and int(stored_cl) != chunk_lines:
        mismatch = True
    if stored_co is not None and int(stored_co) != chunk_overlap:
        mismatch = True
    if stored_mc is not None and int(stored_mc) != max_chunk_chars:
        mismatch = True
    if mismatch and not force:
        conn.close()
        return {"status": "error", "message": [
            "index parameters/model changed; run with force=True to rebuild"
        ]}
    if force:
        clear_all(conn) if False else None
        # clear chunks/files but keep schema
        conn.execute("DELETE FROM chunks")
        conn.execute("DELETE FROM files")
        conn.commit()

    # collect files
    files_to_index = []
    avoid_dirs = {".git", "__pycache__", "node_modules", ".docsearch"}
    if os.path.isfile(path):
        files_to_index.append(path)
    else:
        for root, dirs, files in os.walk(path):
            if not recursive and root != path:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in avoid_dirs]
            # apply exclude
            if exclude_pat:
                dirs[:] = [d for d in dirs if not fnmatch.fnmatch(d, exclude_pat)]
            for fname in files:
                if not any(fnmatch.fnmatch(fname, ip) for ip in include_pats):
                    continue
                if exclude_pat and fnmatch.fnmatch(fname, exclude_pat):
                    continue
                fpath = os.path.join(root, fname)
                files_to_index.append(fpath)
            if not recursive:
                dirs[:] = []

    indexed_files = 0

    indexed_files = 0
    indexed_chunks = 0
    skipped = 0
    errors = []

    batch_size = _env_int("LAMA_OLE_DOCSEARCH_EMBED_BATCH", 32)
    timeout = _env_int("LAMA_OLE_DOCSEARCH_EMBED_TIMEOUT", 60)

    for fpath in files_to_index:
        try:
            st = os.stat(fpath)
        except OSError:
            skipped += 1
            continue
        if st.st_size > max_file_bytes:
            skipped += 1
            continue
        # check if unchanged
        existing = get_file(conn, fpath)
        if existing is not None and not force:
            if existing[0] == st.st_mtime and existing[1] == st.st_size:
                continue  # unchanged
        # read text via chunker (single source of truth)
        text = None
        try:
            from doc_search.chunker import read_text_file
            text = read_text_file(fpath)
        except Exception:
            text = None
        if text is None:
            skipped += 1
            continue

        # delete old chunks for this file
        delete_file_chunks(conn, fpath)

        # chunk
        chunks = chunk_text(text, chunk_lines, chunk_overlap, max_chunk_chars)
        if not chunks:
            skipped += 1
            continue

        # embed in batches
        texts_to_embed = [c["text"] for c in chunks]
        embeddings = []
        for i in range(0, len(texts_to_embed), batch_size):
            batch = texts_to_embed[i:i + batch_size]
            try:
                embs = backend.embed(batch, model)
                embeddings.extend(embs)
            except Exception as e:
                errors.append(f"{fpath}: {e}")
                embeddings = None
                break
        if embeddings is None:
            skipped += 1
            continue

        # upsert
        import time as _t
        now = _t.time()
        upsert_file(conn, fpath, st.st_mtime, st.st_size, now)
        for c, emb in zip(chunks, embeddings):
            cid = f"{fpath}\x1f{c['line_start']}\x1f{c['line_end']}"
            upsert_chunk(conn, cid, fpath, c["line_start"], c["line_end"], c["text"], emb)
        conn.commit()
        indexed_files += 1
        indexed_chunks += len(chunks)

    # set meta
    set_meta(conn, "model", model)
    set_meta(conn, "chunk_lines", str(chunk_lines))
    set_meta(conn, "chunk_overlap", str(chunk_overlap))
    set_meta(conn, "max_chunk_chars", str(max_chunk_chars))
    set_meta(conn, "last_indexed_at", str(_time.time()))
    conn.commit()
    conn.close()

    return {"status": "success", "data": {
        "path": path,
        "files_indexed": indexed_files,
        "chunks_indexed": indexed_chunks,
        "files_skipped": skipped,
        "errors": errors[:10],
        "db_path": db_path,
    }}


def get_chunk_text(chunk_id: str, db_root: Optional[str] = None, model: Optional[str] = None) -> dict:
    if db_root is None:
        db_root = get_db_root()
    if model is None:
        _, _, model, _ = get_backend_config()
    db_path = db_path_for(db_root, model)
    if not os.path.exists(db_path):
        return {"status": "error", "message": [f"no index found at {db_path}"]}
    conn = connect(db_path)
    try:
        c = get_chunk(conn, chunk_id)
        if c is None:
            return {"status": "error", "message": [f"chunk not found: {chunk_id}"]}
        return {"status": "success", "data": {
            "chunk_id": c["chunk_id"],
            "path": c["path"],
            "line_start": c["line_start"],
            "line_end": c["line_end"],
            "text": c["text"],
            "full_length": len(c["text"]),
        }}
    finally:
        conn.close()


def index_status(db_root: Optional[str] = None, model: Optional[str] = None) -> dict:
    if db_root is None:
        db_root = get_db_root()
    if model is None:
        _, _, model, _ = get_backend_config()
    db_path = db_path_for(db_root, model)
    if not os.path.exists(db_path):
        return {"status": "success", "data": {
            "exists": False,
            "db_path": db_path,
        }}
    conn = connect(db_path)
    try:
        if not check_schema_version(conn):
            return {"status": "error", "message": ["incompatible schema"]}
        stored_model = get_meta(conn, "model")
        newest_mtime = get_newest_mtime(conn)
        # stale check
        index_stale = False
        stored_files = [r[0] for r in conn.execute("SELECT path FROM files").fetchall()]
        for fp in stored_files:
            try:
                if os.path.exists(fp) and os.path.getmtime(fp) > (newest_mtime or 0):
                    index_stale = True
                    break
            except OSError:
                pass
        return {"status": "success", "data": {
            "exists": True,
            "db_path": db_path,
            "model": stored_model,
            "configured_model": model,
            "model_match": stored_model == model,
            "file_count": count_files(conn),
            "chunk_count": count_chunks(conn),
            "chunk_lines": get_meta(conn, "chunk_lines"),
            "chunk_overlap": get_meta(conn, "chunk_overlap"),
            "max_chunk_chars": get_meta(conn, "max_chunk_chars"),
            "last_indexed_at": get_meta(conn, "last_indexed_at"),
            "index_stale": index_stale,
        }}
    finally:
        conn.close()


def clear_index(path: Optional[str] = None, db_root: Optional[str] = None, model: Optional[str] = None) -> dict:
    if db_root is None:
        db_root = get_db_root()
    if model is None:
        _, _, model, _ = get_backend_config()
    db_path = db_path_for(db_root, model)
    if not os.path.exists(db_path):
        return {"status": "success", "data": {"deleted": False, "reason": "no index exists"}}
    if path is None:
        # delete whole db
        try:
            os.remove(db_path)
            # remove wal/shm
            for suffix in ("-wal", "-shm"):
                p = db_path + suffix
                if os.path.exists(p):
                    os.remove(p)
            return {"status": "success", "data": {"deleted": True, "db_path": db_path}}
        except Exception as e:
            return {"status": "error", "message": [str(e)]}
    else:
        conn = connect(db_path)
        try:
            from doc_search.store import delete_subtree
            n = delete_subtree(conn, path)
            return {"status": "success", "data": {"deleted_subtree": path, "files_removed": n}}
        finally:
            conn.close()