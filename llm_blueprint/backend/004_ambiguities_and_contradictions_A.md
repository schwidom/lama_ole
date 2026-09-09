# 004A: Contradictions Introduced by Decisions

These contradictions arose from applying the decisions in `004_ambiguities_and_contradictions.md`. They must be resolved before implementation proceeds.

---

## 1. `supports_thinking` Is Per-Backend But Thinking Availability Is Per-Model

### Contradiction

The decision says:
- Echo/Eliza: "implement a fake thinking block which just says `*thinking*`"
- OpenAI o1/o3: map `reasoning_content` → `ChatChunk.thinking`
- Warning on model selection when thinking is not supported

But thinking support varies **per model within a backend**:
- `openai_compat` with `o1` → thinking works
- `openai_compat` with `gpt-4` → thinking does NOT work
- `llamacpp` with a thinking-capable quantization → works
- `llamacpp` with a standard quantization → does NOT work

If `supports_thinking` is a property of the backend class, it cannot reflect per-model capability. The warning "on model selection" would need to know the model, not just the backend.

### Resolution Needed

Should `supports_thinking` be:
- (a) A backend-level property (simpler, but imprecise)?
- (b) A method `supports_thinking(model: str) -> bool` that queries the backend?
- (c) Detected at chat time — if the first chunk has no thinking, disable thinking display with a one-time warning? # this one

---

## 2. `last_used_model` Lifetime — Instance vs. Factory Cache

### Contradiction

The decision says: "The backend should remember which was the latest used model."

But `create_backend()` creates a **new instance** each time. When the user does `/backend ollama` → uses `gemma2:2b` → `/backend echo` → `/backend ollama`, a fresh `OllamaBackend` is created. The previous `last_used_model` is gone.

### Resolution Needed

Where is `last_used_model` persisted?

- (a) On the backend instance (lost on re-creation)?
- (b) On `ChatState` (survives backend switches)?
- (c) Factory caches backend instances (never re-created)?
- (d) `ChatState` stores `last_used_model_by_backend: Dict[str, str]`? # this one

---

## 3. `keep_alive` Warning — When Does It Fire?

### Contradiction

The decision says: "print a warning when it has no effect."

But `keep_alive` is passed on every `chat()` call. If the warning fires inside `chat()`, it would print **every turn** — extremely noisy.

### Resolution Needed

When should the warning print?

- (a) Once, when the backend is created with `keep_alive` set and the backend doesn't support it? # this one
- (b) Once, on the first `chat()` call where `keep_alive` is non-None and unused?
- (c) Only when the user explicitly sets `keep_alive` via CLI, not when it's the default?

---

## 4. Thinking Warning — "On Model Selection" Is Ambiguous

### Contradiction

The decision says: "provide a warning on model selection (via chat or commandline)."

Three different events could be "model selection":
1. CLI `--model gemma2:2b` at startup
2. Chat `/model gemma2:2b` during REPL
3. `/backend openai_compat` (backend switch, which may imply model change)

The thinking incompatibility is with the **backend**, not the model. Warning on model selection only makes sense if the warning is about the backend. But the user might switch backends without changing the model.

### Resolution Needed

Should the thinking warning fire:
- (a) When a backend is selected that doesn't support thinking (regardless of model)? # here
- (b) When a model is selected on a backend that doesn't support thinking for that model? # here also
- (c) Both? # yes

---

## 5. Model Validity Across Backend Switches

### Contradiction

The decision says: "When a backend is selected and it has no `last_used_model` then the current model keeps selected."

But if the current model is `gemma2:2b` (an Ollama model) and the user switches to `openai_compat`, the model `gemma2:2b` doesn't exist on OpenAI. The engine would send an invalid model name.

### Resolution Needed

Should the backend:
- (a) Accept any model name and let the backend API return an error?
- (b) Validate the model name against `list_models()` and warn if not found?
- (c) Silently keep the model name (user's responsibility)? # this one

---

## 6. Tool Format — `convert_tools()` Return Type Contradicts Interface

### Contradiction

The architecture doc says:
> "Normalized to `List[Dict]` in OpenAI function-calling format... eliminates the need for `OllamaTool` type entirely."

The decision says:
> "CRUCIAL: normalize it but convert it in the backend abstraction to ollamas native format. Don't let ollama do this."

These contradict. If `convert_tools()` returns backend-native types (e.g., `List[OllamaTool]` for Ollama), then the return type of `convert_tools()` is `List[Any]`, not `List[Dict]`. The engine cannot hold the result in a typed variable.

### Resolution Needed

Two interpretations:

- (a) `convert_tools()` returns backend-native format. The `chat()` method receives backend-native tools. The engine never sees the tool objects — it just passes `backend_tools` through. **This is what the decision implies.**
- (b) `convert_tools()` returns `List[Dict]` (OpenAI format). A separate `_to_native_tools()` method converts to backend-native format just before the `chat()` call. **This keeps the interface typed.** # this one. Just make sure that the ollama backend communicates in ollama native format with ollama.

---

## 7. Echo/Eliza Fake Thinking vs. `supports_thinking`

### Contradiction

If Echo/Eliza implement fake thinking (`*thinking*`), they effectively "support" thinking. Then `supports_thinking` should return `True` for them. But the original design intent was:
- `supports_thinking = True` → real thinking (Ollama, OpenAI o1)
- `supports_thinking = False` → no thinking (Echo, Eliza, OpenAI gpt-4)

With fake thinking, Echo/Eliza blur this distinction. Is the fake thinking output:
- (a) Identical to real thinking (same display, same `--thoughtlog` output)? this one
- (b) Clearly marked as fake (e.g., prefixed with `[mock thinking]`)?
- (c) Only shown when `--thinking` is enabled, but distinguishable from real thinking?

---

## 8. `--host` Default vs. Backend Default

### Contradiction

The decision says: `--host` defaults to the backend's default URL. But the current `--host` has `default="http://localhost:11434"` in `parameters.py`.

If the user runs `lama_ole --backend llama.cpp` without `--host`, what happens?

- Current behavior: `--host` defaults to `http://localhost:11434` (Ollama)
- New behavior: `--host` should default to `http://localhost:8080` (llama.cpp)

But `argparse` applies the default at parse time, before `--backend` is known. The default depends on `--backend`, but `--backend` is parsed simultaneously.

### Resolution Needed

- (a) `--host` default becomes `None`. Each backend uses its own default when `host is None`. # This one + when only the host is given without portnr the portnumber is used which is defined by the backend
- (b) `--host` default stays `http://localhost:11434`. Backend-specific defaults are documented but require explicit `--host` override.
- (c) Resolve at runtime: if `--host` equals the Ollama default and `--backend` is not `ollama`, override with the backend's default.

### I made some comments. If further ambiguities and contradictions come up though my decisions or if I missed smoething comment it in 004_ambiguities_and_contradictions_B.md

