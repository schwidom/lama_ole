# 003 — CLI forwarding (`lama_ole.py`)

## Where the change lives

`lama_ole.py` → `main()` → the per-run `options` dict that is passed into
`RunConfig(options=options, …)`. This is the same place where `"temperature":
args.temperature` is added.

## Added code

```python
options = {
    "temperature": args.temperature,
}

if None != args.top_p:
    options["top_p"] = args.top_p

if None != args.top_k:
    options["top_k"] = args.top_k

if None != args.repeat_penalty:
    options["repeat_penalty"] = args.repeat_penalty

if None != args.presence_penalty:
    options["presence_penalty"] = args.presence_penalty

if None != args.num_ctx:
    options["num_ctx"] = args.num_ctx

if None != args.num_gpu:
    options["num_gpu"] = args.num_gpu
```

## Why the `is not None` guard (and why it differs from temperature)

Temperature must always be present in the payload because its default is a real
value (`0.0`). For `repeat_penalty`/`presence_penalty` we use `default=None`, so
guarding with `if … is not None` means an unset knob never pollutes the request
payload and each backend can apply its own native fallback — exactly analogous to
how `top_p`, `top_k`, `num_ctx`, and `num_gpu` are already conditionally added:

```python
if None != args.num_ctx:
    options["num_ctx"] = args.num_ctx
```

This is intentional: sending `repeat_penalty=0.0` or `presence_penalty=0.0` would
override the model's own sampling on every backend, which is not what a user wants
when they never asked for these knobs.

## Env/config plumbing needs no change

`build_parser()` selects `_env_float` for float specs automatically:

```python
elif spec.type is float:
    default_val = _env_float(spec.env_var, spec.default)
```

So `LAMA_OLE_REPEAT_PENALTY` / `LAMA_OLE_PRESENCE_PENALTY` are read from shell env
and `lama_ole.env` files with the same warn-and-fallback behavior as `top_p`/`top_k`.
No new helper is required.

## Engine needs no change

`tool_base/engine.py::run_with_tools()` already forwards `config.options` verbatim to
`config.client.chat(..., options=config.options)`. The two new keys flow through the
same generic path as every other option — no engine modification needed.
