# Implementation Plan: `--load` and `--stats` Parameters

## 1. Overview

This plan describes the implementation of two new CLI parameters for `lama_ole`:

- **`--stats <path>`** (renamed from `--load-info`): Prints statistical information about a session file and exits. Works standalone (no `--chat` required).
- **`--load <path>`**: Loads a session file in chat mode. Overrides `--resume`. Requires explicit `--chat`.

An environment variable `LAMA_OLE_LOAD` (string) provides the same functionality as `--load` without requiring a CLI flag.

---

## 2. Resolved Specifications

### 2.1 `--stats` Parameter

| Aspect | Decision |
|--------|----------|
| **Name** | `--stats` (replaces `--load-info`) |
| **Requires `--chat`** | No — works standalone |
| **Requires `--load` or `--resume`** | Yes — exits with error if neither is set |
| **Target file** | File specified by `--load` (if set); otherwise file that `--resume` would load via `find_recent_session()` |
| **Both `--load` and `--resume` set** | Inspects `--load` file (overrides `--resume`) |
| **Output format** | Human-readable text, same as `/stats` REPL command |
| **Fields displayed** | Model, number of messages, message breakdown by role (user, assistant, tool calls, thinking, system — at message level), title, session ID, created/updated timestamps, mode, loaded tool modules, skill, system prompt presence, context usage stats, context compaction settings (informational only), cwd from session file, current working directory |
| **Malformed file** | Print partial info + warning |
| **Non-existent file** | Exit with error message to stderr, `sys.exit(1)` |
| **Invalid JSON** | Exit with error message to stderr, `sys.exit(1)` |
| **Empty file** | Exit with specific error "Error: the file is empty." to stderr, `sys.exit(1)` |
| **No messages** | Exit with specific error to stderr, `sys.exit(1)` |

### 2.2 `--load` Parameter

| Aspect | Decision |
|--------|----------|
| **Name** | `--load` (string parameter) |
| **Requires `--chat`** | Yes — exits with "Error: --load requires --chat" to stderr, `sys.exit(1)` if `--chat` not set |
| **Works in one-shot mode** | No |
| **Precedence** | `--load` CLI > `LAMA_OLE_LOAD` env > `lama_ole.env` config > `--resume` > `LAMA_OLE_RESUME` |
| **Both `--load` and `--resume` set** | `--load` overrides `--resume`; warning to stderr: "Warning: --load overrides --resume; --resume is ignored." |
| **File validation** | Level 1: valid JSON, regular file, has at least `messages` key |
| **Minimum valid keys** | `messages` is sufficient; `model` is optional |
| **Session ID handling** | If loaded file has `session_id`: prompt user to preserve or create new (default: new, also shows title). If no `session_id`: create new one. |
| **Model mismatch** | Prompt when loaded file has `model` key differing from `--model`. If `--model` not set: exit(1) with error. On abort: `sys.exit(0)`. |
| **Archiving current session** | No archiving at startup (session is not yet used) |
| **CWD handling** | `cwd` from loaded file is IGNORED. Current working directory always used for future autosave operations |
| **Tool restoration** | Session tools are NOT loaded. Only `--tool` CLI flags and `/tools` REPL commands matter |
| **`ctx_*` settings** | `ctx_compact`, `ctx_compact_threshold`, `ctx_compact_model` from loaded file are NOT applied to runtime. Kept in session file for informational purposes only |
| **Entropy check** | No |
| **Symlink validation** | No |
| **Cross-backend files** | Yes, works with session files from any backend |

### 2.3 `LAMA_OLE_LOAD` Environment Variable

| Aspect | Decision |
|--------|----------|
| **Type** | String (file path) |
| **Same behavior as** | `--load` |
| **Validation timing** | Runtime (not at startup) |
| **Config file support** | Yes, via `lama_ole.env` |
| **Precedence** | Below `--load`, above `--resume` |

### 2.4 `/load` REPL Command Extension

| Aspect | Decision |
|--------|----------|
| **Model mismatch prompt** | Yes, triggers on every `/load` call |
| **On abort** | User lands in chat, program is NOT aborted |
| **Session ID prompt** | Yes, if loaded file has `session_id` (shows title) |

### 2.5 `--resume` — Unchanged

- `LAMA_OLE_RESUME` and `--resume` remain unchanged.
- Model mismatch prompt does NOT trigger for `--resume` (only for `--load` and `/load`).
- Session ID prompt does NOT trigger for `--resume`.

