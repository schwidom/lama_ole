# 005 — Test plan

## Conventions (from `tests/run_all_tests.py` / AGENTS.md)

- Every test file that imports package modules must include the `sys.path` bootstrap:

  ```python
  current_file = os.path.abspath(__file__)
  lama_ole_dir = os.path.abspath(os.path.join(os.path.dirname(current_file), ".."))
  if lama_ole_dir not in sys.path:
      sys.path.insert(0, lama_ole_dir)
  ```

- Files are collected by both `unittest discover -s tests -p "test_*.py"` and
  `pytest tests/`. Keep module-level imports side-effect-free.
- The CLI help-defaults guard (`tests/test_help_defaults.py`) is **opt-in** via
  `LAMA_OLE_ENFORCE_HELP_DEFAULTS=1`; it must not be broken by our new help text
  (which contains no `(default: …)`).

## Files touched

### `tests/test_parameters.py` — extend existing cases

- In `test_parse_cli_explicit_params`, add assertions that `--repeat_penalty 1.1` parses
  to `{"repeat_penalty": 1.1}` and `--presence_penalty 0.5` → `{"presence_penalty": 0.5}`
  (float coercion).
- Add a case verifying the inspection output surfaces the new flags/env vars, e.g.
  `--show "s env" --as-environment LAMA_OLE_REPEAT_PENALTY=1.1 …` prints
  `export LAMA_OLE_REPEAT_PENALTY=1.1`.

### `tests/test_env_config.py` — extend the env-default flow test

- In `test_env_defaults_flow_into_parser`, also assert that setting
  `LAMA_OLE_REPEAT_PENALTY`/`LAMA_OLE_PRESENCE_PENALTY` yields
  `args.repeat_penalty == 1.1` / `args.presence_penalty == 0.5`.
- Add a warn-and-fallback case for an invalid value (`LAMA_OLE_REPEAT_PENALTY=banana` →
  falls back to default, warning on stderr), mirroring the temperature/num_ctx guards.

### `tests/test_groq_backend.py` — add a payload-mapping test

- `test_presence_penalty_dropped`: run `GroqBackend.chat(..., options={"presence_penalty": 0.5})`
  with a mocked `urlopen`, capture the body, assert `presence_penalty` does **not**
  appear in the captured payload (Groq rejects it).
- `test_repeat_penalty_dropped`: similarly assert `repeat_penalty` is absent from the
  Groq payload.

### New file: `tests/test_sampling_options.py` (backend-agnostic forwarding)

- Directly invoke each backend's `chat()` with `options={"repeat_penalty": 1.1, "presence_penalty": 0.5}`
  and assert the captured JSON body contains the mapped keys:
  - `ollama`: both keys present in `options`
  - `openai_compat`: `presence_penalty` present in payload; `repeat_penalty` dropped (not in `_OPTION_MAP`)
  - `groq`: both keys dropped (not in `_OPTION_MAP`)

## Rationale for not adding range validation tests now

There is no runtime range validation (e.g. `-2.0 <= presence_penalty <= 2.0`) in the
current code, and temperature has none either. Validation can be added later behind an
opt-in env-var guard if desired; it is out of scope for this concept. See `007_summary.md`.
