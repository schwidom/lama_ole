"""Lisp-like query language parser for doc_search."""

from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple


class LispParseError(Exception):
    pass


def _tokenize(s: str) -> List[str]:
    """Tokenize a lisp expression into tokens: '(', ')', quoted strings, unquoted runs."""
    tokens: List[str] = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c.isspace():
            i += 1
            continue
        if c == "(":
            tokens.append("(")
            i += 1
            continue
        if c == ")":
            tokens.append(")")
            i += 1
            continue
        if c == '"':
            # quoted string with escapes
            i += 1
            buf = []
            while i < n and s[i] != '"':
                if s[i] == "\\" and i + 1 < n:
                    esc = s[i + 1]
                    if esc == "n":
                        buf.append("\n")
                    elif esc == "t":
                        buf.append("\t")
                    elif esc == "r":
                        buf.append("\r")
                    elif esc == '"':
                        buf.append('"')
                    elif esc == "\\":
                        buf.append("\\")
                    else:
                        buf.append(esc)
                    i += 2
                else:
                    buf.append(s[i])
                    i += 1
            if i >= n:
                raise LispParseError("unterminated string")
            i += 1  # skip closing quote
            tokens.append('"' + "".join(buf) + '"')
            continue
        # unquoted run
        buf = []
        while i < n and not s[i].isspace() and s[i] not in "()":
            buf.append(s[i])
            i += 1
        if buf:
            tokens.append("".join(buf))
    return tokens


def _parse_tokens(tokens: List[str]) -> Tuple[Any, int]:
    """Parse tokens into an AST. Returns (ast, consumed_count)."""
    if not tokens:
        raise LispParseError("empty expression")
    if tokens[0] == "(":
        # parse list
        i = 1
        items = []
        while i < len(tokens) and tokens[i] != ")":
            sub, consumed = _parse_tokens(tokens[i:])
            items.append(sub)
            i += consumed
        if i >= len(tokens):
            raise LispParseError("missing closing paren")
        # i points at ')'
        return items, i + 1
    else:
        tok = tokens[0]
        if tok.startswith('"') and tok.endswith('"') and len(tok) >= 2:
            return tok[1:-1], 1
        return tok, 1


def parse(expr: str) -> Any:
    """Parse a lisp expression string into an AST.

    A bare string (not starting with '(') is auto-wrapped as ('q', string).
    """
    expr = expr.strip()
    if not expr:
        raise LispParseError("empty query")
    if not expr.startswith("("):
        # auto-wrap as (q "...")
        return ["q", expr]
    tokens = _tokenize(expr)
    ast, consumed = _parse_tokens(tokens)
    if consumed != len(tokens):
        raise LispParseError("trailing tokens after expression")
    return ast


OPERATORS = {"q", "r", "ri", "rf", "rfi", "k", "kc", "and", "or", "not"}


def validate(ast: Any) -> None:
    """Validate an AST's structure."""
    if isinstance(ast, str):
        return
    if not isinstance(ast, list):
        raise LispParseError("invalid AST node")
    if not ast:
        raise LispParseError("empty list")
    head = ast[0]
    if not isinstance(head, str) or head not in OPERATORS:
        raise LispParseError(f"unknown operator: {head}")
    args = ast[1:]
    if head in ("q", "r", "ri", "rf", "rfi"):
        if len(args) != 1 or not isinstance(args[0], str):
            raise LispParseError(f"{head} requires exactly one string argument")
    elif head in ("k", "kc"):
        if len(args) < 1 or not all(isinstance(a, str) for a in args):
            raise LispParseError(f"{head} requires at least one string argument")
    elif head == "not":
        if len(args) != 1:
            raise LispParseError("not requires exactly one argument")
        validate(args[0])
    elif head in ("and", "or"):
        for a in args:
            validate(a)
    else:
        raise LispParseError(f"unknown operator: {head}")