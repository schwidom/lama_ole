# 004 — Backend mapping notes

## Summary: minimal backend changes were needed

`presence_penalty` was already present in `openai_compat_backend.py`'s `_OPTION_MAP`
(from prior work). `repeat_penalty` was not present in any backend's map. No backend
code was modified — the implementation relies on the existing generic forwarding
path.

### `backends/ollama_backend.py` — native passthrough ✅✅

Ollama's native client accepts `options={"repeat_penalty": …, "presence_penalty": …}`
directly (no key mapping). The engine passes the whole `options` dict under the
`options=` kwarg:

```python
if options is not None:
    kwargs["options"] = options
```

So both keys reach Ollama unchanged. This mirrors how `temperature`, `num_ctx`,
`top_p`, and `top_k` already work.

### `backends/openai_compat_backend.py` — presence_penalty ✅ / repeat_penalty ⚠️

`presence_penalty` is already mapped in `_OPTION_MAP`:

```python
_OPTION_MAP = {
    "temperature": "temperature",
    "top_p": "top_p",
    "top_k": "top_k",
    ...
    "frequency_penalty": "frequency_penalty",
    "presence_penalty": "presence_penalty",
}
```

`repeat_penalty` is **not** in `_OPTION_MAP`. It will be silently dropped by the
generic loop (`_OPTION_MAP.get(key)` returns `None`). This is acceptable because
`repeat_penalty` is Ollama-specific and not part of the OpenAI API spec. If a
backend supports it under a different wire name, the backend would need a custom
map entry.

### `backends/groq_backend.py` — both ❌ (intentional)

Groq's `_OPTION_MAP` contains neither `repeat_penalty` nor `presence_penalty`. Groq
rejects `frequency_penalty` and `presence_penalty` with HTTP 400 errors, and
`repeat_penalty` is not a Groq concept. Both keys are silently dropped from the
payload — this is the intended behavior.

### `backends/llamacpp_backend.py` — inherits ✅ (for presence_penalty)

Subclass of `OpenAICompatBackend`, so it reuses the same `_OPTION_MAP`.
`presence_penalty` flows through; `repeat_penalty` is dropped (same as openai_compat).

## Backend-specific test guidance

The existing Groq temperature-clamp test (`test_groq_backend.py::
TestGroqOptionsAndPayloads.test_temperature_zero_clamped`) documents the payload-
assertion style: capture `req.data` via a fake `urlopen`, decode JSON, assert on
keys.

New backend tests should assert that a provided `options={"presence_penalty": 0.5}`
appears in the captured request body for `openai_compat`, and is absent for `groq`.
`repeat_penalty` should be asserted present in Ollama's captured `options` dict.
