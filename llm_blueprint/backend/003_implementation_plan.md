# 003: Implementation Plan — Step-by-Step

## Phase 0: Preparation (no behavioral changes)

### Step 0.1 — Create `backends/` package skeleton

Create the `backends/` directory with:
- `__init__.py` — re-exports `LlmBackend`, `ChatChunk`, `ModelInfo`, `RunningModel`, `create_backend`
- `base.py` — `LlmBackend` ABC, `ChatChunk`, `ModelInfo`, `RunningModel` dataclasses
- `registry.py` — `BACKEND_REGISTRY` dict, `DEFAULT_BACKEND`, `SUPPORTED_BACKENDS`
- `factory.py` — `create_backend()` function
- `_compat.py` — lazy import helpers (`_try_import(module, name)`)

### Step 0.2 — Add new CLI parameters

In `parameters.py`, add `ParameterSpec` entries for:
- `--backend` / `LAMA_OLE_BACKEND` (default `"ollama"`, choices from `SUPPORTED_BACKENDS`)
- `--api-key` / `LAMA_OLE_API_KEY` (default `None`)

### Step 0.3 — Generalize config

In `tool_base/config.py`, add `set_backend_config()`, `get_backend_host()`, `get_api_key()`. Keep `set_ollama_host()` / `get_ollama_host()` as backward-compatible aliases.

**Verification**: Run `python3 tests/run_all_tests.py` — must stay green.

---

## Phase 1: Ollama Backend (zero-regression)

### Step 1.1 — Implement `OllamaBackend`

Create `backends/ollama_backend.py`:
- `__init__`: lazy `from ollama import Client`, store host
- `chat()`: call `self._client.chat()`, iterate native chunks, yield `ChatChunk`
- `convert_tools()`: move `to_ollama_tools()` logic here
- `list_models()`, `list_running()`, `show_model()`, `stop_model()`: wrap `client.list()`, `client.ps()`, `client.show()`, `client.generate()`
- `close()`: no-op (Ollama client has no close)

### Step 1.2 — Refactor `engine.py` to use `ChatChunk`

Replace direct Ollama chunk field access with `ChatChunk` fields:
- `chunk.message.content` → `chunk.content`
- `chunk.message.thinking` → `chunk.thinking`
- `chunk.message.tool_calls` → `chunk.tool_calls`
- `chunk.prompt_eval_count` → `chunk.prompt_eval_count`
- etc.

Remove `from ollama import Tool as OllamaTool` from engine.py. Move to `OllamaBackend`.

Replace `to_ollama_tools()` at module level with `backend.convert_tools()` call.

### Step 1.3 — Refactor `run_with_tools()` signature

```python
# OLD:
def run_with_tools(client, model, messages, loaded_tools, ollama_tools, ...):

# NEW:
def run_with_tools(client, model, messages, loaded_tools, backend_tools, ...):
```

Update all callers:
- `lama_ole.py` (lines ~563, 611, 660)
- `chat.py` (lines ~1124, 1398)

### Step 1.4 — Refactor `ChatState`

Rename `ollama_tools` → `backend_tools`, `refresh_ollama_tools()` → `refresh_backend_tools()`.

Update all references in `chat.py` (~20 occurrences).

### Step 1.5 — Wire up factory in `lama_ole.py`

Replace `Client(host=host_url)` with `create_backend("ollama", host=host_url)`.

Pass the backend to `ChatState` and `run_with_tools()`.

**Verification**: Full test suite must pass. Ollama behavior must be identical.

---

## Phase 2: Testing Backends (Eliza + Echo)

### Step 2.1 — Implement `EchoMockBackend`

Create `backends/echo_backend.py`:
- `chat()`: echoes user content back as assistant; detects tool-call triggers (e.g., message containing `"call_tool:"`) and yields tool_call chunks
- `convert_tools()`: returns tools as-is (OpenAI format)
- `list_models()`: returns a fake model list
- `supports_thinking`: `False`

### Step 2.2 — Implement `ElizaBackend`

Create `backends/eliza_backend.py`:
- `__init__`: accepts `script: List[Dict]` — sequence of `{"content": "...", "tool_calls": [...]}` responses
- `chat()`: pops from script queue; yields matching `ChatChunk`
- `convert_tools()`: OpenAI format
- `list_models()`: returns fake list
- `supports_thinking`: `False`

### Step 2.3 — Write tests for echo and Eliza backends

Create `tests/test_echo_backend.py` and `tests/test_eliza_backend.py`:
- Test chat streaming produces correct chunks
- Test tool call simulation
- Test `convert_tools()` format
- Test `list_models()`, `stop_model()` etc.

