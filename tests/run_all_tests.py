#!/usr/bin/env python3
"""Run the full lama_ole test suite.

This helper runs BOTH test frameworks used in ``tests/``:

  1. ``python3 -m unittest discover -s tests -p "test_*.py"``
     -> unittest-style files (``test_edit_tools.py``, ``test_true.py``).
  2. ``python3 -m pytest tests/ -q``
     -> the full suite (pytest also collects unittest classes, so nothing
        is skipped).

Backend-specific test directories (``tests/tests_<backendname>/``) are
opt-in: they are only included when the corresponding env var
``LAMA_OLE_TEST_<BACKENDNAME>`` is set to ``1``.  Disabled directories
are passed to pytest via ``--ignore``.  unittest discover still finds the
files, but the test modules use ``@unittest.skipUnless`` to skip
themselves when the env var is absent.

Usage (from ``lama_ole/``):

    python3 tests/run_all_tests.py
    python3 tests/run_all_tests.py -v      # verbose unittest output

Exits with a non-zero status if any test run fails.
"""

import glob
import os
import subprocess
import sys

current_file = os.path.abspath(__file__)
lama_ole_dir = os.path.abspath(os.path.join(os.path.dirname(current_file), ".."))
if lama_ole_dir not in sys.path:
    sys.path.insert(0, lama_ole_dir)

TESTS_DIR = os.path.join(lama_ole_dir, "tests")


def _discover_backend_test_dirs():
    """Find ``tests/tests_<backendname>/`` directories.

    Returns a list of ``(abs_dir_path, env_var_name, enabled)`` tuples.
    ``enabled`` is True when the env var is set to ``"1"``.
    """
    results = []
    for entry in sorted(glob.glob(os.path.join(TESTS_DIR, "tests_*"))):
        if not os.path.isdir(entry):
            continue
        suffix = os.path.basename(entry)[len("tests_"):]  # e.g. "openai_compat"
        env_var = "LAMA_OLE_TEST_%s" % suffix.upper()
        enabled = os.environ.get(env_var, "") == "1"
        results.append((entry, env_var, enabled))
    return results


def _run(cmd, label):
    print("=" * 72)
    print("### %s" % label)
    print("=" * 72)
    result = subprocess.run(cmd, cwd=lama_ole_dir)
    print()
    return result.returncode


def main():
    verbose = "-v" in sys.argv[1:] or "--verbose" in sys.argv[1:]

    backend_dirs = _discover_backend_test_dirs()

    # --- unittest discover ---
    unittest_cmd = [
        sys.executable, "-m", "unittest", "discover",
        "-s", TESTS_DIR, "-p", "test_*.py",
    ]
    if verbose:
        unittest_cmd.append("-v")

    # --- pytest ---
    pytest_cmd = [sys.executable, "-m", "pytest", TESTS_DIR, "-q"]
    for dir_path, env_var, enabled in backend_dirs:
        if not enabled:
            pytest_cmd.extend(["--ignore", dir_path])

    # --- report ---
    if backend_dirs:
        enabled_names = [os.path.basename(d) for d, _, e in backend_dirs if e]
        skipped_names = [os.path.basename(d) for d, _, e in backend_dirs if not e]
        if enabled_names:
            print("Backend test dirs ENABLED: %s" % ", ".join(enabled_names))
        if skipped_names:
            print("Backend test dirs SKIPPED: %s" % ", ".join(skipped_names))
        print()

    returncode = 0
    returncode |= _run(unittest_cmd, "unittest-style tests (unittest discover)")
    returncode |= _run(pytest_cmd, "full suite (pytest, includes unittest classes)")

    if returncode == 0:
        print("ALL TEST SUITES PASSED.")
    else:
        print("SOME TESTS FAILED -- see output above.")
    return returncode


if __name__ == "__main__":
    sys.exit(main())
