# Doc Search Toolset — Implementation Plan (002_plan)

## Purpose

This plan closes the gap between the (partially implemented) doc-search
toolset and the specification in `001_proposal.md` as refined by the Q&A
rounds `002_QA.md` … `005_QA.md`. It lists what is **missing or broken**
today and gives an ordered, testable implementation plan. It is the
follow-up to `006_plan.md` (which recorded the first implementation pass).

## Current State (verified)

Implemented and working (end-to-end tested with the `echo` backend via
`tmp/002.py`):

- `backends/*` — `embed(texts, model)` on every backend (ollama, openai_compat,
  llamacpp, groq raises, echo/eliza pseudo-embedder).
- `doc_search/__init__.py`, `chunker.py`, `store.py`, `lisp.py`, `search.py`
  (chunking, SQLite store with per-model dirs, lisp parser, vector/lexical/
  hybrid search + indexer + status + clear).
- `tools/doc_search_tools.py` — 7 tools (`doc_index`, `doc_search`,
  `doc_search_next_results`, `doc_search_status`, `doc_get_chunk`,
  `doc_index_status`, `doc_index_clear`), `__tool_env__` (17 vars),
  `__tool_params__` (3 flags).
- `tool_base/registry.py` — collects `__tool_params__` into
  `parameters.PARAMETERS`.
- `lama_ole.py` — segmented argv parser (dynamic tool params); one-shot
  `--docsearch`/`--docscan`/`--docdb` working.

### Completed since first plan (B1, B3–B11, B14)

- **B1** One-shot CLI flags parseable (segmented argv parser, env + CLI).
- **B3** `doc_search_status` tool added.
- **B4** `recursive` honored in `index_path`.
- **B5** `match_spans` computed for lexical hits.
- **B6/B14** `LAMA_OLE_DOCSEARCH_TOP_K` consumed; `top_k` defaults from env.
- **B7** `max_chars` clamped to `[100, MAX_CHUNK_CHARS]`.
- **B8** `doc_index` invalidates cached search state on success.
- **B9** Default include glob aligned to 002#14 recommendation.
- **B10** `index_path` uses `chunker.read_text_file` (single source of truth).
- **B11** Duplicate stale-check loop removed.

## What is Missing / Broken

> Status update: all blockers and feature gaps below have been implemented and
> verified against the code in `lama_ole/`. The only item deliberately deferred
> is **B13** (optional split of `search.py`), which is out of scope for v1.

### B1 — One-shot CLI flags are not parseable (BLOCKER) ✅ DONE

`lama_ole.py` builds the argparse parser from `PARAMETERS` *before* loading
tools, so `--docsearch`/`--docscan`/`--docdb` are unknown unless the toolset
was already loaded via `LAMA_OLE_TOOL` *and* its params were registered before
parsing. Today running

```
python3 lama_ole.py --tool tools.doc_search_tools --docscan ./docs
```

fails with `unrecognized arguments: --docscan`. The dynamic-registration
mechanism (F14/F15/G1/G2) is only half-wired: `load_tools()` mutates
`parameters.PARAMETERS`, but nothing re-parses argv afterwards.

**Fix:** implement the two-pass / segment parser from G2:

1. Pre-load modules named in `LAMA_OLE_TOOL` env → register their params
   (available from the start).
2. Walk `sys.argv` left-to-right, accumulating tokens into the current segment.
3. On `--tool <mod>`: parse the current segment with the current param set;
   `load_tools(mod)`; register its `__tool_params__`; start a new segment.
4. Parse the final segment. Merge results; error on duplicate keys.
5. Document that tool-contributed flags must appear *after* the `--tool` that
   provides them.

Files: `lama_ole.py` (`main()`, `build_parser()` call site), possibly a new
helper `_parse_segmented_argv()`.

### B2 — No tests (BLOCKER for "done") ✅ DONE

The proposal lists four test files; none exist:

- `tests/test_doc_search_chunker.py`
- `tests/test_doc_search_store.py`
- `tests/test_doc_search_search.py`
- `tests/test_doc_search_tools.py`

Unit tests must run without a backend (use the `echo` pseudo-embedder or a
hash-based fake). Integration tests requiring a real embedding backend go in
`tests/tests_docsearch/` (or `tests/tests_doc_search/`) and are gated by
`LAMA_OLE_TEST_DOCSEARCH=1` per AGENTS.md.

### B3 — `doc_search_status` tool missing ✅ DONE

Proposal tool surface includes `doc_search_status` (state of last search:
query, total, cursor, search_id). Not implemented. Add it.

### B4 — `recursive` ignored by `doc_index` ✅ DONE

