# Plan: Random Bugfixes — `lama_ole` project

**Date:** 2026-10-26  
**Scope:** Fix a set of mistakes found during a code review of the `lama_ole` project.  
**Goal:** Make the codebase consistent with its own documented standards (AGENTS.md), eliminate crashes, fix type-annotation errors, and remove unsafe `eval()` calls.

---

## 1. Overview of Issues

| # | File | Issue | Severity |
|---|------|-------|----------|
| 1 | `tools/edit.py` | `edit_range_based_file3` crashes on `None` search params (`.count()` called on `None`) | **Critical** |
| 2 | `tools/edit.py` | `edit_range_based_file3` requires `sep` with no default, despite docstring saying default is `'\|'` | **High** |
| 3 | `tools/dev_tools_readonly.py` | `fixed` param has no type annotation → inferred as `string`, causing truthy `"false"` | **High** |
| 4 | `tools/example_tools.py` | `read_file` returns raw `str` on success instead of `{"status": "success", "data": ...}` | **Medium** |
| 5 | `tools/edit.py`, `tools/edit_all.py` | `*_help()` functions return plain strings instead of required dict format | **Medium** |
| 6 | `tools/edit.py` | `eval(paramname)` used for validation — unsafe and unnecessary | **Medium** |
| 7 | `tools/example_tools.py` | `calculate` uses `eval()` on LLM-supplied input | **Medium** |
| 8 | `tools/edit.py` | Leftover debug variable `read_lines_tuple3 = None` | **Low** |
| 9 | `tools/dev_tools_readonly.py` | `DIRECTORIES_TO_AVOID` check doesn't prevent descent into avoided dirs | **Low** |
| 10 | `backends/openai_compat_backend.py` | O(n) `pending_ids.pop(0)` in `_sanitize_messages` | **Low** |

---

## 2. Detailed Fix Plan

### Fix 1 — `edit_range_based_file3` crash on `None` params

**File:** `tools/edit.py`, function `edit_range_based_file3`

**Problem:** The validation loop:
```python
for paramname in "pe_search_from,pe_search_to,pg_search_from,pg_search_to".split(','):
    if eval(paramname).count(sep) != 1:
        return {"status": "error", "message": [...]}
```
calls `.count()` on `None` when a search param is `None` (meaning "start/end of file"), causing `AttributeError`.

**Fix:** Guard each param with a `None` check before calling `.count()`:
```python
for paramname in "pe_search_from,pe_search_to,pg_search_from,pg_search_to".split(','):
    val = locals()[paramname]
    if val is not None and val.count(sep) != 1:
        return {"status": "error", "message": [...]}
```

Also replace `eval(paramname)` with `locals()[paramname]` (see Fix 6).

---

### Fix 2 — `edit_range_based_file3` default for `sep`

**File:** `tools/edit.py`, function `edit_range_based_file3`

**Problem:** Signature is `sep: str` (mandatory), but docstring says default is `'|'`.

**Fix:** Change signature to `sep: str = "|"`.

---

### Fix 3 — `fixed` param type annotation in `dev_tools_readonly.py`

**File:** `tools/dev_tools_readonly.py`, functions `grep` and `grep_range_based`

**Problem:** `fixed = False` has no type annotation. `_infer_params` in `tool_base/utils.py` maps unannotated params to `{"type": "string"}`. When the LLM passes `"false"` (a string), `if fixed:` evaluates to `True` (non-empty string), incorrectly enabling fixed mode.

**Fix:** Add `bool` type annotation:
```python
def grep(pattern: str, path: str = ".", include: str = "*", fixed: bool = False) -> Dict[str, Any]:
```
and
```python
def grep_range_based(pattern_from: str = None, pattern_to: str = None, path: str = ".", include: str = "*", fixed: bool = False) -> Dict[str, Any]:
```

Also update `_type_to_json_schema` in `tool_base/utils.py` to include `bool` in the mapping (it already does: `bool: {"type": "boolean"}`), so the annotation will be correctly inferred.

---

### Fix 4 — `read_file` return format in `example_tools.py`

**File:** `tools/example_tools.py`, function `read_file`

**Problem:** Returns a raw string on success, violating the AGENTS.md tool standard (must return `{"status": "success", "data": ...}`).

**Fix:** Wrap the return value:
```python
return {"status": "success", "data": raw_content.decode("utf-8", errors="replace")}
```

---

### Fix 5 — `*_help()` functions return format

**File:** `tools/edit.py` (`edit_help`), `tools/edit_all.py` (`edit_all_help`)

