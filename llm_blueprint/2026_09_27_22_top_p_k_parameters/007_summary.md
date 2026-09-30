# 007 — Summary & change set

## Change set (summary)

| File | Change |
|---|---|
| `parameters.py` | Add two `ParameterSpec`s (`top_p`, `top_k`) after `temperature`. ✅ done |
| `lama_ole.py` | Conditionally add `top_p`/`top_k` to the `options` dict in `main()` when set. ✅ done |
| `backends/openai_compat_backend.py` | None — already maps both keys. |
| `backends/groq_backend.py` | None — `top_p` mapped; `top_k` intentionally absent. |
| `backends/ollama_backend.py` | None — generic options passthrough. |
| `backends/llamacpp_backend.py` | None — inherits openai_compat map. |
| `tool_base/engine.py` | None — `config.options` already forwarded verbatim. |
| `README.md` | Feature list + Configuration Options table + Environment Variables table. (todo) |
| `tests/test_parameters.py` | Extend param-parse & inspection cases. (todo) |
| `tests/test_env_config.py` | Extend env-default flow case; add invalid-value guard. (todo) |
| `tests/test_groq_backend.py` | Add `top_p` payload-mapping test. (todo) |

## Why this is the minimal, correct approach

- The backends' option maps were **already** populated with `top_p`/`top_k`; only the
  front door (CLI/env) and options-dict forwarding were missing. This means no wire-
  format work and no risk of diverging API names between backends — they already agree.
- Using `default=None` + a `is not None` guard reuses the existing generic env/config
  plumbing (`_env_float`/`_env_int`) and parser logic, exactly like `num_ctx`, without
  introducing new helpers or special cases.
- No engine changes: `config.options` is already forwarded generically to every backend.

## Pre-merge checklist

- [x] New specs use `type=float` (top_p) / `type=int` (top_k), `default=None`. ✅
- [x] Help strings contain **no** `(default: …)` text (passes `test_help_defaults.py`). ✅
- [x] Env/config values coerce correctly; invalid values warn and fall back. ✅
- [ ] Backend payload tests confirm mapped wire names (`top_p`/`top_k`) reach the body; Groq omits `top_k`. (todo)
- [ ] `README.md` updated in all three spots. (todo)
- [ ] `python3 tests/run_all_tests.py` is green. (todo)

## Optional future work (out of scope now)

- Runtime range validation (`0 < top_p <= 1`, `top_k >= 1`) behind an opt-in env-var
  guard, mirroring the masking-out convention in AGENTS.md. Temperature has no such
  validation today, so this is a separate enhancement.
