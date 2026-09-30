# 004 — Backend mapping notes

## Summary: no backend changes were needed

The backend option maps already contained both `top_p` and `top_k`, so no code was
changed in any backend. This section documents the existing behavior for clarity and
for writing tests.

### `backends/ollama_backend.py` — native passthrough ✅✅

Ollama's native client accepts `options={"top_p": …, "top_k": …}` directly (no key
mapping). The engine passes the whole `options` dict under the `options=` kwarg:

```python
if options is not None:
    kwargs["options"] = options
```

So both keys reach Ollama unchanged. This mirrors how `temperature`, `num_ctx`, and
`num_gpu` already work.

### `backends/openai_compat_backend.py` — mapped ✅✅

The generic OpenAI-compatible path maps both keys in `_OPTION_MAP`:

```python
_OPTION_MAP = {
    "temperature": "temperature",
    "top_p": "top_p",       # present
    "top_k": "top_k",       # present
    ...
}
```

`chat()` iterates `options` and applies any mapped key whose value is not None:

```python
for key, value in (options or {}).items():
    target = _OPTION_MAP.get(key)
    if target and value is not None:
        mapped[target] = value
```

Since we only put `top_p`/`top_k` into `options` when set, they flow through cleanly.

### `backends/groq_backend.py` — top_p ✅ / top_k ❌ (intentional)

Groq's `_OPTION_MAP` contains `"top_p": "top_p"` but **not** `top_k` — Groq has no
`top_k` concept, so it is deliberately omitted. The generic loop simply won't find a
mapping for `top_k` and skips it (the key is dropped from the payload).

Groq also clamps temperature ≤ 0 to `1e-5`:

```python
if target == "temperature":
    if float(value) <= 0.0:
        value = 1e-5
    else:
        value = float(value)
```

This is unrelated to top_p/top_k but is documented here because the existing Groq
tests exercise this path.

### `backends/llamacpp_backend.py` — inherits ✅✅

Subclass of `OpenAICompatBackend`, so it reuses the same `_OPTION_MAP`. No change.

## Backend-specific test guidance

The existing Groq temperature-clamp test (`test_groq_backend.py::
TestGroqOptionsAndPayloads.test_temperature_zero_clamped`) documents the payload-
assertion style: capture `req.data` via a fake `urlopen`, decode JSON, assert on keys.

New backend tests should assert that a provided `options={"top_p": 0.9, "top_k": 40}`
(or just `top_p` for Groq) appears in the captured request body under the right wire
names — reusing `_sse_raw` + `patch(urlopen)` as already done there.