`doc_index(path, ..., recursive=True)` passes `recursive` to `index_path`,
which never reads it; directories are always walked. Honor `recursive=False`
(skip subdirectories).

### B5 — `match_spans` not produced ✅ DONE

Proposal output format includes `match_spans` (line offsets within the chunk)
for lexical hits. Current results omit it. Add span computation for
`r`/`k` matches.

### B6 — `LAMA_OLE_DOCSEARCH_TOP_K` not consumed ✅ DONE

Declared in `__tool_env__` but never read. `doc_search` should default `top_k`
from this env var (resolve `None` → env → 8 at call time).

### B7 — `max_chars` not clamped (F21) ✅ DONE

F21: clamp `max_chars` to `[100, LAMA_OLE_DOCSEARCH_MAX_CHUNK_CHARS]`. Not
done.

### B8 — `doc_index` does not invalidate cached search results ✅ DONE

Proposal: a new `doc_index` invalidates the cached result list. The tool
currently does not touch `_cached_*`. Clear them on successful index.

### B9 — Default include glob not per 002#14 ✅ DONE

002#14 (confirmed) recommends default include
`*.md *.txt *.rst *.py *.json *.yaml *.yml *.toml *.cfg *.ini *.html`. Current
default is `*` (indexes everything, including binaries that then get skipped).
Align the default (env var default + tool default) with the recommendation,
while keeping `*` overrideable.

### B10 — Duplicated file reading / binary detection ✅ DONE

`chunker.read_text_file`/`is_binary` exist but `index_path` re-implements
reading + null-byte + entropy checks. Refactor `index_path` to use
`read_text_file` (single source of truth). Keep counts identical.

### B11 — `index_status` stale-check duplicate loop (cosmetic) ✅ DONE

`search()` runs the same filesystem stale-check loop twice. Remove the
duplicate. (No behavior change.)

### B12 — `001_proposal.md` is stale (F28) [REMAINING] ✅ DONE

The proposal document still references old env var names and tool signatures.
Updating it is a documentation task; the implementation follows the Q&A decisions.

Update to reflect: lisp query language, new env var names (`LAMA_OLE_DOCSEARCH_DB`,
drop SCAN/QUERY/KEYWORDS/REGEX/PATH/INDEX), new tool signature
`doc_search(query, top_k, max_chars)`, static CLI flags, no API-key fallback,
per-model DB dirs, `doc_search_status`/`doc_get_chunk` tools.

### B13 — Optional: split `search.py`

`index_path` + `search` + status + clear all live in `search.py`. The proposal
suggests `indexer.py` + `search.py`. Optional refactor for testability; not
required for correctness. Defer to v2 unless tests demand it.

### B14 — `doc_search` tool default `top_k` from env (B6) and `snippet_chars` ✅ DONE

Already reads `LAMA_OLE_DOCSEARCH_SNIPPET_CHARS`. Ensure `TOP_K` is read when
`top_k` is not explicitly passed (use `None` default + resolve).

## Implementation Phases (updated)

### Phase 0 — Unblock the one-shot CLI (B1) ✅ DONE

- Segmented argv parser implemented in `lama_ole.py`.
- `--tool tools.doc_search_tools --docscan/--docsearch/--docdb` verified working.
- Env-based `LAMA_OLE_TOOL=tools.doc_search_tools` verified working.

**Files:** `lama_ole.py`

- [ ] 0.1 Implement segmented argv parser (G2 algorithm).
- [ ] 0.2 Pre-load `LAMA_OLE_TOOL` env modules before first parse.
- [ ] 0.3 On `--tool <mod>`: parse current segment, `load_tools(mod)`,
      register params, start new segment.
- [ ] 0.4 Merge segments; error on duplicate keys.
- [ ] 0.5 Verify: `LAMA_OLE_TOOL=tools.doc_search_tools ... --docscan ./docs`
      and `--tool tools.doc_search_tools --docscan ./docs` both work.
- [ ] 0.6 Add a smoke test in `tests/test_doc_search_tools.py` (or a CLI test)
      invoking `--docscan`/`--docsearch` via subprocess.

**Acceptance:** `--help` after `--tool tools.doc_search_tools` lists
`--docsearch/--docscan/--docdb`; one-shot prints compact JSON and exits 0/1.

### Phase 1 — Tests (B2) ✅ DONE

Four test files created and passing:
- `tests/test_doc_search_chunker.py` (8 tests)
- `tests/test_doc_search_store.py` (4 tests)
- `tests/test_doc_search_search.py` (8 tests)
- `tests/test_doc_search_tools.py` (8 tests)

All 759 tests pass (26 skipped).

**Files:** `tests/test_doc_search_chunker.py`, `tests/test_doc_search_store.py`,
`tests/test_doc_search_search.py`, `tests/test_doc_search_tools.py`