**Verification**: New tests pass. Existing tests still pass.

---

## Phase 3: External Backends (llama.cpp + OpenAI)

### Step 3.1 — Implement `OpenAICompatBackend`

Create `backends/openai_compat_backend.py`:
- Uses stdlib `urllib.request` (no new dependencies)
- `chat()`: POST `/v1/chat/completions` with `stream: true`, parse SSE lines
- `convert_tools()`: convert internal `Tool` to OpenAI function-calling schema
- `list_models()`: GET `/v1/models`
- `show_model()`: limited (OpenAI API doesn't expose ctx window)
- `supports_thinking`: `True` for o1/o3 models (via `reasoning_content`), `False` otherwise
- API key sent as `Authorization: Bearer <key>` header

### Step 3.2 — Implement `LlamaCppBackend`

Create `backends/llamacpp_backend.py`:
- Uses stdlib `urllib.request`
- Primary: `/v1/chat/completions` (OpenAI-compatible mode)
- Fallback: `/completion` (native llama.cpp)
- `convert_tools()`: OpenAI format (llama.cpp accepts it in chat mode)
- `list_models()`: limited (llama.cpp doesn't list models; return loaded model name)
- `show_model()`: GET `/v1/models` with details if available

### Step 3.3 — Write integration tests (opt-in)

Create `tests_llamacpp/` and `tests_openai_compat/` with:
- Opt-in env-var guards (`LAMA_OLE_LLAMACPP_TEST=1`, `LAMA_OLE_OPENAI_COMPAT_TEST=1`)
- Tests that require a running server — skip by default

**Verification**: New tests pass (skipped when servers unavailable). Existing tests still pass.

---

## Phase 4: REPL Integration

### Step 4.1 — Add `/backend` command to chat REPL

In `chat.py`:
- Add `"/backend"` to `_COMMANDS` list
- Add handler in `_handle_command()`:
  - No arg: show current backend + available backends
  - With arg: create new backend, swap `state.client`, prompt for model if needed, call `refresh_backend_tools()`

### Step 4.2 — Update `_show_help()`

Add `/backend` to the help output.

### Step 4.3 — Update `ChatState` display

Show backend name in mode prompt or stats output.

**Verification**: Full test suite passes. Manual testing: `/backend echo`, `/backend ollama`.

---

## Phase 5: Encapsulation Testing

### Step 5.1 — Write import-without-ollama test

Create `tests/test_backend_encapsulation.py`:
- Temporarily remove `ollama` from `sys.modules` and `sys.path`
- Verify `from backends import create_backend` works
- Verify `from backends.factory import create_backend` works
- Verify `create_backend("echo", ...)` works
- Verify `create_backend("ollama", ...)` raises a clear error
- Restore `sys.modules` after test

### Step 5.2 — Update `run_all_tests.py`

Ensure `tests_<backendname>/` directories are discovered by the test runner.

**Verification**: Test passes. `ollama` import failure is handled gracefully.

---

## Phase 6: Documentation & Cleanup

### Step 6.1 — Update `README.md`

- Add `--backend` and `--api-key` to CLI reference table
- Add backend architecture section
- Update model transfer documentation (Ollama-only)

### Step 6.2 — Update `AGENTS.md`

- Add `backends/` to directory layout
- Add backend architecture to key patterns

### Step 6.3 — Rename remaining `ollama` references

- `tool_base/__init__.py` exports: keep `set_ollama_host` / `get_ollama_host` as deprecated aliases
- `tools/media_understanding_tools.py`: migrate to `get_backend_host()` (or keep using `get_ollama_host()` as alias)

**Verification**: Full test suite green. No hardcoded `ollama` references in core engine code.

---

## Execution Order Summary

| Phase | Steps | Dependencies |
|-------|-------|-------------|
| 0 | 0.1, 0.2, 0.3 | None |
| 1 | 1.1 → 1.2 → 1.3 → 1.4 → 1.5 | Phase 0 |
| 2 | 2.1, 2.2 (parallel), 2.3 | Phase 1 |
| 3 | 3.1, 3.2 (parallel), 3.3 | Phase 1 |
| 4 | 4.1, 4.2, 4.3 | Phase 1 |
| 5 | 5.1, 5.2 | Phase 1 |
| 6 | 6.1, 6.2, 6.3 | Phase 4 |

**Total estimated effort**: 6 phases, ~25 discrete steps.

Each phase ends with a green test suite. Phase 1 is the critical path — it must be completed before anything else can proceed.