---

## 3. Files to Modify

### 3.1 `parameters.py`

Add two new `ParameterSpec` entries to the `PARAMETERS` list:

```python
ParameterSpec(
    name="load",
    flags=["--load"],
    env_var="LAMA_OLE_LOAD",
    default=None,
    help="Path to a session file to load (requires --chat)",
),
ParameterSpec(
    name="stats",
    flags=["--stats"],
    default=None,
    help="Print statistics about a session file (requires --load or --resume)",
),
```

### 3.2 `lama_ole.py`

#### 3.2.1 `build_parser()` — No changes needed
The parser is auto-generated from `PARAMETERS` in `parameters.py`.

#### 3.2.2 `process_inspection_flags()` — No changes needed
`--stats` is not an inspection flag.

#### 3.2.3 `main()` — Add new logic

The new logic flow in `main()`:

```
1. Load env files (existing)
2. Process inspection flags (existing)
3. Parse CLI args (existing)
4. Resolve env defaults (existing)

5. [NEW] Handle --stats early:
   a. If --stats is set:
      i. Determine target file:
         - If --load is set: use --load path
         - Else if --resume is True: call find_recent_session()
         - Else: print error, exit(1)
      ii. Validate file (Level 1: valid JSON, has 'messages' key)
      iii. Parse file, compute statistics
      iv. Print statistics in human-readable format
      v. exit(0)

6. [NEW] Handle --load / LAMA_OLE_LOAD:
   a. Determine effective load path:
      - If --load is set: use it
      - Else if LAMA_OLE_LOAD is set: use it
      - Else: None
   b. If effective load path is set AND --chat is NOT set:
      - Print "Error: --load requires --chat" to stderr
      - exit(1)
   c. If both effective load path AND --resume are set:
      - Print "Warning: --load overrides --resume; --resume is ignored." to stderr

7. [EXISTING] Backend creation, tools loading, etc.

8. [EXISTING] If --chat:
   a. Determine session source:
      - If effective load path is set:
        i. Validate file at runtime (Level 1)
        ii. Load file data
        iii. If data has 'model' and --model is set and they differ:
             - Call _prompt_model_choice()
             - If abort: exit(0)
             - If cli: update data["model"] = cli_model
        iv. If data has 'session_id':
             - Prompt user: preserve or create new (default: new, show title)
        v. Apply session data via apply_session() (without ctx_* settings)
        vi. Print load confirmation message
      - Else if --resume is True:
        i. Call find_recent_session()
        ii. If found: call _resume_session_into()
   b. Create/restore session_id
   c. Handle initial content
   d. Call run_chat()

9. [EXISTING] If not --chat:
   a. Run one-shot mode (unchanged)
```

#### 3.2.4 New functions to add

**`compute_stats(data: dict) -> str`**:
- Reads session file data
- Computes all statistics
- Returns human-readable formatted string
- Handles missing keys gracefully

**`resolve_load_path(args) -> Optional[str]`**:
- Returns effective load path from `--load` or `LAMA_OLE_LOAD`
- Validates file existence at runtime
- Returns None if not set

**`handle_stats(args) -> None`**:
- Determines target file (from `--load` or `--resume`)
- Validates file
- Computes and prints statistics
- Exits on error

### 3.3 `chat.py`

#### 3.3.1 Extend `_cmd_load()` for model mismatch prompt

```python
def _cmd_load(path: str, state: ChatState):
    # ... existing validation ...
    
    # NEW: Model mismatch prompt
    session_model = data.get("model")
    cli_model = state.config.model
    if cli_model and session_model and cli_model != session_model:
        choice = _prompt_model_choice(cli_model, session_model)
        if choice == "abort":
            print("Aborted. Returning to chat.", file=sys.stderr)
            return  # User stays in chat
        if choice == "cli":
            data["model"] = cli_model
    
    # NEW: Session ID prompt
    if data.get("session_id"):
        title = data.get("title") or "(untitled)"
        while True:
            ans = input(
                f"The loaded session has session_id '{data['session_id']}' "
                f"(title: '{title}').\n"
                "Preserve this session ID or create a new one? [p/n]: "
            ).strip().lower()
            if ans in ("p", "preserve", ""):
                break
            if ans in ("n", "new"):
                data["session_id"] = new_session_id()
                break
            print("Please answer p or n.", file=sys.stderr)
    
    # ... rest of existing apply_session ...
```

