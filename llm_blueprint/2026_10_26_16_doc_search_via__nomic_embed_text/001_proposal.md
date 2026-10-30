# Doc Search Toolset — Final Specification

## Purpose

This document defines the **Doc Search Toolset** (`tools/doc_search_tools.py`) for `lama_ole`. It provides a loadable toolset that enables an LLM to retrieve exact documentation passages from indexed source trees using a combination of:

- **Semantic search** (vector embeddings via `nomic-embed-text` or any compatible embedding model served through the `backends/` package).
- **Lexical search** (keywords and regular expressions) evaluated over indexed chunks.

The toolset returns small, located chunks (text + file path + line range) so the LLM can cite and reason over precise content without bloating the context window. It follows established repository patterns: standard `{"status": ..., "data/": ...}` return contract, cached-session pagination (`*_next_results`), `validate_path` safety, and Python 3.9 compatibility.

## Design Principles

| Principle | Rationale |
|---|---|
| **Stdlib-first** | No mandatory third-party runtime deps beyond what `backends/` already requires (e.g., `requests`). Vector math uses pure Python; `numpy` is optional. |
| **Read-only toolset** | `__tool_readonly__ = True`. Indexing writes only to a dedicated cache directory (`LAMA_OLE_DOCSEARCH_DB`), never to the source tree. |
| **Reuse `validate_path`** | Every `path` argument is validated via `tools_security.validate_path` (D11 of the LSP blueprint). |
| **Reuse `backends/` for embeddings** | The chat backend package (`backends/`) is extended with `embed(texts, model)` on `LlmBackend`. No parallel adapter module. Host normalization and backend registry are shared. |
| **Config-only env vars** | All `LAMA_OLE_DOCSEARCH_*` environment variables define configuration defaults only (DB root, backend host/model/key, chunking/retrieval/filter params). They do not drive search execution. |
| **Static CLI flags for one-shot** | One-shot actions use static parameters (`--docsearch`, `--docscan`, `--docdb`) declared in `parameters.py`. No dynamic registration or autoload of the toolset. |
| **Lisp query language** | A single `query` parameter accepts a Lisp-like S-expression language for all search logic (vector, lexical, and boolean composition), eliminating separate keyword/regex/mode parameters. |
| **Per-model storage isolation** | One SQLite DB per embedding model under `./docsearch/<url-encoded-model>/db.sqlite`. Model or chunking param mismatches require explicit rebuild (`force=True`). |
| **Python 3.9 compatible** | Uses `typing.Optional`/`Union`, no `match`/`case`, no 3.10+ stdlib features. |

## Architecture and File Layout

```
lama_ole/
├── tools/
│   └── doc_search_tools.py          ← Loadable toolset (@tool surface, __tool_env__, __tool_params__)
├── doc_search/                      ← Engine package (core logic)
│   ├── __init__.py                  ← Package marker
│   ├── chunker.py                   ← Text → chunks (path, lines, text), binary detection via EntropyChecker
│   ├── store.py                     ← SQLite vector store: files / chunks / meta tables; per-model DB dirs; WAL mode
│   ├── lisp.py                      ← Lisp-like query language tokenizer + parser + AST evaluator
│   └── search.py                    ← Search engine (vector/lexical/hybrid), indexer, status, clear
├── backends/                        ← Reused for embeddings (modified)
│   ├── base.py                      ← LlmBackend.embed(texts, model) abstract method added
│   ├── ollama_backend.py            ← embed() via /api/embed (+ /api/embeddings fallback)
│   ├── openai_compat_backend.py     ← embed() via /v1/embeddings
│   ├── llamacpp_backend.py          ← inherits openai_compat embed
│   ├── groq_backend.py              ← embed() raises NotImplementedError (Groq has no embedding endpoint)
│   ├── echo_backend.py              ← deterministic pseudo-embedder (SHA-256 → 64-dim unit vector, for tests)
│   └── eliza_backend.py             ← same pseudo-embedder as echo
├── tool_base/
│   └── registry.py                  ← Modified: load_tools() collects __tool_params__ and registers into parameters.PARAMETERS
└── lama_ole.py                      ← Modified: one-shot --docsearch / --docscan / --docdb mode
```

