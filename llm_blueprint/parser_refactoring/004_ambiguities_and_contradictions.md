# 004: Ambiguities, Contradictions, and Open Questions

Before implementing the refactoring, several contradictions, edge cases, and ambiguous requirements in `task_001.txt` must be clarified and resolved.

---

## 1. Syntax Ambiguity: `show-nonconfig` vs `--show-nonconfig`

### Issue:
Line 18 of `task_001.txt` states:
> "There are 8 selector parameter : --show-config, show-nonconfig, --show-environment, --show-noenvironment, --show-parameters, --show-noparameters, --show-defaults, --show-nondefaults"

Notice that `show-nonconfig` is missing the leading double hyphens `--`, whereas all other 7 selectors have `--`.

### Question / Recommendation:
- Is `show-nonconfig` a typo in the prompt for `--show-nonconfig`, or must both `--show-nonconfig` and positional `show-nonconfig` be accepted?
- **Recommendation:** Accept both `--show-nonconfig` and `show-nonconfig` to prevent failures if passed as written, while treating `--show-nonconfig` as the canonical flag.

---

## 2. Semantics of Negative Selectors (`--show-no...` / `--show-non...`)

### Issue:
Does `--show-noenvironment` mean:
1. **Subtract/Deselect**: Remove `environment` from the currently accumulated set of active selectors? (e.g. user previously specified `--show-environment`, then negated it).
2. **Complement/Invert**: Select everything *except* environment? (i.e. select `config`, `parameters`, and `defaults`).
3. **Show unset/absent items**: Show items that do *not* have an environment variable set?

### Question / Recommendation:
- Look at the naming: `--show-defaults` vs `--show-nondefaults`, `--show-environment` vs `--show-noenvironment`.
- If `--show-environment` explicitly selects values originating from environment variables:
  - If it is a deselect flag: it turns off the environment selector.
  - If it is a complement filter: `--show-nondefaults` means show all parameters that have non-default values (i.e. explicitly set by config, env, or CLI).
- **Recommendation:**
  - Positive selectors (`--show-config`, `--show-environment`, `--show-parameters`, `--show-defaults`) enable inclusion of that origin tier.
  - Negative/Invert selectors:
    - `--show-nondefaults`: Include parameters whose active value differs from the default (i.e. explicitly configured).
    - `--show-noenvironment`: If positive selectors are additive, does `--show-no...` subtract an enabled category, or does it select parameters *without* an environment variable?
  - Clarification from user is needed on exact intended behavior.

---

## 3. Scope of CLI Parameters in `--show-...`

### Issue:
Some CLI flags do not have corresponding environment variables or config keys:
- Action / standalone flags: `-V`/`--version`, `-l`/`--list`, `--ps`, `--stop`, `--transfer`, `--serve-blobs`, `--help`, `--help-tools`.
- Inspect flags themselves: `--show-config`, `--as-environment`, etc.
- Multi-argument flags: `--transfer SOURCE DEST`.
- Repeatable flags: `--tool`, `--skill`, `--vision_model`.

### Questions:
1. Should the inspection flags (`--show-*`, `--as-*`) exclude themselves from the output?
   - **Recommendation:** Yes, inspection flags should never be displayed in the output.
2. How should CLI parameters without environment variables (e.g. `--stop`, `--list`) be formatted if `--as-environment` is chosen?
   - Can they be exported? (No standard `LAMA_OLE_*` variable exists for them).
   - **Recommendation:** Either omit them under `--as-environment` with a warning, or skip items that have no mapped environment variable.
3. How should repeatable parameters (like `--tool` or `--vision_model`) be formatted in `--as-environment`?
   - `LAMA_OLE_TOOL` expects space-separated values (e.g. `export LAMA_OLE_TOOL="tools.foo tools.bar"`).
   - CLI expects repeated flags (`--tool tools.foo --tool tools.bar`).
   - Need confirmation that conversion logic between list parameters and space-separated env vars matches `lama_ole.py` conventions.

---

## 4. Lifecycle and Exit Behavior

### Issue:
When `--as-parameters`, `--as-environment`, or `--as-natural` is passed:
1. Should `lama_ole.py` exit immediately after printing the inspection output?
   - In standard CLI conventions, inspection flags (like `--version`, `--help`, `--show-*`) perform their output and exit `0` without attempting to connect to the Ollama server or start a chat session.
   - What happens if someone passes `--show-parameters --as-parameters -m llama3 -i "hello"`?
2. **Recommendation:** If any `--as-...` flag is executed, print the requested groups and terminate with exit code 0.

---

## 5. Multiple `--as-...` Arguments on Single Command Line

### Issue:
Line 31 & 33 state:
> "every --as-... parameter releases all previous --show-... parameters. The output is grouped by --as and --show parameter."

### Examples:
```bash
python3 lama_ole.py --show-environment --as-environment --show-parameters --as-parameters
```
1. Does the first `--as-environment` consume `--show-environment`, print the environment section, and clear the selector list?
2. Then does `--show-parameters` add `parameters` to the clean selector list, which `--as-parameters` prints?
3. What is the exact expected header or grouping delimiter between groups?
   - Example visual output:
     ```text
     [Environment as Environment]
     export LAMA_OLE_MODEL="gemma4:26b-a4b-it-qat"

     [Parameters as Parameters]
     --model "gemma4:26b-a4b-it-qat"
     ```
   - We need to know if strict machine-parseable output is expected (e.g. pure bash statements so `eval $(...)` works) or human-readable section headers. Note that if headers are printed, `eval $(lama_ole.py --show-environment --as-environment)` would fail unless headers are commented (`# [Environment]`).
   - **Recommendation:** Use bash comments `# --- Group: ... ---` so output remains executable in bash scripts while being clearly grouped for human reading.

---

## 6. Precedence and Detection of Origin

### Issue:
If an option is set in both `lama_ole.env` AND in shell `os.environ` AND passed via `--model`:
- Value in `lama_ole.env`: `model=qwen2.5`
- Value in shell env: `export LAMA_OLE_MODEL=mistral`
- Value on CLI: `--model gemma4:26b-a4b-it-qat`

When the user runs:
`--show-config --show-environment --show-parameters --as-parameters`
Does it print:
1. Only the active winning value (`--model "gemma4:26b-a4b-it-qat"`) grouped under CLI parameters?
2. Or does it print the value from each tier (Config: qwen2.5, Environment: mistral, Parameter: gemma4)?
- Line 26-29 of the prompt indicates:
  > "--show-config --show-environment --show-parameters --as-natural shows the values from all 3 sections"
  This implies the user wants to see the values present in all 3 tiers!
- Clarification needed: When a parameter is present in multiple tiers, do we display the tier-specific values for each requested tier, or only the final active value assigned to the highest-precedence tier?
