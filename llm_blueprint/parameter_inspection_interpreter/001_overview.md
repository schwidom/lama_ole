# 001: Overview — Fixing Parameter Inspection Parsing Strictness

## 1. Problem Statement

In the commit `2511374daeb4ffc3817f905edda73e5a2db014ae`, a new parameter inspection technique was introduced using a Lisp-like (LI) interpreter (`parameter_inspection_interpreter.py` / `interpret()`) driven by the `--show <script>` CLI option.

However, the argument parser and inspection pipeline in `parameters.py` (`parse_cli_explicit_params` and `process_inspection_flags`) is not strict enough. Specifically:

1. **Obsolete / Unknown Flags are Silently Ignored:**
   When old selector flags (like `--show-parameters`, `--show-config`, `--show-environment`, `--show-defaults`, or invalid flags) are supplied in `argv` along with an `--as-*` flag:
   - `INSPECTION_FLAGS` only contains `["--show", "--as-parameters", "--as-environment", "--as-natural"]`.
   - The old flags are not recognized in `flag_to_spec` and not in `INSPECTION_FLAGS`, so they are simply skipped by `parse_cli_explicit_params()` or treated as positional arguments and ignored.
   - In `process_inspection_flags()`, because no `--show` is encountered, `selector_script` remains `None`.
   - `_output_inspection_group()` treats `selector_script=None` as "no filter", outputting all parameters (CLI args and defaults).
   - As a result, outdated test cases in `tests/test_parameters.py` (e.g. `test_inspection_as_parameters`, `test_inspection_as_environment`, `test_inspection_as_natural`, `test_releasing_selectors_between_as_flags`, `test_nonconfig_selector_support`) still pass assertions even though they pass completely obsolete flags (`--show-parameters`, `--show-config`, etc.).

2. **Inconsistent Handling of `--show` Syntax and Unknown Tokens in Inspection Mode:**
   - If `--show` is passed without an argument before an `--as-*` flag, or followed immediately by another flag, it grabs that next token (which could be `--as-parameters` or `--model`) as the script.
   - Unknown CLI arguments in inspection mode are not validated or rejected, allowing misspelled or obsolete inspection options to silently succeed.

3. **`tests/test_parameters.py` Drift:**
   - Tests were written against the deprecated `--show-*` boolean flags rather than testing the new `--show <script>` interpreter grammar defined in `doc.txt`.
   - Because the parser is permissive, the suite stays green while testing nothing related to the new interpreter logic.

---

## 2. Goals & Key Objectives

1. **Enforce Strictness in Inspection Parsing (`parameters.py`):**
   - Strictly parse `--show <expression>`: ensure `--show` consumes a valid selector expression string argument.
   - Detect and reject unknown flags or unsupported `--show-*` options when running inspection mode, or validate `argv` against the allowed `PARAMETERS` schema.
   - When no `--show` filter is provided, clarify whether all parameters or only explicit arguments should be shown, or require explicit selector expressions.
   - If an unrecognized option or syntax error is provided in `argv`, raise an error or exit with a clear message rather than silently continuing with unfiltered output.

2. **Fix and Update Test Suite (`tests/test_parameters.py`):**
   - Update tests to use the new `--show "<expr>"` syntax (e.g., `--show "arg"`, `--show "(or arg env)"`, `--show "! conf"`).
   - Add negative tests to ensure obsolete flags (like `--show-parameters`) and malformed selector scripts fail as expected.
   - Verify comprehensive coverage of LI grammar features (tokens `def`, `conf`, `env`, `arg`, `s <source>`, `!`, `and`, `or`).

---

## 3. Structure of the Concept Documentation

This concept directory (`./llm_blueprint/parameter_inspection_interpreter/`) contains the following detailed blueprints:

- **`001_overview.md`**: High-level problem definition, goals, and blueprint structure (this document).
- **`002_architecture_and_strictness.md`**: Detailed analysis of parser laxness in `parameters.py`, grammar validation, and strict token processing rules.
- **`003_test_suite_update_and_matrix.md`**: Test refactoring plan for `tests/test_parameters.py` and test matrix for the LI interpreter.
- **`004_implementation_plan.md`**: Step-by-step roadmap for implementing parser strictness and updating tests.