## Final Tool Surface and Signatures

All functions decorated with `@tool(description=...)`. Module marked `__tool_readonly__ = True`. Every call returns the standard dict shape:

```python
{"status": "success", "data": { ... }}
# or
{"status": "error", "message": ["human-readable error string"]}
```

| Tool | Purpose | Signature | Key Behavior |
|---|---|---|---|
| `doc_index` | Index (or re-index) documents under a path. | `doc_index(path: str, include: Optional[str] = None, exclude: str = "", recursive: bool = True, force: bool = False)` | Walks path, applies entropy/binary check, chunks text, embeds via backend, upserts to SQLite DB. `include=None` resolves to `LAMA_OLE_DOCSEARCH_INCLUDE` (default `*.md *.txt *.rst *.py *.json *.yaml *.yml *.toml *.cfg *.ini *.html`). Respects `force=True` to rebuild even on model/param mismatch. Returns counts (`files_indexed`, `chunks_indexed`, `files_skipped`, `errors`, `db_path`). |
| `doc_search` | Search the index using a Lisp query or plain string. | `doc_search(query: str, top_k: Optional[int] = None, max_chars: int = 400)` | Parses lisp → evaluates lexical filter → embeds query → cosine ranks candidates → returns top-k truncated snippets with locations. `top_k=None` resolves to `LAMA_OLE_DOCSEARCH_TOP_K` (default 8), clamped to `[1, LAMA_OLE_DOCSEARCH_MAX_RESULTS]`. `max_chars` clamped to `[100, LAMA_OLE_DOCSEARCH_MAX_CHUNK_CHARS]`. Mode derived from operators present (`q`→vector, `r/k`→lexical, both→hybrid). Plain strings auto-wrapped as `(q "...")`. |
| `doc_search_next_results` | Next page of the last `doc_search`. | `doc_search_next_results(maxcount: int = 10, search_id: Optional[str] = None)` | Continues pagination over cached results. `maxcount` clamped to `[1, 10]`. Validates `search_id` if provided (staleness detection). Errors if no active search or `search_id` mismatch. Returns next page with `has_more`. |
| `doc_search_status` | Show state of the last `doc_search`. | `doc_search_status()` | Returns `query`, `total`, `cursor`, `search_id`, `has_more` for the most recent search. |
| `doc_get_chunk` | Retrieve full text of a chunk by ID. | `doc_get_chunk(chunk_id: str)` | Looks up chunk in DB, returns full text (already capped at `max_chunk_chars` at index time), plus location metadata (`path`, `line_start`, `line_end`). Used for targeted expansion after search truncation. |
| `doc_index_status` | Show index statistics and staleness. | `doc_index_status()` | Returns `exists`, `db_path`, `model`, `configured_model`, `model_match`, `file_count`, `chunk_count`, `chunk_lines`, `chunk_overlap`, `max_chunk_chars`, `last_indexed_at`, `index_stale`. No file contents returned. If no index exists, returns `exists: false` and `db_path`. |
| `doc_index_clear` | Clear the index (whole DB or subtree). | `doc_index_clear(path: Optional[str] = None)` | If `path` given: remove that subtree's chunks/files from DB (`files_removed` in response). If `None`: delete entire DB file plus WAL/SHM sidecars (`deleted: true` in response; `deleted: false` if no index exists). Irreversible; no confirmation prompt. |

### Parameter Precedence

Explicit tool arguments override environment variables, which override built-in defaults. This is consistent across all tools.

## Lisp Grammar and Escaping Rules

The `query` parameter accepts a Lisp-like S-expression language or a plain string. The grammar supports vector search (`q`), lexical filtering (`r`, `k`), and boolean composition (`and`, `or`, `not`).

### Operators

