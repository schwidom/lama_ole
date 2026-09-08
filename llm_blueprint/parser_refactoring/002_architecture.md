# 002: Parameters Database and Architecture Design

## 1. Module Structure: `parameters.py`

The new module `parameters.py` will serve as the single source of truth for:
- Command-line argument definitions (long name, short flags, metavar, type, action).
- Environment variable mappings (e.g. `LAMA_OLE_MODEL`, `LAMA_OLE_NUM_CTX`).
- Default values and factory fallbacks.
- Origin detection and classification.
- Value formatting (parameters vs environment vs natural, including bash c-quoting).

### Proposed Schema

Each parameter is represented by a structured dataclass or dictionary specification:

```python
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Sequence, Union

@dataclass
class ParameterSpec:
    name: str                           # Canonical identifier, e.g. "model"
    flags: List[str]                    # e.g. ["-m", "--model"]
    dest: Optional[str] = None          # Destination attribute in args (defaults to name)
    env_var: Optional[str] = None       # e.g. "LAMA_OLE_MODEL"
    type: Any = str                     # Python type or converter function
    default: Any = None                 # Default value when not specified in any tier
    choices: Optional[Sequence[Any]] = None
    action: Optional[str] = None        # e.g. "store_true", "append", "count", BooleanOptionalAction
    nargs: Optional[Union[int, str]] = None
    metavar: Optional[Union[str, tuple]] = None
    help: str = ""
    # Category / tier behavior flags
    is_standalone_mode: bool = False    # e.g. --list, --ps, --stop, --version
    repeatable: bool = False            # e.g. --tool, --skill, --vision_model
```

---

## 2. Distinction Between Config, Environment, and Parameters

Currently in `lama_ole.py`, `load_env_files()` directly inserts config values into `os.environ` with `os.environ.setdefault()`.
This destroys the distinction between:
- A value set in the shell environment (`export LAMA_OLE_MODEL=...`)
- A value set in `lama_ole.env` (`LAMA_OLE_MODEL=...`)

### Refined Loading Architecture

To support the `--show-config` vs `--show-environment` selectors:
1. `parameters.py` tracks sources separately:
   - `CONFIG_VALUES`: parsed from `~/.config/lama_ole/lama_ole.env` and `./lama_ole.env` before mutating `os.environ`.
   - `INITIAL_ENV`: snapshot of `dict(os.environ)` before `load_env_files()` modifies anything.
   - `CLI_PARAMS`: parsed from `sys.argv`.
2. When resolving active values:
   - If argument was explicitly provided on CLI -> Source is `PARAMETER`.
   - Else if present in `INITIAL_ENV` -> Source is `ENVIRONMENT`.
   - Else if present in `CONFIG_VALUES` -> Source is `CONFIG`.
   - Else -> Source is `DEFAULT`.

---

## 3. Dynamic Parser Registration

Instead of hardcoding dozens of `parser.add_argument(...)` calls in `build_parser()`, `build_parser()` iterates through the parameter catalog:

```python
def register_parameters(parser: argparse.ArgumentParser, specs: List[ParameterSpec], env_defaults: dict):
    for spec in specs:
        kwargs = {}
        if spec.help:
            kwargs["help"] = spec.help
        if spec.action:
            kwargs["action"] = spec.action
        if spec.choices:
            kwargs["choices"] = spec.choices
        if spec.nargs is not None:
            kwargs["nargs"] = spec.nargs
        if spec.metavar is not None:
            kwargs["metavar"] = spec.metavar
        if spec.dest:
            kwargs["dest"] = spec.dest
        if spec.type and spec.action not in ("store_true", "store_false", "count"):
            kwargs["type"] = spec.type

        # Compute active default from config / env
        default_val = env_defaults.get(spec.name, spec.default)
        if spec.action not in ("store_true", "store_false", "count", "version"):
            kwargs["default"] = default_val

        parser.add_argument(*spec.flags, **kwargs)
```

---

## 4. Bash C-Quoting ($'...') Implementation

Values containing newlines or special control characters must be quoted using Bash ANSI-C quoting syntax (`$'...'`).

### Escaping Rules:
- If a string contains `\n`, `\r`, `\t`, unprintable characters, or single quotes/backslashes:
  - Replace `\` with `\\`
  - Replace `'` with `\'`
  - Replace newline `\n` with `\n`
  - Replace carriage return `\r` with `\r`
  - Replace tab `\t` with `\t`
  - Wrap in `$'...'`
- If a string contains only ordinary spaces or characters safe for standard shell quoting:
  - Wrap in standard double quotes `"...`" or single quotes `'...'`.
- Non-string types (integers, floats, booleans):
  - Converted to standard textual representations (e.g. `100000`, `0.7`, `true`).
