# 005: Detailed Implementation Strategy and Unification Plan

## 1. Resolution of Clarified Requirement

### User Guidance:
> "We want to see the winning value but with an comment in the output that it has been overwritten a weaker value."

### Tier Precedence Hierarchy:
1. **Parameters** (CLI arguments) — Strongest
2. **Environment** (Shell environment variables `os.environ`) — Medium-Strong
3. **Config** (`lama_ole.env` project or user files) — Medium-Weak
4. **Defaults** (Hardcoded Python argument defaults) — Weakest

### Value Resolution & Annotation Logic:
When evaluating a parameter across selected tiers:
- The effective winning value is determined by checking tiers in precedence order: Parameter > Environment > Config > Default.
- If a value exists in a lower/weaker tier, it is noted as overridden in a comment (`# overridden lower tier: ...`).

#### Examples in Output:

**As Parameters (`--as-parameters`):**
```bash
--model "gemma4:26b-a4b-it-qat" # (overrides environment: "mistral", config: "qwen2.5")
--temperature 0.7
```

**As Environment (`--as-environment`):**
```bash
export LAMA_OLE_MODEL="gemma4:26b-a4b-it-qat" # (overrides environment: "mistral", config: "qwen2.5")
export LAMA_OLE_TEMPERATURE=0.7
```

**As Natural (`--as-natural`):**
```bash
--model "gemma4:26b-a4b-it-qat" # (overrides environment: "mistral", config: "qwen2.5")
LAMA_OLE_NUM_CTX=100000
```

---

## 2. Refactored Code Structure Overview

```
lama_ole/
├── parameters.py          # Data definitions (ParameterSpec), tier inspection & formatting helpers
├── lama_ole.py            # CLI entry point using parameters.py to build parser & handle inspection actions
```

### Key Functions in `parameters.py`:

1. `get_parameter_specs()` -> Returns list of all `ParameterSpec` instances.
2. `load_configuration_tiers(argv)` -> Captures:
   - Config tier (`_parse_env_file`)
   - Pre-existing environment tier (`os.environ` before file loading)
   - CLI arguments tier (`argv`)
3. `resolve_tier_values(spec, config_tier, env_tier, cli_tier)` -> Returns `(winning_value, winning_tier, overwritten_dict)`.
4. `format_bash_c_quote(val)` -> Returns properly quoted string with `$'...'` if value contains `\n`, `\r`, `\t`, or unprintable characters.
5. `execute_inspection_pipeline(sys_argv)` -> Sequentially processes `--show-*` and `--as-*` flags, grouping output and commenting on overwritten weaker tiers.

---

## 3. Step-by-Step Implementation Roadmap

1. **Step 1: Create `parameters.py`**
   - Define `ParameterSpec` dataclass with all metadata required by `argparse` and tier inspection.
   - Extract every argument definition currently in `build_parser()` of `lama_ole.py` into a data structure in `parameters.py`.

2. **Step 2: Implement Tier Capturing and Escaping in `parameters.py`**
   - Implement `format_bash_c_quote()` with ANSI-C quoting support (`$'...'`).
   - Implement tier resolution and comment generation for weaker overwritten values.

3. **Step 3: Update `lama_ole.py`**
   - Update `build_parser()` to iterate over `parameters.py` specs.
   - Intercept inspection parameters (`--show-*`, `--as-*`, `show-nonconfig`) during initial CLI parsing or via pre-parser pass.
   - Execute inspection printing if any `--as-*` parameter is provided, then exit with code `0`.

4. **Step 4: Verification and Test Suite Integration**
   - Run existing `tests/run_all_tests.py` suite to ensure no regressions in CLI parsing, tool calls, and session management.
   - Write new unit tests for parameter inspection, tier resolution, bash C-quoting, and `--show-*` / `--as-*` behavior.
