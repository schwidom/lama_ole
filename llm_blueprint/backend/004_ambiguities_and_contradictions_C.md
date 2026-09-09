# 004C: Contradictions Introduced by B-Decisions

These contradictions arose from applying the decisions in `004B`.

---

## 1. Vision Backend — Full `LlmBackend` or Just a URL?

### Contradiction

The decision says: "introduce `LAMA_OLE_VISION_BACKEND` which defines the backend which is to use. Deprecate `set_ollama_host()` / `get_ollama_host()` completely."

But media tools (`tools/media_understanding_tools.py`) currently use `get_ollama_host()` only to get a **URL**. They make direct HTTP requests to Ollama's `/api/generate` endpoint with image payloads. They do NOT use the `ollama.Client.chat()` API.

If `LAMA_OLE_VISION_BACKEND` names a full backend, should media tools:
- (a) Create a full `LlmBackend` instance and use its `chat()` method?
- (b) Use the backend only for its host URL, making direct HTTP calls as before?
- (c) Not use the backend abstraction at all — `LAMA_OLE_VISION_BACKEND` just selects which backend's default host to use for direct HTTP calls?

---

## 2. `LAMA_OLE_VISION_HOST` and `LAMA_OLE_VISION_BACKEND` Coexistence

### Contradiction

Currently: `LAMA_OLE_VISION_HOST` overrides the Ollama host for media tools.

Proposed: `LAMA_OLE_VISION_BACKEND` selects the backend for media tools.

If both exist:
- `LAMA_OLE_VISION_BACKEND=ollama` + `LAMA_OLE_VISION_HOST=http://myserver:11434` → use Ollama backend at custom host
- `LAMA_OLE_VISION_BACKEND=openai_compat` + `LAMA_OLE_VISION_HOST=https://api.openai.com` → use OpenAI for vision?

But OpenAI's `/v1/chat/completions` doesn't accept image payloads the same way Ollama does. Media tools send base64 images to Ollama's `/api/generate`. OpenAI uses a different image format in the messages array.

### Resolution Needed

- (a) `LAMA_OLE_VISION_BACKEND` only accepts `ollama` (vision is Ollama-only)?
- (b) `LAMA_OLE_VISION_BACKEND` accepts any backend, but media tools must adapt to each backend's image format? 
- (c) `LAMA_OLE_VISION_HOST` is kept for vision-specific URL override; `LAMA_OLE_VISION_BACKEND` is removed? # this one (for simplicity)

---

## 3. `last_used_model` — Only on Backend Switch Is Insufficient

### Contradiction

The decision chose (c): store `last_used_model` only on backend switch.

Scenario:
1. User starts with Ollama, default model `gemma2:2b`
2. User does `/model llama3:8b` → `last_used_model_by_backend["ollama"]` is NOT updated
3. User does `/backend echo` → snapshots `llama3:8b` into `last_used_model_by_backend["ollama"]`
4. User does `/backend ollama` → restores `llama3:8b` → correct

This works. But consider:
1. User starts with Ollama, default model `gemma2:2b`
2. User does `/backend echo` → snapshots `gemma2:2b` into `last_used_model_by_backend["ollama"]`
3. User does `/backend ollama` → restores `gemma2:2b` → correct
4. User does `/model llama3:8b`
5. User does `/model mistral:7b`
6. User does `/backend echo` → snapshots `mistral:7b` into `last_used_model_by_backend["ollama"]`
7. User does `/backend ollama` → restores `mistral:7b` → correct

This also works. The snapshot captures the LAST model used before switching.

But what if the user does `/model` but never switches backends? The `last_used_model_by_backend` is never updated. This is fine — the model is set directly, no need to restore it.

Actually, I don't see a contradiction here. The behavior is correct. Let me reconsider...

The real issue: what if the user switches backends multiple times without changing the model?

1. User starts with Ollama, model `gemma2:2b`
2. User does `/backend echo` → snapshots `gemma2:2b` into `last_used_model_by_backend["ollama"]`
3. User does `/backend ollama` → restores `gemma2:2b`
4. User does `/backend echo` → snapshots `gemma2:2b` into `last_used_model_by_backend["ollama"]` (same value)
5. User does `/backend ollama` → restores `gemma2:2b`

No issue. The dict value is stable.

**No contradiction found.** The decision works correctly. # ok

---

## 4. Media Tools Need a Backend Instance, Not Just a URL # scrubbed

### Contradiction

If `LAMA_OLE_VISION_BACKEND=ollama` and media tools need to make API calls, they need:
- A host URL (from `LAMA_OLE_VISION_HOST` or the backend's default)
- The API format (Ollama's `/api/generate` for images)

If the vision backend is a full `LlmBackend` instance, media tools could call `backend.chat()` with image content. But the current media tool implementation sends images via Ollama's `/api/generate` endpoint, which is not the same as `chat()`.

The `chat()` method is for text chat completions. Image understanding in Ollama uses a different endpoint (`/api/generate` with `images` field).

### Resolution Needed

Should the `LlmBackend` interface include an image/media method?

- (a) Add `generate(model, prompt, images, ...)` to `LlmBackend` for media inference?
- (b) Keep media tools as direct HTTP callers; `LAMA_OLE_VISION_BACKEND` only provides the host URL?
- (c) Create a separate `MediaBackend` interface for media tools?

### I made some comments. If further ambiguities and contradictions come up though my decisions or if I missed smoething comment it in 004_ambiguities_and_contradictions_D.md

