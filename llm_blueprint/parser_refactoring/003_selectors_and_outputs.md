# 003: Selectors, Outputs, and State Processing

## 1. Parameters Specification

### Selectors (8 Flags):
- `--show-config` / `--show-nonconfig` (also note user instruction typo `show-nonconfig`, see contradictions file)
- `--show-environment` / `--show-noenvironment`
- `--show-parameters` / `--show-noparameters`
- `--show-defaults` / `--show-nondefaults`

### Output Actions (3 Flags):
- `--as-parameters`
- `--as-environment`
- `--as-natural`

---

## 2. Dynamic Evaluation Cycle

The task states:
> "every --as-... parameter releases all previous --show-... parameters. The output is grouped by --as and --show parameter."

This means the command line can contain multiple stages, evaluated left-to-right.

### Execution Model:

Consider the command line:
```bash
python3 lama_ole.py --show-config --as-environment --show-parameters --as-parameters
```

Or:
```bash
python3 lama_ole.py --show-environment --show-parameters --as-parameters
```

### State Machine:
1. Initialize an active selector set:
   `active_selectors = set()` (e.g. `{Origin.CONFIG, Origin.ENVIRONMENT, Origin.PARAMETER, Origin.DEFAULT}`)
2. Scan CLI tokens in order of appearance (`sys.argv[1:]`).
3. When a `--show-<X>` flag is encountered:
   - Add `<X>` to `active_selectors` (or remove if `--show-no<X>`).
4. When an `--as-<FORMAT>` flag is encountered:
   - "Release" the accumulated state:
     - Filter the active parameter entries matching the currently selected origins.
     - Group the items according to the requested grouping.
     - Format and print the values using the format specified by `<FORMAT>`.
   - Clear or reset the active selectors for subsequent `--show-...` / `--as-...` blocks.
5. If at least one `--as-...` flag was processed:
   - Exit the process (do not run LLM / chat session), unless standalone flags dictate otherwise.

---

## 3. Output Formats

### 1. `--as-parameters`
Outputs matching parameters formatted as CLI flags:
```bash
--model "gemma4:26b-a4b-it-qat"
--temperature 0.7
--thinking
```

### 2. `--as-environment`
Outputs matching parameters formatted as bash environment export statements:
```bash
export LAMA_OLE_MODEL="gemma4:26b-a4b-it-qat"
export LAMA_OLE_TEMPERATURE=0.7
export LAMA_OLE_THINKING=true
```

### 3. `--as-natural`
Displays the values in their natural / native representation:
- Parameters as CLI parameter format:
  `--model "gemma4:26b-a4b-it-qat"`
- Environment variables as key-value pairs (unexported):
  `LAMA_OLE_NUM_CTX=100000`
- Config values are treated as environment variables (as specified in task requirement line 29).

### 4. Grouping
When multiple selectors are active (e.g. `--show-config --show-environment --show-parameters --as-natural`):
Outputs must be grouped clearly by source tier (Config, Environment, Parameters) or header sections.
