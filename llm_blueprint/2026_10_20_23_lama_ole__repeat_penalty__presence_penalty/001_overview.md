# repeat_penalty and presence_penalty parameters

**Status:** Implemented (modeled on the existing `temperature`, `top_p`, `top_k` parameters)

## What

Add two new Ollama sampling parameters to lama_ole:

- `repeat_penalty` — Penalize repeated token sequences (float, backend default)
- `presence_penalty` — Penalize tokens based on their presence in the text so far (float, backend default)

## Why

These are standard Ollama sampling parameters that control token generation behavior. They are supported by Ollama's native API and many OpenAI-compatible backends, but were not previously exposed via lama_ole's CLI or environment configuration.

## Key Design Decisions

- Parameters follow the exact same pattern as `temperature`, `top_p`, and `top_k`:
  - `ParameterSpec` entries in `parameters.py` with `type=float` and `default=None`
  - Environment variable support (`LAMA_OLE_REPEAT_PENALTY`, `LAMA_OLE_PRESENCE_PENALTY`)
  - Conditional forwarding to backend `options` dict (only when not `None`)
- Backend mapping is handled per-backend:
  - Ollama: passed through directly (native support)
  - OpenAI-compatible: `presence_penalty` mapped to `"presence_penalty"` in `_OPTION_MAP`; `repeat_penalty` passed through if the backend supports it
  - Groq: both parameters explicitly excluded (Groq rejects them with HTTP 400)
- No validation added — defaults to backend behavior when `None`

## Files Modified

| File | Change |
|------|--------|
| `parameters.py` | Add two `ParameterSpec`s (`repeat_penalty`, `presence_penalty`) after `top_k` |
| `lama_ole.py` | Add conditional forwarding in `options` dict |
| `README.md` | Document in Features, Configuration Options table, and Environment Variables table |

## Notes

- `repeat_penalty` is Ollama-specific; not all OpenAI-compatible backends support it.
- `presence_penalty` is widely supported (Ollama, OpenAI, etc.) but rejected by Groq.
- The implementation mirrors the already-working `temperature` parameter as closely as possible.