| Operator | Arity | Semantics |
|---|---|---|
| `(q "text")` | 1 string | Embed `"text"`; compute cosine similarity against all indexed chunks. Produces a vector score used for ranking (not filtering, unless combined with lexical ops). |
| `(r "regex")` | 1 string | Apply Python `re` regex pattern per chunk. Case-sensitive by default. Returns boolean match. |
| `(ri "regex")` | 1 string | Same as `r`, but case-insensitive (`re.IGNORECASE`). |
| `(rf "regex")` | 1 string | Treat `"regex"` as a fixed literal string (metacharacters escaped). Case-sensitive. Equivalent to `re.escape(pattern)` then match. |
| `(rfi "regex")` | 1 string | Same as `rf`, but case-insensitive. |
| `(k "word1" "word2" ...)` | 1+ strings | Case-insensitive substring matching for each keyword. Keywords are OR-combined by default (any match suffices). |
| `(kc "word1" "word2" ...)` | 1+ strings | Same as `k`, but case-sensitive matching. |
| `(and expr ...)` | 0 to n expressions | Boolean AND. Short-circuit left-to-right. `(and)` with zero args evaluates to **True** (identity). All sub-expressions must match for the chunk to be included in the candidate set. |
| `(or expr ...)` | 0 to n expressions | Boolean OR. Short-circuit left-to-right. `(or)` with zero args evaluates to **False**. At least one sub-expression must match. |
| `(not expr)` | exactly 1 expression | Boolean NOT. Unary negation of the sub-expression result. Errors if arity ≠ 1. |

### Plain String Auto-Wrapping

A bare string passed as `query` is automatically wrapped as a vector query: `"how to configure"` → `(q "how to configure")`. Strings starting with `(` are parsed as Lisp expressions. This keeps the common case ergonomic while enabling complex queries when needed.

**Practical examples:**

```lisp
(q "which file contains the docs about LSP?")
  → Pure vector search for the query text.

(r ".*\.md")
  → Lexical regex filter: only chunks from .md files match.

(k "configuration" "setup")
  → Lexical keyword filter: chunks containing either word (case-insensitive, OR).

(and (q "which file contains the docs about LSP?") (r ".*\.md"))
  → Hybrid: lexical filter to .md files first, then re-rank by cosine similarity.

(and (q "keep_alive config") (not (rf "deprecated")))
  → Vector search excluding chunks containing the literal string "deprecated".

(or (k "LSP") (r "language.*server"))
  → Lexical OR: matches chunks with keyword "LSP" or regex pattern "language.*server".
```

### String Escaping Rules

Inside quoted strings, standard escape sequences apply:

| Escape | Meaning |
|---|---|
| `\"` | Literal double-quote character. |
| `\\` | Literal backslash character. |
| `\n` | Newline (LF). |
| `\t` | Tab character. |
| `\r` | Carriage return. |

**Double-escaping for regex:** Because the lisp parser unescapes strings first, then passes them to Python `re`, regex patterns containing backslashes require double-escaping in the Lisp string. For example, to match a digit (`\d`), write `(r "\\d")` — the lisp parser converts `\\d` to `\d`, which `re` interprets as the digit metacharacter.

### Unquoted Tokens and Disambiguation

Operators are recognized only in **head position** (first token) of a list. Any token in argument position is treated as a string, quoted or unquoted. Thus `(k foo bar)` and `(k "foo" "bar")` are equivalent. Unquoted tokens cannot contain spaces, parentheses, or backslashes and are split on whitespace. Regex patterns should always be quoted (they typically contain metacharacters or spaces).

### Evaluation Model

The lisp expression is evaluated against each chunk:
1. **Lexical operators** (`r`, `ri`, `rf`, `rfi`, `k`, `kc`) produce a boolean match per chunk.
2. **`q`** embeds the query text and computes cosine similarity for ranking (not filtering). If multiple `q` nodes exist in an `and`, their scores are averaged for final ranking.
3. **`and`/`or`/`not`** combine results left-to-right with short-circuit evaluation. `(and)` → True, `(or)` → False.
4. For pure lexical queries (no `q`), results are sorted by file path then line number. For mixed or vector-only queries, results are ranked by cosine similarity (descending) and clamped to `top_k`.

### Error Cases

- Unbalanced parentheses → error with 1-based position info.
- `(not)` with no args → arity error.
- Empty input after trimming → "query is required" error (no env-var fallback).
- Unknown operator name → parse error.

