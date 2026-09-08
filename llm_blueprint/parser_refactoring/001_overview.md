# 001: Overview and Requirements Analysis

## Context and Goal

In `lama_ole.py`, command-line arguments, environment variables, and configuration values are currently defined and parsed using repeated procedural calls to `parser.add_argument(...)` and helper functions like `_env_str()`, `_env_int()`, `_env_float()`, `_env_bool()`, and `_env_choice()`.

The goal of this refactoring is:
1. Extract the relationship between program parameters, environment variables, and config values into an external module (`parameters.py`) with a structured schema/database (e.g. dataclass or dictionary-based).
2. Populate `parser.add_argument` and other configuration-reading logic dynamically from this definition in a data-driven loop.
3. Support parameter inspection and output via 8 selector flags and 3 output format options:
   - **8 Selector flags**:
     - `--show-config` / `--show-nonconfig` (or `show-nonconfig`)
     - `--show-environment` / `--show-noenvironment`
     - `--show-parameters` / `--show-noparameters`
     - `--show-defaults` / `--show-nondefaults`
   - **Output formats**:
     - `--as-parameters`
     - `--as-environment`
     - `--as-natural`
4. Handle proper bash C-quoting (`$'...'`) when values contain characters that break lines (e.g. `\n`, `\r`, unprintable characters, or quotes).
5. State grouping: `--as-...` releases/evaluates all previous `--show-...` parameters, grouped by `--as` and `--show` parameters.

---

## Source Hierarchy & Semantics

In `lama_ole.py`, configuration comes from three tiers:
1. **Config files** (`_ENV_FILE_USER` = `~/.config/lama_ole/lama_ole.env`, `_ENV_FILE_PROJECT` = `./lama_ole.env`).
2. **Environment variables** (`os.environ`, prefix typically `LAMA_OLE_*`).
3. **CLI Program parameters** (argv flags passed to the script, e.g. `--model`, `-t`).

Currently, `load_env_files()` loads keys from the config files into `os.environ` using `os.environ.setdefault()`. This merges tier 1 into tier 2 in `os.environ`. To support distinction between config files and environment variables, the system must retain awareness of which values came from config files versus actual pre-existing shell environment variables.

---

## Requirements Checklist

- [x] External definition module (`parameters.py`).
- [x] Explicit relationships: CLI parameter flags (`--name`, short `-x`), environment variable names (`LAMA_OLE_*`), types, default values, choices, help strings.
- [x] Dynamic loop in `lama_ole.py` to register arguments on `argparse.ArgumentParser`.
- [x] Inspection mechanism: detect current active values and their origin (CLI parameter, environment variable, config file, or default value).
- [x] Selector flags: `--show-config`, `--show-nonconfig`, `--show-environment`, `--show-noenvironment`, `--show-parameters`, `--show-noparameters`, `--show-defaults`, `--show-nondefaults`.
- [x] Output flags: `--as-environment`, `--as-parameters`, `--as-natural`.
- [x] Execution semantics: `--as-...` consumes/releases previous `--show-...` selectors and outputs the matching values formatted accordingly.
- [x] Bash C-quoting (`$'...'`) escaping for special/multiline values.
