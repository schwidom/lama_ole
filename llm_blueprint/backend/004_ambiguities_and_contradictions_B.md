# 004B: Contradictions Introduced by A-Decisions

These contradictions arose from applying the decisions in `004A`. They must be resolved before implementation proceeds.

---

## 1. `last_used_model` Update Timing

### Contradiction

The decision chose (d): `ChatState` stores `last_used_model_by_backend: Dict[str, str]`.

The decision also says: "The backend should remember which was the latest used model."

But when does the dict get updated?

- When the user does `/model gemma2:2b`? → Set `last_used_model_by_backend["ollama"] = "gemma2:2b"`
- After each successful `chat()` call? → The model used in that call is stored
- When switching backends via `/backend`? → Store current model in `last_used_model_by_backend[current_backend]` before switching

All three seem needed, but the interaction is subtle:

1. User does `/model gemma2:2b` → `last_used_model_by_backend["ollama"] = "gemma2:2b"`
2. User does `/backend echo` → model `gemma2:2b` stays (no `last_used_model` for echo)
3. User does `/model echo_model` → `last_used_model_by_backend["echo"] = "echo_model"`
4. User does `/backend ollama` → `last_used_model_by_backend["ollama"]` is `"gemma2:2b"` → model switches back to `gemma2:2b`

This works. But what if the user never did `/model` and just used the default? Is the default stored in `last_used_model_by_backend`?

### Resolution Needed

- (a) Store the model on every `/model` command and on every successful `chat()` call?
- (b) Only store on `/model` command? (Default model is implicit, not stored)
- (c) Store on backend switch (snapshot current model into the dict)? # This one.

---

## 2. Thinking Warning Scope — Per-Turn or Per-Session?

### Contradiction

The decision chose (c): "Detected at chat time — if the first chunk has no thinking, disable thinking display with a one-time warning."

"One-time" is ambiguous:
- **Per-turn**: Warning fires once per `chat()` call where thinking is missing. User sends 3 messages with a non-thinking model → 3 warnings.
- **Per-session**: Warning fires once per session. After the first warning, subsequent turns silently skip thinking.
- **Per-model**: Warning fires once per model. If user switches models and comes back, warning fires again.

### Resolution Needed

- (a) Per-turn (warn every time thinking is expected but missing)?
- (b) Per-session (warn once, then silent for rest of session)?
- (c) Per-model (warn once per unique model, re-warn if model changes)? # this one, and maybe also per backend if the backend is not able to think

---

## 3. `--host` Port Extraction — Parsing Partial URLs

### Contradiction

The decision chose (a): "`--host` default becomes `None`. Each backend uses its own default when `host is None`. When only the host is given without port, the port number is used which is defined by the backend."

This implies URL normalization logic:

| Input | Backend | Expected Result |
|-------|---------|----------------|
| `None` | `ollama` | `http://localhost:11434` |
| `None` | `llamacpp` | `http://localhost:8080` |
| `myserver` | `ollama` | `http://myserver:11434` |
| `myserver` | `llamacpp` | `http://myserver:8080` |
| `myserver:9999` | `ollama` | `http://myserver:9999` |
| `http://myserver` | `ollama` | `http://myserver:11434` |
| `http://myserver:9999` | `ollama` | `http://myserver:9999` |

The logic:
1. If `None` → use backend default
2. If no scheme → prepend `http://`
3. If no port → append backend's default port
4. If scheme + port → use as-is

### Resolution Needed

Is this normalization done in:
- (a) The factory (normalize before passing to backend)?
- (b) Each backend's `__init__`?
- (c) A shared utility function in `backends/_compat.py`? # this one

---

## 4. `keep_alive` Warning — Does `/backend` Switch Re-Trigger It?

### Contradiction

The decision chose (a): "Once, when the backend is created with `keep_alive` set and the backend doesn't support it."

This fires at startup in `lama_ole.py`. But what about REPL backend switches?

Scenario:
1. User starts with `--keep_alive 300 --backend ollama` → no warning (Ollama supports it)
2. User does `/backend echo` → `keep_alive` is still set in `ChatState` options
3. Should a warning fire? The decision says "once, when the backend is created" — the echo backend is newly created, but the `keep_alive` was set at startup, not at echo creation.

### Resolution Needed

- (a) Warning fires only at startup (CLI level), never in REPL?
- (b) Warning fires at startup AND on `/backend` switch if new backend doesn't support `keep_alive`? # this one
- (c) Warning fires at startup; `/backend` switch prints a different info message ("Note: keep_alive is not supported by this backend")?

---

## 5. `convert_tools()` Timing — When Does Conversion Happen?

### Contradiction

The decision chose (b): `convert_tools()` returns `List[Dict]` (OpenAI format). The Ollama backend converts to native format internally in `chat()`.

But currently, `to_ollama_tools()` is called in `refresh_ollama_tools()` which runs after every `/tools load` / `/tools unload`. The result is stored in `ChatState.ollama_tools` (now `backend_tools`).

With the new design:
1. `convert_tools()` returns `List[Dict]` (OpenAI format)
2. This is stored in `ChatState.backend_tools`
3. `backend.chat(tools=backend_tools)` receives `List[Dict]`
4. Inside `chat()`, the Ollama backend converts `List[Dict]` → `List[OllamaTool]`

This means the conversion from OpenAI format → Ollama format happens on **every turn**, not once at tool-load time. Is this acceptable performance-wise?

### Resolution Needed

- (a) Convert on every turn (simple, slight overhead per turn)? # this one
- (b) Cache the native conversion in the backend (invalidate when tools change)?
- (c) `convert_tools()` returns native format, engine stores native format, `chat()` receives native format? (This contradicts choice (b))

---

## 6. `--host` Default `None` and Backward-Compatible `get_ollama_host()`

### Contradiction

`tool_base/config.py` has `get_ollama_host()` which returns a string. `tools/media_understanding_tools.py` calls `get_ollama_host()` to get the vision model endpoint.

If `--host` defaults to `None` and the backend normalizes it, `set_ollama_host()` / `get_ollama_host()` needs to receive the normalized URL. But at config-set time, the backend might not be known yet (config is set before backend creation in `lama_ole.py`).

Current flow in `lama_ole.py`:
```python
host_url = args.host  # could be None now
# ... normalize ...
set_ollama_host(host_url)
# ... later ...
client = create_backend(args.backend, host=host_url, ...)
```

If `args.host` is `None`, `set_ollama_host(None)` would store `None`, and `get_ollama_host()` would return `None` — breaking media tools.

### Resolution Needed

- (a) Normalize the host URL before calling `set_ollama_host()`, using the backend's default port if `--host` is `None`?
- (b) Deprecate `set_ollama_host()` / `get_ollama_host()` and migrate media tools to `get_backend_host()`? 
- (c) `get_ollama_host()` returns the backend's normalized host, set after backend creation?

Currently the media tools communicate directly over an ollama endpoint and not over the given backends. Currently the user can use the LAMA_OLE_VISION_HOST variable to define the ollama host which has to be used for media understanding. We should introduce the additional variable LAMA_OLE_VISION_BACKEND which defines the backend which is to use. So we should deprecate set_ollama_host / get_ollama_host completely. 

### I made some comments. If further ambiguities and contradictions come up though my decisions or if I missed smoething comment it in 004_ambiguities_and_contradictions_C.md