## Environment Variables (Final List)

All `LAMA_OLE_DOCSEARCH_*` variables are **configuration only**. They do not trigger searches or define search defaults. One-shot actions use static CLI flags (`--docsearch`, `--docscan`, `--docdb`).

| Variable | Default | Description |
|---|---|---|
| `LAMA_OLE_DOCSEARCH_DB` | `./docsearch` | Root directory for persisted SQLite DBs. Final DB path: `$DB/<url-encoded-model>/db.sqlite`. One DB per model variant. |
| `LAMA_OLE_DOCSEARCH_BACKEND` | `ollama` | Embedding backend name: `ollama`, `openai_compat`, `llamacpp`, etc. Reuses `backends/` registry. |
| `LAMA_OLE_DOCSEARCH_HOST` | (backend default) | Host endpoint of the embedding backend. Normalized via `_compat.normalize_host`. |
| `LAMA_OLE_DOCSEARCH_MODEL` | `nomic-embed-text` | Embedding model name. Used to derive subdirectory under `DB` root and passed per-call to `backend.embed(texts, model)`. |
| `LAMA_OLE_DOCSEARCH_API_KEY` | (none) | API key for the embedding backend. **No fallback** to global `LAMA_OLE_API_KEY`. Local Ollama accepts unset; remote endpoints raise backend errors naturally if required but missing. |

### Chunking Parameters

| Variable | Default | Description |
|---|---|---|
| `LAMA_OLE_DOCSEARCH_CHUNK_LINES` | `40` | Lines per chunk. Stored in DB `meta`; mismatch with existing index requires `force=True`. |
| `LAMA_OLE_DOCSEARCH_CHUNK_OVERLAP` | `8` | Overlapping lines between adjacent chunks for context continuity. |
| `LAMA_OLE_DOCSEARCH_MAX_CHUNK_CHARS` | `2000` | Hard cap on chunk text length at index time. |

### Retrieval Parameters

| Variable | Default | Description |
|---|---|---|
| `LAMA_OLE_DOCSEARCH_TOP_K` | `8` | Default number of chunks returned by `doc_search`. Clamped to `[1, LAMA_OLE_DOCSEARCH_MAX_RESULTS]`. Per-call override via `top_k` param. |
| `LAMA_OLE_DOCSEARCH_MAX_RESULTS` | `20` | Hard cap on total results per call. |
| `LAMA_OLE_DOCSEARCH_MIN_SCORE` | `0.25` | Minimum cosine similarity threshold for vector hits. In v1, this is a soft annotation (hits below threshold are returned but flagged `below_threshold: true`), not a hard filter. |
| `LAMA_OLE_DOCSEARCH_SNIPPET_CHARS` | `600` | Max characters of chunk text returned in search results. Excess is truncated with an ellipsis marker; full length reported as `full_length`. Use `doc_get_chunk(chunk_id)` for full text. |

### Indexing Filters

| Variable | Default | Description |
|---|---|---|
| `LAMA_OLE_DOCSEARCH_INCLUDE` | `*.md *.txt *.rst *.py *.json *.yaml *.yml *.toml *.cfg *.ini *.html` | Glob patterns (space-separated) for files to index. Applied via `fnmatch` to basenames. |
| `LAMA_OLE_DOCSEARCH_EXCLUDE` | `.git __pycache__ node_modules` | Glob patterns (space-separated) for directories/files to skip during walk. Directory names in `avoid_dirs` (`.git`, `__pycache__`, `node_modules`, `.docsearch`) are always pruned. |
| `LAMA_OLE_DOCSEARCH_MAX_FILE_BYTES` | `2000000` (2 MB) | Skip files larger than this size; count them in status as skipped. |

### Embedding Backend Parameters

| Variable | Default | Description |
|---|---|---|
| `LAMA_OLE_DOCSEARCH_EMBED_BATCH` | `32` | Number of chunks batched per embedding request. Batches are sequential to keep memory bounded. |
| `LAMA_OLE_DOCSEARCH_EMBED_TIMEOUT` | `60` (seconds) | Timeout per individual embedding HTTP request. |

