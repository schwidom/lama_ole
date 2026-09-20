# 004: Implementation Plan

## 1. Overview of Implementation Steps

To resolve the issue where permissive parsing allows tests with obsolete flags to pass:

1. **Step 1: Refactor `parameters.py` for Strict CLI & Inspection Parsing**
   - Implement strict argument validation in `parse_cli_explicit_params` and `process_inspection_flags`.
   - Ensure `--show` requires a valid operand argument and does not swallow subsequent inspection action flags.
   - Reject any unrecognized `-` or `--` flags in `argv`.
   - Ensure `_output_inspection_group` correctly defines and populates all 8 attribute flags (`has_def`, `has_def_set`, `has_conf`, `has_conf_set`, `has_env`, `has_env_set`, `has_arg`, `has_arg_set`).

2. **Step 2: Update Existing Tests in `tests/test_parameters.py`**
   - Rewrite outdated test cases (`test_inspection_as_parameters`, `test_inspection_as_environment`, `test_inspection_as_natural`, `test_releasing_selectors_between_as_flags`, `test_nonconfig_selector_support`) to use `--show "<script>"` syntax.
   - Verify assertions match the expected output of the evaluated filter script.

3. **Step 3: Add Strictness and Error Handling Unit Tests**
   - Add test cases verifying that passing invalid/obsolete flags (`--show-parameters`, `--show-config`, `--unknown-flag`) raises an error or exits non-zero.
   - Add test cases verifying that missing `--show` arguments (e.g. `--show --as-parameters`) are rejected.
   - Add unit tests covering complex LI interpreter expressions.

4. **Step 4: Verification and Quality Assurance**
   - Run the complete test suite: `python3 tests/run_all_tests.py`.
   - Ensure 100% test pass rate and clean test output.
