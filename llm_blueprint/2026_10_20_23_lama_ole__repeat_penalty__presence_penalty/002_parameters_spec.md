# 002 — ParameterSpec changes (`parameters.py`)

## Where the change lives

`parameters.py` → the `PARAMETERS` catalog (a list of `ParameterSpec`). The two new
specs are inserted immediately after the existing `top_k` spec so they sit grouped
with the other sampling knobs.

## Added specs

```python
ParameterSpec(
    name="repeat_penalty",
    flags=["--repeat_penalty"],
    env_var="LAMA_OLE_REPEAT_PENALTY",
    type=float,
    default=None,
    help="Penalize repeat sequence of tokens (e.g., 1.1); unset to use the model's own value",
),
ParameterSpec(
    name="presence_penalty",
    flags=["--presence_penalty"],
    env_var="LAMA_OLE_PRESENCE_PENALTY",
    type=float,
    default=None,
    help="Present penalty for tokens based on their presence in the text so far (e.g., 0.5); unset to use the model's own value",
),
```

## Decisions and rationale

### `type=float` for both

Ollama and OpenAI both accept `repeat_penalty` and `presence_penalty` as floats.
`repeat_penalty` is typically in `[0.0, 2.0]` (values > 1 penalize repetition,
values < 1 encourage it). `presence_penalty` is typically in `[-2.0, 2.0]`.
Using `float` gives us argparse coercion and automatic env-config handling via
`_env_float` in `build_parser()` — no new helper needed.

### `default=None` (not `0.0`)

Both parameters default to `None` so that:

- nothing is sent when the user does not ask for it (payloads stay minimal), and
- each backend can fall back to its own native/default sampling instead of being
  forced into a possibly-unwanted value.

This matches how `top_p`, `top_k`, `num_ctx`, and `num_gpu` already behave in the
catalog (`default=None`).

### No `choices`, no custom `action`

Plain value options, identical to `top_p`/`top_k`/`temperature`. The generic
`build_parser()` path handles them unchanged.

## Why this satisfies the mandatory CLI-help-defaults rule

Per `AGENTS.md` and enforced by `tests/test_help_defaults.py`: help strings must **not**
hardcode a default (`(default: …)`), because `argparse.ArgumentDefaultsHelpFormatter`
appends `(default: <value>)` automatically. Our help text gives usage guidance
(`e.g., 1.1`, `e.g., 0.5`) but never writes "(default: null)". The formatter owns the
single default rendering — so no doubled `(default: None) (default: None)` output.

Note: we deliberately avoid even the word "default" in the help text, since it sits
next to the formatter's own `(default: None)` and would read redundantly;
"unset to use the model's own value" conveys the same meaning cleanly.

## Env/config inspection participation

Because both specs carry a real `env_var` (and participate in the tier system), they
automatically appear in `--show … --as-parameters/--as-environment/--as-natural`.
Their default is `None`, so under the interpreter's `has_def` rule (`val_default is not
None`) they are **not** flagged as having a built-in default — exactly like `num_ctx`
and `top_p`/`top_k`.
