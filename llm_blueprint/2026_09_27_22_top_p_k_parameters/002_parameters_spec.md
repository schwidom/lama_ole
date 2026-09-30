# 002 — ParameterSpec changes (`parameters.py`)

## Where the change lives

`parameters.py` → the `PARAMETERS` catalog (a list of `ParameterSpec`). The two new
specs are inserted immediately after the existing `temperature` spec so they sit
grouped with the other sampling knobs.

## Added specs

```python
ParameterSpec(
    name="top_p",
    flags=["--top_p"],
    env_var="LAMA_OLE_TOP_P",
    type=float,
    default=None,
    help="Constrained-sampling threshold: keep the smallest set of tokens whose cumulative probability reaches top_p (e.g., 0.9); unset to use the model's own value",
),
ParameterSpec(
    name="top_k",
    flags=["--top_k"],
    env_var="LAMA_OLE_TOP_K",
    type=int,
    default=None,
    help="Constrained-sampling threshold: restrict sampling to the top k most probable tokens (e.g., 40); unset to use the model's own value",
),
```

## Decisions and rationale

### `type=float` for `top_p`, `type=int` for `top_k`

Ollama, OpenAI, and Groq all accept `top_p` as a float in `(0, 1]` and `top_k` as a
positive int. Reusing the built-in `float`/`int` types gives us:

- argparse coercion (`--top_p 0.9`, `--top_k 40`), and
- automatic env-config handling via the generic `_env_float` / `_env_int` helpers
  in `build_parser()` — no new helper needed.

### `default=None` (not `0.0`)

Temperature defaults to `0.0` because some servers reject a literal zero and we want
an explicit value. For `top_p`/`top_k`, the right default is **unset** (`None`) so that:

- nothing is sent when the user does not ask for it (payloads stay minimal), and
- each backend can fall back to its own native/default sampling instead of being
  forced into a possibly-unwanted value.

This matches how `num_ctx` / `num_gpu` already behave in the catalog (`default=None`).

### No `choices`, no custom `action`

Plain value options, identical to temperature/num_ctx. The generic
`build_parser()` path handles them unchanged.

## Why this satisfies the mandatory CLI-help-defaults rule

Per `AGENTS.md` and enforced by `tests/test_help_defaults.py`: help strings must **not**
hardcode a default (`(default: …)`), because `argparse.ArgumentDefaultsHelpFormatter`
appends `(default: <value>)` automatically. Our help text gives usage guidance
(`e.g., 0.9`, `e.g., 40`) but never writes "(default: null)". The formatter owns the
single default rendering — so no doubled `(default: None) (default: None)` output.

Note: we deliberately avoid even the word "default" in the help text, since it sits
next to the formatter's own `(default: None)` and would read redundantly;
"unset to use the model's own value" conveys the same meaning cleanly.

## Env/config inspection participation

Because both specs carry a real `env_var` (and participate in the tier system), they
automatically appear in `--show … --as-parameters/--as-environment/--as-natural`.
Their default is `None`, so under the interpreter's `has_def` rule (`val_default is not
None`) they are **not** flagged as having a built-in default — exactly like `num_ctx`.
