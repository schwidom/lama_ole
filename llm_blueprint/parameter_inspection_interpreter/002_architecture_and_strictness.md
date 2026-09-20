# 002: Architecture & Parser Strictness Specification

## 1. Analysis of the Current Parser Behavior

In `parameters.py`, two primary functions handle command-line inspection:

### 1.1 `parse_cli_explicit_params(argv: List[str])`
- Iterates over `argv` linearly with index `i`.
- If an argument is in `INSPECTION_FLAGS` (`--show`, `--as-parameters`, `--as-environment`, `--as-natural`), it increments `i += 1` without validating arguments to `--show`.
- If an argument is in `flag_to_spec`:
  - Parses flags, boolean options, counts, appends, and 2-ary arguments.
- If an argument is unrecognized (neither inspection nor in `flag_to_spec`), it simply falls through the `else: i += 1` branch without warning or error.

### 1.2 `process_inspection_flags(argv, config_dict, initial_env)`
- Checks `has_as_flag = any(a in ("--as-parameters", "--as-environment", "--as-natural") for a in argv)`.
- If found, iterates linearly:
  ```python
  fill_selector_script = False
  selector_script: Optional[str] = None
  for token in argv:
      if fill_selector_script:
          selector_script = token
          fill_selector_script = False
      elif token == "--show":
          fill_selector_script = True
      elif token in ("--as-parameters", "--as-environment", "--as-natural"):
          # ... executes _output_inspection_group ...
          selector_script = None
  ```
- **Flaws in this loop**:
  1. If `--show` is immediately followed by `--as-parameters` (e.g. `lama_ole --show --as-parameters`), `fill_selector_script` causes `selector_script = "--as-parameters"`, which fails in the interpreter or causes confusing behavior.
  2. Any unrecognized token (e.g., `--show-parameters`, `show-nonconfig`) is simply ignored by the loop.
  3. `_output_inspection_group` checks `if selector_script is not None and not interpret(attributes, selector_script): continue`. When `selector_script` is `None`, it defaults to passing everything through, meaning obsolete flags cause the filter to be completely bypassed.

---

## 2. Specification for Strict Inspection Parsing

To ensure strict validation and prevent obsolete or malformed flags from passing silently:

### 2.1 Recognized Flags & Schema
Inspection CLI parsing must recognize:
1. **Inspection Control Flags:**
   - `--show <script>` (expects exactly one string argument following `--show` that is NOT another `--as-*` or leading inspection flag).
   - `--as-parameters`
   - `--as-environment`
   - `--as-natural`
2. **Standard Application Parameters:**
   - Defined in `PARAMETERS` (including short flags and `--no-*` variants for boolean options).
3. **Unrecognized Arguments Rejection:**
   - Any argument in `argv` starting with `-` (or unexpected positional tokens not belonging to previous flags) that does not match a known parameter in `PARAMETERS` or an inspection flag must be rejected with an error (e.g., `SystemExit(2)` or raising `argparse.ArgumentError` / `ValueError`).

### 2.2 Token-Stream Parsing State Machine for Inspection
Rather than loose independent scans, inspection parsing should process `argv` strictly:

```text
[Tokens in argv]
       │
       ▼
┌────────────────────────────────────────────────────────┐
│ Parse Step: Token by Token                             │
│                                                        │
│ • If token == "--show":                                │
│     Check that next token exists and is not a flag     │
│     (or starts with a valid script syntax).            │
│     Set current_selector = next_token.                 │
│                                                        │
│ • If token in ("--as-parameters", ...):               │
│     Execute inspection group with current_selector.    │
│     Reset current_selector = None.                     │
│                                                        │
│ • If token is known parameter flag:                    │
│     Consume parameter and its values (if any).         │
│                                                        │
│ • If token is unknown flag (starts with '-'):          │
│     Raise / Exit with Unknown Option error.            │
└────────────────────────────────────────────────────────┘
```

### 2.3 Attribute Mapping for the Interpreter
Ensure all attributes evaluated in `_output_inspection_group` correctly match the LI specification in `doc.txt`:
- `has_def`: parameter has a default defined.
- `has_conf`: parameter allows a config value (`spec.env_var` exists).
- `has_conf_set`: config file defines a value for `spec.env_var`.
- `has_env`: parameter allows an environment variable (`spec.env_var` exists).
- `has_env_set`: environment variable is set in `initial_env`.
- `has_arg`: parameter allows a CLI argument (`spec` exists).
- `has_arg_set`: CLI argument is explicitly supplied in `argv`.