#### 3.3.2 Modify `apply_session()` to skip `ctx_*` settings

Add a parameter or conditional to skip restoring `ctx_compact`, `ctx_compact_threshold`, and `ctx_compact_model`:

```python
def apply_session(state: ChatState, data: dict, source: str = "session", skip_ctx_settings: bool = False) -> None:
    # ... existing code ...
    
    if "ctx_compact" in data and not skip_ctx_settings:
        state.ctx_compact = bool(data["ctx_compact"])
    if "ctx_compact_threshold" in data and not skip_ctx_settings:
        state.ctx_compact_threshold = sanitize_ctx_threshold(...)
    if "ctx_compact_model" in data and not skip_ctx_settings:
        state.ctx_compact_model = data["ctx_compact_model"]
    
    # ... rest of existing code ...
```

#### 3.3.3 Modify `serialize_session()` to NOT store `cwd`

```python
def serialize_session(state: ChatState, session_id: str = None, cwd: str = None, created_at: float = None) -> dict:
    # ... existing code ...
    
    # REMOVE or COMMENT OUT:
    # if cwd:
    #     data["cwd"] = cwd
    
    # ... rest of existing code ...
```

### 3.4 `LAMA_OLE_LOAD` Integration

In `_resolve_env_defaults()` or equivalent, add:

```python
def _resolve_env_defaults(args):
    # ... existing code ...
    
    # NEW: Resolve LAMA_OLE_LOAD
    if not args.load:
        load_from_env = os.environ.get("LAMA_OLE_LOAD")
        if not load_from_env:
            # Check config dict
            for key, value in config_dict.items():
                if key == "LAMA_OLE_LOAD" and value:
                    load_from_env = value
                    break
        if load_from_env:
            args.load = load_from_env
```

---

## 4. `--stats` Output Format

The output should mirror `/stats` REPL command. Based on the session file format:

```
Session Statistics
==================

Model: <model name>
Messages: <total count>

Message breakdown by role:
  user: <count>
  assistant: <count>
  tool_calls: <count>
  thinking: <count>
  tool: <count>
  system: <count>

Title: <title or "(untitled)">
Session ID: <session_id or "(none)">
Created: <formatted timestamp>
Updated: <formatted timestamp>
Mode: <build/plan>
Loaded tools: <comma-separated list or "(none)">
Skill: <skill name or "(none)">
System prompt: <set/none>
Context usage: <prompt_eval_count>/<eval_count> tokens (model: <model>)
Context compaction: <enabled/disabled> (threshold: <threshold>, model: <model>)
CWD (from session): <cwd or "(not stored)">
Current working directory: <os.getcwd()>
```

### Message breakdown details:
- **user**: Count of messages with `role == "user"`
- **assistant**: Count of messages with `role == "assistant"` and no `thinking` or `tool_calls`
- **tool_calls**: Count of messages with `role == "assistant"` that have `tool_calls`
- **thinking**: Count of messages with `role == "assistant"` that have `thinking` content (separate from output)
- **tool**: Count of messages with `role == "tool"`
- **system**: Count of messages with `role == "system"`

Note: `thinking` and `tool_calls` are counted separately from `assistant` output messages at the **message level**.

---

## 5. Implementation Order

### Phase 1: Foundation (`parameters.py`)
1. Add `--load` ParameterSpec to `PARAMETERS`
2. Add `--stats` ParameterSpec to `PARAMETERS`
3. Verify parser auto-generation works

### Phase 2: `--stats` Implementation (`lama_ole.py`)
4. Implement `compute_stats(data)` function
5. Implement `handle_stats(args)` function
6. Add `--stats` handling in `main()` (early, before chat initialization)
7. Test `--stats` with:
   - Valid session file
   - Non-existent file
   - Invalid JSON
   - Empty file
   - File with no messages
   - File with only `messages` key
   - Old format file (missing optional keys)

### Phase 3: `--load` Implementation (`lama_ole.py`)
8. Implement `resolve_load_path(args)` function
9. Add `--load` / `LAMA_OLE_LOAD` resolution in `main()`
10. Add `--load` requires `--chat` check
11. Add `--load` overrides `--resume` warning
12. Add `--load` file validation at runtime
13. Add `--load` session loading logic (model mismatch, session ID prompt)
14. Test `--load` with:
    - Valid session file + `--chat`
    - Without `--chat`
    - With `--resume` (warning check)
    - With `--model` mismatch
    - With `session_id` in file
    - Via `LAMA_OLE_LOAD` env var
    - Via `lama_ole.env` config