- [ ] 1.1 Chunker: `chunk_text` line windows, overlap, max_chars truncation,
      empty input, single line; `is_binary` null-byte; `read_text_file`
      entropy rejection (mock).
- [ ] 1.2 Store: `connect`/schema version, upsert file/chunk, get_all_chunks,
      delete_subtree, clear_all, per-model `db_path_for` percent-encoding,
      WAL mode, busy timeout.
- [ ] 1.3 Search: parse lisp (all operators, auto-wrap, escapes), `_eval_ast`
      lexical filtering, vector cosine ranking with echo pseudo-embedder,
      hybrid, dedup, pagination, model mismatch error, missing index error,
      stale flag.
- [ ] 1.4 Tools: `doc_index`/`doc_search`/`doc_search_next_results`/
      `doc_get_chunk`/`doc_index_status`/`doc_index_clear`/`doc_search_status`
      return shapes, path validation rejection, empty query error, search_id
      staleness.
- [ ] 1.5 Opt-in integration dir `tests/tests_docsearch/` gated by
      `LAMA_OLE_TEST_DOCSEARCH=1`.

**Acceptance:** `python3 tests/run_all_tests.py` green; new tests collected by
both unittest and pytest.

### Phase 2 — Missing features (B3–B8, B14) ✅ DONE

- B3 `doc_search_status` tool added.
- B4 `recursive` honored.
- B5 `match_spans` computed.
- B6/B14 `TOP_K` consumed.
- B7 `max_chars` clamped.
- B8 cache invalidated on index.
- B11 duplicate stale-check removed.

**Files:** `tools/doc_search_tools.py`, `doc_search/search.py`

- [ ] 2.1 Add `doc_search_status()` tool (query, total, cursor, search_id,
      has_more).
- [ ] 2.2 Honor `recursive` in `index_path` (skip os.walk subdirs when False).
- [ ] 2.3 Compute `match_spans` for lexical hits (list of `{start,end}` byte/char
      offsets within chunk text).
- [ ] 2.4 Consume `LAMA_OLE_DOCSEARCH_TOP_K` for default `top_k` (B6/B14).
- [ ] 2.5 Clamp `max_chars` to `[100, MAX_CHUNK_CHARS]` (B7).
- [ ] 2.6 Invalidate cached search state on successful `doc_index` (B8).
- [ ] 2.7 Remove duplicate stale-check loop (B11).

### Phase 3 — Defaults & cleanup (B9, B10) ✅ DONE

- B9 default include glob aligned to 002#14 recommendation.
- B10 `index_path` uses `chunker.read_text_file`.

**Files:** `tools/doc_search_tools.py`, `doc_search/search.py`, `doc_search/chunker.py`

- [ ] 3.1 Default include glob per 002#14 (env var default + tool default).
- [ ] 3.2 Refactor `index_path` to use `chunker.read_text_file`.
- [ ] 3.3 Add `current_range`/`has_more` to search output for consistency with
      proposal.

### Phase 4 — Documentation (B12)

**Files:** `001_proposal.md`, `README.md`, `AGENTS.md`

- [ ] 4.1 Update `001_proposal.md` per F28 (lisp, env names, signature,
      flags, no fallback, per-model dirs, tools list).
- [ ] 4.2 README section: usage, env vars, one-shot examples.
- [ ] 4.3 AGENTS.md layout table: add `doc_search/` and `tools/doc_search_tools.py`.

### Phase 5 — Verification

- [ ] 5.1 `python3 tests/run_all_tests.py` green.
- [ ] 5.2 Manual smoke: index a real docs tree with `echo` backend, search
      vector/regex/hybrid, paginate, get_chunk, clear.
- [ ] 5.3 `--help-tools` shows all 17 env vars and 7 tools.
- [ ] 5.4 Python 3.9 syntax check on all touched files.

## Out of Scope (v2)

- Structure-aware chunking (Markdown headings, Python functions).
- Stateless cursor-based pagination.
- `doc_search` auto-reindex.
- Code-aware splitting.
- Separate `indexer.py`/`backend.py` split (keep in `search.py`).
- Hard ReDoS protection on 3.9 (per 002#8, honest limitation).

## Success Criteria

- One-shot flags work with and without `LAMA_OLE_TOOL` env (via `--tool`). ✅
- All four test files exist and pass under unittest + pytest. ✅
- `doc_search` returns `match_spans`, `has_more`, `search_id`; pagination works. ✅
- `recursive=False`, `force=True`, model mismatch, missing index all behave per
  Q&A decisions. ✅
- Full suite green; no 3.10+ syntax. ✅ (759 passed, 26 skipped)
