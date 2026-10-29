"""Text chunking with location tracking."""

from __future__ import annotations

import os
from typing import List, Optional


def chunk_text(
    text: str,
    chunk_lines: int = 40,
    overlap: int = 8,
    max_chars: int = 2000,
) -> List[dict]:
    """Split *text* into overlapping line-window chunks.

    Returns a list of dicts: {line_start, line_end, text} (1-based lines).
    """
    lines = text.split("\n")
    total = len(lines)
    if total == 0:
        return []

    chunks: List[dict] = []
    step = max(1, chunk_lines - overlap)
    start = 0  # 0-based line index
    while start < total:
        end = min(start + chunk_lines, total)
        chunk_lines_text = lines[start:end]
        chunk_text_str = "\n".join(chunk_lines_text)
        if len(chunk_text_str) > max_chars:
            chunk_text_str = chunk_text_str[:max_chars]
        chunks.append({
            "line_start": start + 1,  # 1-based
            "line_end": end,  # 1-based (inclusive)
            "text": chunk_text_str,
        })
        if end >= total:
            break
        start += step
    return chunks


def is_binary(data: bytes) -> bool:
    """Heuristic: file is binary if it contains null bytes."""
    return b"\x00" in data


def read_text_file(path: str) -> Optional[str]:
    """Read a file as text, returning None if binary or unreadable."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
        if is_binary(raw):
            return None
        from security.entropychecker import EntropyChecker
        result = EntropyChecker().feed(raw)
        if result.is_suspicious:
            return None
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return None