**Problem:** Return plain strings instead of the required dict format.

**Fix:** Wrap returns:
```python
return {"status": "success", "data": "Tools for editing files."}
```

---

### Fix 6 — Replace `eval(paramname)` with `locals()[paramname]`

**File:** `tools/edit.py`, function `edit_range_based_file3`

**Problem:** `eval(paramname)` is unsafe and unnecessary. `paramname` is a controlled string, but `eval` is a code smell.

**Fix:** Replace `eval(paramname)` with `locals()[paramname]`.

---

### Fix 7 — `calculate` uses `eval()`

**File:** `tools/example_tools.py`, function `calculate`

**Problem:** `eval(expression, {"__builtins__": {}}, allowed)` on LLM-supplied input. While restricted, `eval` can still be exploited (e.g., via `().__class__.__bases__`).

**Fix:** Replace `eval` with `ast.literal_eval` for simple expressions, or use a safe math parser. Given the tool only supports basic math, use `ast.literal_eval` with a fallback, or better, implement a simple safe evaluator. For minimal change, restrict to `ast.literal_eval` which only evaluates literals (not function calls), but this breaks `abs()`, `min()`, etc.

**Alternative:** Keep `eval` but add a note that this is a known limitation. Given the scope of "random bugfixes", the minimal fix is to document the risk and optionally add an `ast`-based safe evaluation. For now, replace with a safer approach using `ast.parse` and a restricted node visitor, or simply keep `eval` with a comment. 

**Decision:** Implement a minimal safe evaluator using `ast` module that only allows arithmetic operations and the allowed functions. This is the most correct fix.

---

### Fix 8 — Remove leftover debug variable

**File:** `tools/edit.py`

**Problem:** `read_lines_tuple3 = None` at module level is a leftover.

**Fix:** Remove the line.

---

### Fix 9 — `DIRECTORIES_TO_AVOID` descent issue

**File:** `tools/dev_tools_readonly.py`, function `grep`

**Problem:** The check:
```python
if any([x in DIRECTORIES_TO_AVOID for x in root.split('/')]):
    continue
```
skips processing files in that root, but `os.walk` still descends into subdirectories of avoided dirs.

**Fix:** Use `os.walk` with `topdown=True` and prune `dirs` in place:
```python
for root, dirs, files in os.walk(path):
    dirs[:] = [d for d in dirs if d not in DIRECTORIES_TO_AVOID]
    ...
```

---

### Fix 10 — O(n) `pop(0)` in `_sanitize_messages`

**File:** `backends/openai_compat_backend.py`, method `_sanitize_messages`

**Problem:** `pending_ids.pop(0)` is O(n) per tool result.

**Fix:** Use a `collections.deque` or an index pointer instead of `pop(0)`:
```python
pending_idx = 0
...
msg["tool_call_id"] = m.get("tool_call_id") or pending_ids[pending_idx]
pending_idx += 1
```

---

## 3. Implementation Order

1. Fix 1 + Fix 6 (edit.py — crash + eval replacement) — highest priority
2. Fix 2 (edit.py — sep default)
3. Fix 3 (dev_tools_readonly.py — type annotation)
4. Fix 4 (example_tools.py — read_file return format)
5. Fix 5 (edit.py, edit_all.py — help functions)
6. Fix 7 (example_tools.py — calculate eval)
7. Fix 8 (edit.py — remove debug var)
8. Fix 9 (dev_tools_readonly.py — os.walk pruning)
9. Fix 10 (openai_compat_backend.py — pop(0) optimization)

---

## 4. Testing Strategy

- Run existing test suite: `python3 tests/run_all_tests.py`
- Add unit tests for:
  - `edit_range_based_file3` with `None` params (should not crash)
  - `edit_range_based_file3` with default `sep`
  - `grep`/`grep_range_based` with `fixed=False` passed as string `"false"` (should not enable fixed mode)
  - `read_file` success returns dict with `status` and `data`
  - `edit_help` / `edit_all_help` return dict format
- Verify no regressions in existing edit tests

---

## 5. Files Modified

| File | Changes |
|------|---------|
| `tools/edit.py` | Fix 1, 2, 5, 6, 8 |
| `tools/edit_all.py` | Fix 5 |
| `tools/dev_tools_readonly.py` | Fix 3, 9 |
| `tools/example_tools.py` | Fix 4, 7 |
| `backends/openai_compat_backend.py` | Fix 10 |
| `tool_base/utils.py` | Verify `bool` in type mapping (already present) |