## Storage Schema and Per-Model DB Directories

### Directory Layout

The DB root is defined by `LAMA_OLE_DOCSEARCH_DB` (default `./docsearch`). Each embedding model gets its own subdirectory:

```
./docsearch/
├── nomic-embed-text/
│   └── db.sqlite          ← SQLite index for this model
├── mxbai-embed-large/
│   └── db.sqlite
└── huggingface.co%2Fmodel/  ← URL-encoded model names (e.g., "/" → "%2F")
    └── db.sqlite
```

Model names are URL-encoded via `urllib.parse.quote(model, safe="")` to produce the subdirectory name. This handles slashes (`/`), colons (`:`), spaces, and other filesystem-hostile characters safely. The raw model name is stored in the DB `meta` table as the source of truth; on load, the directory's `meta.model` is verified against the configured model name, and a mismatch errors with "incompatible index — run doc_index(force=True)".

### SQLite Schema

Three tables per DB (schema version stored in `meta`; mismatch → error):

**`files` table** — tracks indexed source files:
| Column | Type | Description |
|---|---|---|
| `path` | TEXT PRIMARY KEY | File path relative to index root. |
| `mtime` | REAL | Modification timestamp at indexing time. |
| `size` | INTEGER | File size in bytes at indexing time. |
| `indexed_at` | REAL | SQLite `strftime('%s', 'now')` timestamp. |

**`chunks` table** — stores chunk text and embeddings:
| Column | Type | Description |
|---|---|---|
| `chunk_id` | TEXT PRIMARY KEY | Format `{path}\x1f{line_start}\x1f{line_end}` internally; displayed as `{path}:{line_start}-{line_end}`. |
| `path` | TEXT | File path (redundant, for indexing). |
| `line_start` | INTEGER | 1-based start line number. |
| `line_end` | INTEGER | 1-based end line number (inclusive). |
| `text` | TEXT | Chunk text, capped at `max_chunk_chars`. |
| `embedding` | TEXT | JSON array of floats representing the embedding vector. |

**`meta` table** — key-value store for index metadata:
| Column | Type | Description |
|---|---|---|
| `key` | TEXT PRIMARY KEY | Meta key name (e.g., `model`, `schema_version`, `chunk_lines`). |
| `value` | TEXT | Meta value. |

Key meta entries:
- `model`: raw embedding model name.
- `schema_version`: integer schema version (v1).
- `chunk_lines`, `chunk_overlap`, `max_chunk_chars`: stored chunking params; mismatch with configured values on `doc_index` triggers a rebuild requirement (`force=True`).

### SQLite Concurrency

WAL mode is enabled for concurrent read safety. A busy timeout of 5 seconds is applied. Indexing takes write locks; searches are readers. Concurrent heavy use (simultaneous indexing + searching) is not a supported scenario but is mitigated by WAL.

## Indexing, Search, Ranking, and Pagination Behavior

### Indexing (`doc_index`)

1. **Validate path** via `tools_security.validate_path` (relative paths only unless basepath registered for tests).
2. **Walk** the path (file or directory). `recursive=False` skips subdirectories. Apply `include`/`exclude` globs and prune high-entropy/binary files using `EntropyChecker` + null-byte heuristic (via `chunker.read_text_file`). Skip files above `max_file_bytes`.
3. **Chunk** each text file into overlapping line windows: `chunk_lines` lines per chunk, `chunk_overlap` overlap. Each chunk records `{chunk_id, path, line_start, line_end, text}` with text hard-capped at `max_chunk_chars`. `chunk_id` format is `{path}\x1f{line_start}\x1f{line_end}` internally.
4. **Embed** chunks in batches of `embed_batch` via `backend.embed(texts, model)`. Batch requests are sequential to keep memory bounded. Progress logged to stderr (not returned as tool data).
5. **Upsert** to SQLite: by `(path, chunk_id)` for changed files; delete stale chunks for removed/renamed files. Unchanged files (same mtime + size, unless `force=True`) are skipped. Version-stamp the index with model name + schema version and chunking params.
6. Return `{"status": "success", "data": {"path": ..., "files_indexed": N, "chunks_indexed": N, "files_skipped": N, "errors": [...], "db_path": ...}}`. `doc_index` also invalidates the cached search state on success.

