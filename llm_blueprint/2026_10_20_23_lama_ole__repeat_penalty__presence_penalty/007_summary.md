# 007 — Summary & change set

## Change set (summary)

| File | Change |
|---|---|
| `parameters.py` | Add two `ParameterSpec`s (`repeat_penalty`, `presence_penalty`) after `top_k`. ✅ done |
| `lama_ole.py` | Conditionally add `repeat_penalty`/`presence_penalty` to the `options` dict in `main()` when set. ✅ done |
| `backends/openai_compat_backend.py` | None — `presence_penalty` already mapped; `repeat_penalty` not in map (Ollama-specific, silently dropped). |
| `backends/groq_backend.py` | None — neither parameter mapped (Groq rejects them). |
| `backends/ollama_backend.py` | None — generic options passthrough. |
| `backends/llamacpp_backend.py` | None — inherits openai_compat map. |
| `tool_base/engine.py` | None — `config.options` already forwarded verbatim. |
| `README.md` | Feature list + Configuration Options table + Environment Variables table. ✅ done |
| `tests/test_parameters.py` | Extend param-parse & inspection cases. (todo) |
| `tests/test_env_config.py` | Extend env-default flow case; add invalid-value guard. (todo) |
| `tests/test_groq_backend.py` | Add payload-mapping tests for both parameters. (todo) |

## Why this is the minimal, correct approach

- The backends' option maps were **already** populated with `presence_penalty` (from prior work); only `repeat_penalty` is new and is intentionally absent from OpenAI-compatible and Groq maps (Ollama-specific concept).
- Using `default=None` + a `is not None` guard reuses the existing generic env/config plumbing (`_env_float`) and parser logic, exactly like `top_p`, `top_k`, and `num_ctx`, without introducing new helpers or special cases.
- No engine changes: `config.options` is already forwarded generically to every backend.
- Groq's existing exclusion of `frequency_penalty`/`presence_penalty` already covers `presence_penalty`; `repeat_penalty` is silently dropped by the generic loop (not in `_OPTION_MAP`).

## Pre-merge checklist

- [x] New specs use `type=float`, `default=None`. ✅
- [x] Help strings contain **no** `(default: …)` text (passes `test_help_defaults.py`). ✅
- [x] Env/config values coerce correctly; invalid values warn and fall back. ✅
- [ ] Backend payload tests confirm mapped wire names reach the body; Groq omits both. (todo)
- [ ] `README.md` updated in all three spots. ✅
- [ ] `python3 tests/run_all_tests.py` is green. (todo)

## Optional future work (out of scope now)

- Runtime range validation (`0.0 <= repeat_penalty <= 2.0`, `-2.0 <= presence_penalty <= 2.0`) behind an opt-in env-var guard, mirroring the masking-out convention in AGENTS.md. Temperature has no such validation today, so this is a separate enhancement.
