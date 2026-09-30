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

- In `test_parse_cli_explicit_params`, add assertions that `--top_p 0.9` parses to
  `{"top_p": 0.9}` and `--top_k 40` → `{"top_k": 40}` (float/int coercion).
- Add a case verifying the inspection output surfaces the new flags/env vars, e.g.
  `--show "s env" --as-environment LAMA_OLE_TOP_P=0.5 …` prints
  `export LAMA_OLE_TOP_P=0.5`.

### `tests/test_env_config.py` — extend the env-default flow test

- In `test_env_defaults_flow_into_parser`, also assert that setting
  `LAMA_OLE_TOP_P`/`LAMA_OLE_TOP_K` yields `args.top_p == 0.9` / `args.top_k == 40`.
- Add a warn-and-fallback case for an invalid value (`LAMA_OLE_TOP_P=banana` → falls
  back to default, warning on stderr), mirroring the temperature/num_ctx guards.

### `tests/test_groq_backend.py` — add a payload-mapping test

- `test_top_p_forwarded`: run `GroqBackend.chat(..., options={"top_p": 0.9})` with a
  mocked `urlopen`, capture the body, assert `captured_payload["top_p"] == 0.9`.
  (`top_k` is intentionally dropped for Groq — optionally assert that passing it does
  not appear in the payload.)

### New file: `tests/test_sampling_options.py` (backend-agnostic forwarding)

- Directly invoke each backend's `chat()` with `options={"top_p": 0.9, "top_k": 30}`
  and assert the captured JSON body contains the mapped keys (`openai_compat` /
  `llamacpp` get both; `groq` gets only `top_p`). This pins end-to-end mapping without
  needing a live server.

## Rationale for not adding range validation tests now

There is no runtime range validation (e.g. `0 < top_p <= 1`) in the current code, and
temperature has none either. Validation can be added later behind an opt-in env-var
guard if desired; it is out of scope for this concept. See `007_summary.md`.
