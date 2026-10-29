"""SQLite-backed vector store for doc_search."""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = "1"


def _model_dir_name(model: str) -> str:
    return urllib.parse.quote(model, safe="")


def db_path_for(db_root: str, model: str) -> str:
    return os.path.join(db_root, _model_dir_name(model), "db.sqlite")


def connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            mtime REAL,
            size INTEGER,
            indexed_at REAL
        );
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY,
            path TEXT,
            line_start INTEGER,
            line_end INTEGER,
            text TEXT,
            embedding TEXT
        );
    """)
    conn.commit()
    # schema version
    cur = conn.execute("SELECT value FROM meta WHERE key='schema_version'")
    row = cur.fetchone()
    if row is None:
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
        conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    cur = conn.execute("SELECT value FROM meta WHERE key=?", (key,))
    row = cur.fetchone()
    return row[0] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
    conn.commit()


def check_schema_version(conn: sqlite3.Connection) -> bool:
    v = get_meta(conn, "schema_version")
    return v == SCHEMA_VERSION


def upsert_file(conn: sqlite3.Connection, path: str, mtime: float, size: int, indexed_at: float) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO files (path, mtime, size, indexed_at) VALUES (?,?,?,?)",
        (path, mtime, size, indexed_at),
    )


def get_file(conn: sqlite3.Connection, path: str) -> Optional[Tuple[float, int]]:
    cur = conn.execute("SELECT mtime, size FROM files WHERE path=?", (path,))
    row = cur.fetchone()
    if row is None:
        return None
    return (row[0], row[1])


def delete_file_chunks(conn: sqlite3.Connection, path: str) -> None:
    conn.execute("DELETE FROM chunks WHERE path=?", (path,))
    conn.execute("DELETE FROM files WHERE path=?", (path,))


def upsert_chunk(conn: sqlite3.Connection, chunk_id: str, path: str, line_start: int,
                 line_end: int, text: str, embedding: List[float]) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO chunks (chunk_id, path, line_start, line_end, text, embedding) "
        "VALUES (?,?,?,?,?,?)",
        (chunk_id, path, line_start, line_end, text, json.dumps(embedding)),
    )


def get_all_chunks(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    cur = conn.execute("SELECT chunk_id, path, line_start, line_end, text, embedding FROM chunks")
    rows = cur.fetchall()
    out = []
    for r in rows:
        emb = json.loads(r[5]) if r[5] else None
        out.append({
            "chunk_id": r[0],
            "path": r[1],
            "line_start": r[2],
            "line_end": r[3],
            "text": r[4],
            "embedding": emb,
        })
    return out


def get_chunk(conn: sqlite3.Connection, chunk_id: str) -> Optional[Dict[str, Any]]:
    cur = conn.execute(
        "SELECT chunk_id, path, line_start, line_end, text, embedding FROM chunks WHERE chunk_id=?",
        (chunk_id,),
    )
    r = cur.fetchone()
    if r is None:
        return None
    emb = json.loads(r[5]) if r[5] else None
    return {
        "chunk_id": r[0],
        "path": r[1],
        "line_start": r[2],
        "line_end": r[3],
        "text": r[4],
        "embedding": emb,
    }


def count_chunks(conn: sqlite3.Connection) -> int:
    cur = conn.execute("SELECT COUNT(*) FROM chunks")
    return cur.fetchone()[0]


def count_files(conn: sqlite3.Connection) -> int:
    cur = conn.execute("SELECT COUNT(*) FROM files")
    return cur.fetchone()[0]


def list_files(conn: sqlite3.Connection) -> List[str]:
    cur = conn.execute("SELECT path FROM files")
    return [r[0] for r in cur.fetchall()]


def get_newest_mtime(conn: sqlite3.Connection) -> Optional[float]:
    cur = conn.execute("SELECT MAX(mtime) FROM files")
    row = cur.fetchone()
    return row[0] if row and row[0] is not None else None


def clear_all(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM chunks")
    conn.execute("DELETE FROM files")
    conn.execute("DELETE FROM meta WHERE key NOT IN ('schema_version')")
    conn.commit()


def delete_subtree(conn: sqlite3.Connection, path_prefix: str) -> int:
    # Delete chunks/files whose path starts with path_prefix
    cur = conn.execute("SELECT path FROM files")
    to_delete = [r[0] for r in cur.fetchall() if r[0] == path_prefix or r[0].startswith(path_prefix + os.sep) or r[0].startswith(path_prefix + "/")]
    for p in to_delete:
        delete_file_chunks(conn, p)
    conn.commit()
    return len(to_delete)