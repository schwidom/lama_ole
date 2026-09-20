# 003: Test Suite Refactoring & Test Matrix

## 1. Outdated Tests in `tests/test_parameters.py`

The following tests in `tests/test_parameters.py` currently pass obsolete `--show-*` flags and need to be rewritten to test the new interpreter grammar:

| Test Name | Old Usage / Defect | New Expected Behavior with `--show "<expr>"` |
|---|---|---|
| `test_inspection_as_parameters` | Uses `["--show-parameters", "--as-parameters", ...]` | Use `["--show", "arg", "--as-parameters", ...]` to test selecting parameters with CLI arguments allowed/set. |
| `test_inspection_as_environment` | Uses `["--show-parameters", "--as-environment", ...]` | Use `["--show", "arg", "--as-environment", ...]` or `["--show", "s arg", ...]` |
| `test_inspection_as_natural` | Uses `["--show-environment", "--show-parameters", "--as-natural", ...]` | Use `["--show", "(or env arg)", "--as-natural", ...]` |
| `test_releasing_selectors_between_as_flags` | Uses `--show-environment --as-environment --show-parameters --as-parameters` | Use `--show "s env" --as-environment --show "s arg" --as-parameters` to verify grouping and reset between `--as-*` flags. |
| `test_nonconfig_selector_support` | Uses `["--show-config", "show-nonconfig", "--show-parameters", ...]` | Test negated expressions like `["--show", "(and arg ! conf)", ...]` or `["--show", "! conf", ...]`. |

---

## 2. New Test Cases for Strictness & Parser Error Handling

New test functions to add to `tests/test_parameters.py`:

1. **`test_strictness_rejects_obsolete_show_flags()`**:
   - Assert that invoking `process_inspection_flags` with old flags like `["--show-parameters", "--as-parameters"]` fails or raises an error / exits non-zero.

2. **`test_strictness_missing_show_argument()`**:
   - Assert that `["--show", "--as-parameters"]` raises a syntax/argument error because `--show` was not given an expression.

3. **`test_strictness_rejects_unknown_flags()`**:
   - Assert that `["--unknown-flag", "--as-parameters"]` fails.

4. **`test_interpreter_syntax_error_handling()`**:
   - Assert that malformed expressions like `["--show", "(and arg", "--as-parameters"]` or `["--show", "s", "--as-parameters"]` exit with error code 1 / stderr message.

---

## 3. Interpreter Grammar Test Matrix

A comprehensive test suite for the interpreter expressions in inspection mode:

| Expression | Attributes Set | Expected Evaluation |
|---|---|---|
| `"def"` | `{"has_def"}` | `True` |
| `"! def"` | `{"has_def"}` | `False` |
| `"env"` | `{"has_env"}` | `True` |
| `"s env"` | `{"has_env"}` (not set) | `False` |
| `"s env"` | `{"has_env", "has_env_set"}` | `True` |
| `"(and def conf)"` | `{"has_def", "has_conf"}` | `True` |
| `"(and def conf)"` | `{"has_def"}` (missing conf) | `False` |
| `"(or arg env)"` | `{"has_arg"}` | `True` |
| `"(and s env def ! conf)"` | `{"has_env_set", "has_def"}` | `True` |