### Search (`doc_search`)

1. **Parse** the lisp query string into an AST. Plain strings auto-wrapped as `(q "...")`.
2. **Evaluate** the AST against all chunks:
   - Pure lexical (no `q`): evaluate `r`/`k` predicates; return matching chunks sorted by file path + line number.
   - Pure vector (only `q`): embed query, compute cosine similarity against all chunks, return top-k above threshold.
   - Hybrid (both `q` and lexical ops): apply lexical filter first to produce candidate set, then re-rank candidates by average cosine score of all `q` nodes in the expression. If no lexical candidates exist, fall back to pure vector search over all chunks.
3. **Dedup** results by containment: a chunk whose line range is fully contained in an already-kept chunk of the same path is dropped.
4. **Truncate** each returned chunk text to `snippet_chars` (default 600) with an ellipsis marker; report `full_length` and `truncated: true`. Include `below_threshold: true` flag for hits under `min_score`. `match_spans` (char offsets) are computed for lexical hits.
5. Clamp `top_k` to `[1, max_results]`. `doc_search` fetches all results internally, caches them, and returns the first page. Return standard result shape with `mode`, `query`, `total_found`, `returned`, `index_stale`, `search_id`, `has_more`, `current_range`, and `results` array. `max_chars` (snippet length override) is clamped to `[100, LAMA_OLE_DOCSEARCH_MAX_CHUNK_CHARS]`.

### Pagination (`doc_search_next_results`)

- Module globals hold the last search: `_cached_query`, `_cached_results`, `_cached_cursor`, `_cached_index`, `_cached_search_id`.
- `doc_search` resets cache and returns first page (up to `top_k` results).
- `doc_search_next_results(maxcount)` continues; max 10 per call. Errors if no active search or `search_id` mismatch.
- A new `doc_search` or `doc_index` invalidates the cached result list. Pagination is only valid for the most recent search (inherent limitation of the cached-session pattern).

### Staleness Detection (`doc_index_status`)

Compares the newest indexed file mtime against index `last_indexed_at`. If newer source files exist, includes `index_stale: true` in status output with a hint to run `doc_index(path)`. No auto-reindex (too expensive, unpredictable latency).

## Safety and Path Validation

- **Path validation**: Every `path` argument is validated via `tools_security.validate_path`. Relative paths only unless a basepath is registered for tests.
- **Binary detection**: Files with null bytes or high entropy (via `EntropyChecker`) are skipped and counted in status output, never indexed as text.
- **Context-window protection**: Chunk size capped at 2000 chars (index time). Returned snippets truncated to 600 chars (search time). `top_k`/`maxcount` clamped to `max_results` (default 20) and to 10 per page for follow-up tool.
- **Regex safety**: Regex applied per-chunk (input bounded by `chunk_chars`, default 2000), limiting blast radius. Coarse wall-clock timeout guard via threading for pathological patterns; documented limitation on Python 3.9 (no native `re.timeout`).
- **No `eval()`**: The lisp parser is a hand-written tokenizer + recursive descent parser — no use of Python's `eval` or `exec`.
- **SQLite concurrency**: WAL mode with busy timeout mitigates race conditions between indexing and searching.

## One-Shot CLI Flow

When the `doc_search_tools` toolset is loaded (via `LAMA_OLE_TOOL=tools.doc_search_tools` or `--tool tools.doc_search_tools`), three static CLI flags become available:

| Flag | Type | Description |
|---|---|---|
| `--docscan PATH` | string | Index documents at `PATH` and exit. Prints status JSON to stdout, exits 0 on success / 1 on error. Requires backend (embedding needed). |
| `--docsearch QUERY` | string | Run a one-shot search using the lisp query or plain string and exit. Prints compact JSON results to stdout, exits 0 on success (including empty results) / 1 on error. Backend required for vector/hybrid modes. |
| `--docdb PATH` | string | Override the DB root directory for this invocation only. Falls back to env var `LAMA_OLE_DOCSEARCH_DB`, then default `./docsearch`. |

