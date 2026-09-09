# 004: Ambiguities, Contradictions, and Open Questions

These issues must be resolved before or during implementation. Each is classified as:
- **BLOCKER**: Cannot proceed without a decision
- **DECISION**: Requires a design choice that affects the plan
- **NICE-TO-KNOW**: Can be resolved during implementation

---

## 1. Thinking/Reasoning Support Across Backends

### Issue
The engine heavily uses Ollama's `msg.thinking` field for the thinking process display (`-t` / `--thoughtlog`). Not all backends support this:
- **Ollama**: Native `msg.thinking` field
- **OpenAI o1/o3**: `reasoning_content` field in API response — only for specific models
- **llama.cpp**: Some quantizations support it via special tokens, but not all
- **Echo/Eliza**: No thinking by design # implement a fake thinking block which just says "*thinking"

### Questions
1. Should `--thinking` be silently ignored for backends that don't support it, or should it print a warning? # print a warning
2. For OpenAI o1/o3, should we map `reasoning_content` → `ChatChunk.thinking`? # yes

### Recommendation
- **BLOCKER**: Define behavior. Recommend: `--thinking` silently becomes a no-op for backends where `supports_thinking` is `False`. No warning (too noisy). The `/stats` output can indicate "thinking: not supported by backend". # Follow the recommendation and provide a warning on model selection (via chat or commandline).

---

## 2. `keep_alive` Parameter

### Issue
`keep_alive` is an Ollama-specific parameter controlling how long a model stays loaded after the last request. No other backend has this concept.

### Questions
1. Should the `LlmBackend.chat()` signature include `keep_alive` at all, or should it be `**kwargs` that backends selectively consume?
2. Should it be an Ollama-only option passed via `options` dict?

### Recommendation
- **DECISION**: Recommend `keep_alive` stays as an explicit parameter but is typed `Optional[Any]`. Ollama backend uses it; others ignore it. This keeps the common case (Ollama) clean. The alternative (buried in `options`) is less discoverable. # Follow this recommendation and print a warning when it has no effect.

---

## 3. Model Transfer

### Issue
Model transfer (`--transfer SOURCE DEST`) is Ollama-specific: it reads Ollama's local manifest/blobs and uploads via Ollama's `create_blob` / `create` API. This cannot work with other backends.

The task says backends "also ollama will be a separate backend" — but transfer is inherently an Ollama operation.

### Questions
1. Should `--transfer` implicitly force the Ollama backend regardless of `--backend`?
2. Should `--transfer` be hidden/removed when a non-Ollama backend is selected?
3. Should each backend implement its own `transfer_model()` method?

### Recommendation
- **DECISION**: `--transfer` is inherently Ollama-specific. Recommend: `--transfer` works regardless of `--backend` setting (it operates on Ollama instances directly, not through the backend abstraction). Document clearly that transfer is an Ollama-only feature. The `LlmBackend.transfer_model()` method exists in the interface but raises `NotImplementedError` by default. # Follow the recommendation.

---

## 4. API Key Scope

### Issue
The task says "optional possibility to apply an API Key on all backends." But:
- Ollama never needs an API key
- llama.cpp server usually doesn't need one
- OpenAI-compatible servers may need one (Bearer token)
- Echo/Eliza don't need one

### Questions
1. Is the API key global (one `--api-key` for all backends) or per-backend (e.g., `--ollama-api-key`, `--openai-api-key`)?
2. Should the key be stored in config for reuse?

### Recommendation
- **DECISION**: Recommend a single global `--api-key` / `LAMA_OLE_API_KEY`. Each backend receives it via the factory; backends that don't need it simply ignore it. This is the simplest approach and matches the task description. If per-backend keys are needed later, it's a straightforward extension. # Follow the recommendation.

---

## 5. Context Window Detection

### Issue
`chat.py`'s `_resolve_ctx_max()` uses `client.ps()` and `client.show()` (Ollama-specific) to determine the model's context window size. The context meter relies on this.

### Questions
1. Should `LlmBackend` provide a `get_context_window(model)` method, or should `_resolve_ctx_max` be refactored to use `show_model()`?
2. For backends that can't determine ctx window (OpenAI API), what should the meter show?

### Recommendation
- **DECISION**: Add `show_model()` to the abstract interface (already planned). `_resolve_ctx_max()` uses `backend.show_model()` instead of `client.ps()` / `client.show()`. For backends where context length is unknown, the meter shows absolute token counts without percentage (already the fallback behavior when `ctx_max` is `None`). # Follow the recommendation.

---

## 6. Tool Format Differences

### Issue
Different backends expect different tool formats:
- **Ollama**: `OllamaTool` dataclass with typed nested structure
- **OpenAI / llama.cpp**: JSON Schema in `functions` / `tools` parameter
- **Echo/Eliza**: Can use either

