# Concept: Adding `top_p` and `top_k` Sampling Parameters to the CLI

**Status:** Implemented (modeled on the existing `temperature` parameter)
**Date:** 2026-07-25
**Refs:** `parameters.py`, `lama_ole.py`, `tool_base/config.py`, `tool_base/engine.py`,
`backends/ollama_backend.py`, `backends/openai_compat_backend.py`,
`backends/groq_backend.py`, `README.md`, `tests/test_parameters.py`,
`tests/test_env_config.py`, `tests/test_groq_backend.py`

---

## 1. Objective

Expose two new sampling knobs to the `lama_ole` CLI — `--top_p` and `--top_k` — so
that users can constrain decoding without hand-editing config files or env vars.
The implementation should mirror the already-working `temperature` parameter as
closely as possible: a single spec in the central catalog, automatic CLI/env/config
plumbing, forwarding into every backend's request payload, and test coverage.

## 2. Key finding — the plumbing already exists at the backends

Before writing code we traced the full `temperature` flow end-to-end. We found that
**the backend option maps already forward both `top_p` and `top_k`**:

| Backend | `top_p` mapped? | `top_k` mapped? | Notes |
|---|---|---|---|
| `ollama_backend` | ✅ (native) | ✅ (native) | Ollama's native client accepts both directly; no mapping needed. |
| `openai_compat_backend` | ✅ `"top_p": "top_p"` | ✅ `"top_k": "top_k"` | Lines 28-29 of `_OPTION_MAP`. |
| `groq_backend` | ✅ `"top_p": "top_p"` | ❌ (absent) | Groq has no `top_k`; unknown keys are dropped by the backend. Also clamps temperature ≤ 0 → `1e-5`. |
| `llamacpp_backend` | ✅ (inherits openai_compat map) | ✅ (inherits) | Subclass of `openai_compat`. |

Because those maps already exist, **only two front-end pieces were missing**:

1. A CLI flag + env var for each option (`parameters.py`).
2. Forwarding the parsed values into the per-run `options` dict (`lama_ole.py::main`).

The engine (`tool_base/engine.py`) already passes `config.options` verbatim to every
backend's `chat(...)`, and both parser helpers (`_env_float`, `_env_int`) are
already generic — so no new plumbing was required anywhere else.

## 3. Scope of the change

- Add two `ParameterSpec` entries (top_p, top_k) to `parameters.py`.
- Forward both values into the `options` dict in `lama_ole.py::main()`.
- Update README tables (feature list, configuration options, env vars).
- Extend existing tests and add backend payload assertions.

No changes were needed to: `tool_base/engine.py`, `tool_base/config.py`, any
backend's `_OPTION_MAP`, or the parser helper functions.

See the following files for detail:

- [`002_parameters_spec.md`](./002_parameters_spec.md) — spec design & rationale
- [`003_cli_forwarding.md`](./003_cli_forwarding.md) — options-dict wiring
- [`004_backend_mapping.md`](./004_backend_mapping.md) — per-backend behavior
- [`005_tests.md`](./005_tests.md) — test plan & coverage
- [`006_docs.md`](./006_docs.md) — README updates
- [`007_summary.md`](./007_summary.md) — change set + pre-merge checklist