### Flow Rules

- If both `--docscan` and `--docsearch` are given: index first, then search in the same run.
- If only `--docscan`: index and print status JSON, exit 0.
- If only `--docsearch`: search and print results JSON, exit 0.
- If neither flag is given: normal lama_ole chat mode proceeds as usual.
- **No autoload**: If the toolset is not loaded, these flags are unrecognized by argparse. Error message directs user to add `--tool tools.doc_search_tools` (or set `LAMA_OLE_TOOL=tools.doc_search_tools`). No implicit module loading occurs.
- One-shot mode runs after argument parsing and tool loading but before the chat loop. Backend is created; if backend creation fails, error JSON printed and process exits 1.
- `--docdb` overrides the DB root for both scan and search in the same invocation.

### Flow Rules

- If both `--docscan` and `--docsearch` are given: index first, then search in the same run (convenient for "index then ask").
- If only `--docscan`: index and print status JSON, exit 0.
- If only `--docsearch`: search and print results JSON, exit 0.
- If neither flag is given: normal lama_ole chat mode proceeds as usual.
- **No autoload**: If the toolset is not loaded, these flags are unrecognized by argparse. Error message directs user to add `--tool tools.doc_search_tools` (or set `LAMA_OLE_TOOL=tools.doc_search_tools`). No implicit module loading occurs.
- One-shot mode runs after argument parsing and tool loading but before the chat loop. Backend is created; if backend creation fails, error JSON printed and process exits 1.

## Implementation Status

Based on `006_plan.md` and `007_summary.md`, the implementation is **partially complete**:

### Completed (✓)

| Component | Files | Status |
|---|---|---|
| **Backend extensions** | `backends/base.py`, `ollama_backend.py`, `openai_compat_backend.py`, `llamacpp_backend.py`, `groq_backend.py`, `echo_backend.py`, `eliza_backend.py` | `embed(texts, model)` abstract method added to `LlmBackend`; all backends implement or raise appropriately. Pseudo-embedders in echo/eliza for deterministic testing. |
| **Engine package** | `doc_search/__init__.py`, `chunker.py`, `store.py`, `lisp.py`, `search.py` | All core modules created and written. Chunking, SQLite storage with per-model DB dirs, lisp parser, search + index engine all implemented. |
| **Toolset** | `tools/doc_search_tools.py` | 7 tools (`doc_index`, `doc_search`, `doc_search_next_results`, `doc_search_status`, `doc_get_chunk`, `doc_index_status`, `doc_index_clear`) with correct signatures, `__tool_env__` (17 env vars), and `__tool_params__` (3 CLI flags). Module marked `__tool_readonly__ = True`. |
| **Parameter registration** | `tool_base/registry.py` | Modified to collect `__tool_params__` from loaded tool modules and register into `parameters.PARAMETERS` with deduplication. No circular imports. |
| **One-shot mode** | `lama_ole.py` | Added one-shot handling for `--docsearch`, `--docscan`, `--docdb`. Backend created before execution; JSON output to stdout; exit 0/1 codes. |
| **End-to-end testing** | — | Tested with `echo` backend (deterministic pseudo-embedder): indexing, vector search, regex filtering, status reporting, and staleness detection all verified. |

### Remaining Work

| Item | Priority | Description |
|---|---|---|
| Full test suite | Medium | Unit tests for chunker, store, lisp parser (deterministic fake embeddings); integration tests gated by `LAMA_OLE_TEST_DOCSEARCH=1` for real backends. |
| Update `001_proposal.md` | Low | Marked as stale per F28; superseded by this consolidated spec (`009_proposal.md`). No code changes needed — documentation update only. |

### Verified Against Q&A Trail

All decisions from 002_QA, 003_QA (F1–F12), and 004_QA (F13–F28) are reflected in this specification. The primary sources for each decision are traced in `./docs/008_table.md`.

---
*This document is the single source of truth for the Doc Search Toolset blueprint, superseding all prior proposal and Q&A documents for implementation purposes.*