The current code uses `to_ollama_tools()` which converts to Ollama's typed format. The engine passes this as `tools=` to `client.chat()`.

### Questions
1. Should the normalized tool format be OpenAI-style (JSON dict) since it's the most widely supported?
2. Should `convert_tools()` return `List[Dict]` (universal) or `List[Any]` (backend-typed)?

### Recommendation
- **DECISION**: Normalize to `List[Dict]` in OpenAI function-calling format. This is the de facto standard. Ollama's Python library actually accepts this format too (it converts internally). This eliminates the need for `OllamaTool` type entirely in the engine. # CRUCIAL: normalize it but convert it in the backend abstraction to ollamas native format. Don't let ollama do this.

---

## 7. Message History Compatibility

### Issue
The chat history stored in `ChatState.messages` contains Ollama-specific fields like `"thinking"` in assistant messages (see `engine.py:477`). When switching backends, the message history may contain fields that the new backend doesn't understand.

### Questions
1. When sending messages to a new backend, should we strip Ollama-specific fields?
2. Should the history be stored in a backend-neutral format?
3. Can a user switch from an Ollama session (with thinking blocks) to an OpenAI backend mid-conversation?

### Recommendation
- **NICE-TO-KNOW**: The engine already filters messages before sending: `messages=[{k: v for k, v in m.items() if k != "thinking"} for m in messages]` (engine.py:358). So `"thinking"` is already stripped on send. Tool call format in messages is already normalized to `{"function": {"name": ..., "arguments": ...}}` which is OpenAI-compatible. Switching backends mid-conversation should work without special handling.

---

## 8. `/backend` Switch and Model Compatibility

### Issue
When switching from Ollama to Echo backend via `/backend echo`, the current model name (e.g., `gemma2:2b`) is meaningless to the Echo backend.

### Questions
1. Should `/backend echo` automatically reset the model to a sensible default?
2. Should it prompt the user to enter a model name? # no
3. Should the backend interface include `default_model()`? # not a default_model but a last_used_model which defaults to None

### Recommendation
- **DECISION**: Add `default_model` property to `LlmBackend`. When switching backends, if the current model is not valid for the new backend, auto-switch to `backend.default_model` and print a notice. For Echo/Eliza, `default_model` returns `"mock"`. For Ollama, returns the current model or first available. # The backend should remember which was the latest used model. The switch to none in modelfree backends is ok. When a backend is selected and it has no last_used_model then the current model keeps selected.

---

## 9. Thread Safety of Backend Switching

### Issue
The `/backend` command switches the backend mid-REPL. If a generation is in progress (unlikely in REPL but possible with hotkeys), this could cause a race condition.

### Questions
1. Should backend switching be deferred to the next turn boundary?
2. Is the existing hotkey listener (for mode switching) a concern?

### Recommendation
- **NICE-TO-KNOW**: The REPL is single-threaded for user input. Hotkey listener only sets a flag; it doesn't call the backend. Backend switching in `_handle_command()` is safe because it only modifies `state.client` before the next `run_with_tools()` call. No special handling needed. # ok

---

## 10. `--list` and `--ps` Behavior

### Issue
`lama_ole.py` currently calls `client.list()` and `client.ps()` as Ollama-specific operations. With backends, these should use the backend's `list_models()` and `list_running()`.

But: `--list` and `--ps` are standalone operations that exit after printing. Should they use the backend abstraction or remain Ollama-specific?

### Questions
1. Should `lama_ole --list --backend openai_compat` list models from the OpenAI endpoint?
2. Should `--ps` work for all backends?

### Recommendation
- **DECISION**: Yes, both should use the backend. `--list` calls `backend.list_models()`, `--ps` calls `backend.list_running()`. Backends that don't support listing (Echo) return an empty list or a notice. # ok

---

## 11. `--host` Semantics Per Backend

### Issue
`--host` currently means the Ollama server URL. With multiple backends, `--host` is ambiguous:
- For Ollama: `http://localhost:11434`
- For llama.cpp: `http://localhost:8080`
- For OpenAI: `https://api.openai.com`

### Questions
1. Should `--host` be the universal endpoint for all backends?
2. Should there be per-backend host options (`--ollama-host`, `--llamacpp-host`)?

### Recommendation
- **DECISION**: `--host` becomes the universal endpoint, defaulting to the backend's default URL. The factory passes `host` to the backend constructor. Each backend has its own default (Ollama: `localhost:11434`, llama.cpp: `localhost:8080`, OpenAI: `https://api.openai.com`). This means the user only needs `--host` and `--backend`, which is clean. # ok

### I made some comments. If further ambiguities and contradictions come up though my decisions comment it in 004_ambiguities_and_contradictions_A.md
