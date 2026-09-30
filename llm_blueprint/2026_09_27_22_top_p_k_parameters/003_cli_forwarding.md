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

if None != args.num_ctx:
    options["num_ctx"] = args.num_ctx

if None != args.num_gpu:
    options["num_gpu"] = args.num_gpu
```

## Why the `is not None` guard (and why it differs from temperature)

Temperature must always be present in the payload because its default is a real
value (`0.0`). For `top_p`/`top_k` we use `default=None`, so guarding with
`if … is not None` means an unset knob never pollutes the request payload and each
backend can apply its own native fallback — exactly analogous to how `num_ctx` /
`num_gpu` are already conditionally added:

```python
if None != args.num_ctx:
    options["num_ctx"] = args.num_ctx
```

This is intentional: sending `top_p=0.0`/`top_k=0` would override the model's own
sampling on every backend, which is not what a user wants when they never asked for
these knobs.

## Env/config plumbing needs no change

`build_parser()` selects `_env_float` / `_env_int` for float/int specs automatically:

```python
if spec.type is int:
    default_val = _env_int(spec.env_var, spec.default)
elif spec.type is float:
    default_val = _env_float(spec.env_var, spec.default)
```

So `LAMA_OLE_TOP_P` / `LAMA_OLE_TOP_K` are read from shell env and `lama_ole.env`
files with the same warn-and-fallback behavior as temperature/num_ctx. No new helper
is required.

## Engine needs no change

`tool_base/engine.py::run_with_tools()` already forwards `config.options` verbatim to
`config.client.chat(..., options=config.options)`. The two new keys flow through the
same generic path as every other option — no engine modification needed.