### Phase 4: `chat.py` Extensions
15. Modify `apply_session()` to accept `skip_ctx_settings` parameter
16. Extend `_cmd_load()` with model mismatch prompt
17. Extend `_cmd_load()` with session ID prompt
18. Modify `serialize_session()` to NOT store `cwd`

### Phase 5: Integration & Testing
19. Full integration test: `--load` with all features
20. Test `--stats --load <file>` combination
21. Test `--stats --resume` combination
22. Test `LAMA_OLE_LOAD` env var
23. Test `lama_ole.env` config support
24. Backwards compatibility test with old session files

---

## 6. Error Messages Reference

| Condition | Message | Output | Exit Code |
|-----------|---------|--------|-----------|
| `--stats` without `--load` or `--resume` | "Error: --stats requires --load or --resume." | stderr | 1 |
| `--load` without `--chat` | "Error: --load requires --chat" | stderr | 1 |
| `--load` / `--stats` file not found | "Error: file not found: <path>" | stderr | 1 |
| Invalid JSON | "Error: invalid JSON in <path>: <reason>" | stderr | 1 |
| Empty file | "Error: the file is empty." | stderr | 1 |
| No messages | "Error: the session has no messages." | stderr | 1 |
| `--load` + `--resume` both set | "Warning: --load overrides --resume; --resume is ignored." | stderr | 0 (warning only) |
| Model mismatch abort | (handled by `_prompt_model_choice`) | stderr | 0 |
| `--model` not set | "Error: model has to be set (parameter -m, --model)" | stderr | 1 |

---

## 7. Key Design Decisions Summary

1. **`--stats` is standalone** — works without `--chat`, inspects files directly.
2. **`--load` requires `--chat`** — explicit `--chat` flag is mandatory.
3. **`LAMA_OLE_LOAD` is a string** — same type as `--load`, not a boolean.
4. **`ctx_*` settings are informational only** — never applied to runtime.
5. **Session tools are not loaded** — only `--tool` CLI and `/tools` REPL matter.
6. **`cwd` is not stored in `/save` files** — always uses current working directory.
7. **Model mismatch prompt triggers for `--load` and `/load`** — not for `--resume`.
8. **Session ID prompt triggers for `--load` and `/load`** — not for `--resume`.
9. **`--load` and `--resume` can coexist** — `--load` wins with a warning.
10. **Validation is Level 1** — valid JSON, regular file, has `messages` key.
11. **`--stats` output mirrors `/stats`** — human-readable format.
12. **Abort on `/load` model mismatch** — returns to chat, does not exit.

---

## 8. Testing Checklist

- [ ] `--stats <valid_file>` — prints all fields correctly
- [ ] `--stats` without `--load` or `--resume` — error message
- [ ] `--stats --load <nonexistent>` — error message
- [ ] `--stats --load <invalid_json>` — error message
- [ ] `--stats --load <empty_file>` — error message
- [ ] `--stats --load <no_messages>` — error message
- [ ] `--stats --load <old_format>` — graceful handling
- [ ] `--stats --load <file_with_session_id>` — shows session ID
- [ ] `--stats --load <file>` + `--stats --resume` — uses `--load` file
- [ ] `--load <file>` without `--chat` — error message
- [ ] `--load <file>` with `--chat` — loads session
- [ ] `--load <file>` with `--resume` — warning shown, `--load` wins
- [ ] `--load <file>` with `--model` mismatch — prompt shown
- [ ] `--load <file>` with `session_id` — prompt shown
- [ ] `--load <file>` with `ctx_compact` — NOT applied
- [ ] `--load <file>` with `loaded_tool_modules` — NOT loaded
- [ ] `LAMA_OLE_LOAD=<file>` — same as `--load`
- [ ] `lama_ole.env` with `LAMA_OLE_LOAD` — same as `--load`
- [ ] `/load <file>` with model mismatch — prompt shown, abort returns to chat
- [ ] `/load <file>` with `session_id` — prompt shown
- [ ] `/save` does NOT store `cwd` in file
- [ ] Loaded session autosave uses current working directory
- [ ] Backwards compatibility with old session files
