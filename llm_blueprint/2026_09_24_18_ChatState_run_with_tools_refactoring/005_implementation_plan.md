# 005: Implementation Plan & Roadmap

## 1. Step-by-Step Implementation Roadmap

The refactoring will be executed in five distinct, verifiable phases.

```
┌─────────────────────────────────────────────────────────────┐
│ Phase 1: Define RunConfig and Integrate into ChatState       │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Phase 2: Complete Codebase-wide Field Migration to config.  │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Phase 3: Refactor run_with_tools() Signature & Access Logic │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Phase 4: Refactor Test Suite & Test Callsites               │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Phase 5: Run Full Test Suite & Sanity Checks                │
└─────────────────────────────────────────────────────────────┘
```

---

### Phase 1: Define `RunConfig` and Compose `ChatState`
1. Create `tool_base/config.py` and implement the `RunConfig` dataclass with all default parameters.
2. In `chat.py`, import `RunConfig` and add a `config` field to `ChatState`.
3. In `lama_ole.py` where `ChatState` is instantiated, instantiate and pass `RunConfig`.

### Phase 2: Full Field Refactoring to `state.config.P`
1. Audit all references to execution-specific fields on `ChatState` across `chat.py` and `lama_ole.py`.
2. Migrate all references to use the nested `state.config` object (e.g., `state.config.model`, `state.config.show_thinking`).

### Phase 3: Update `run_with_tools()` Signature
1. Refactor the `run_with_tools()` function signature to accept `messages`, `loaded_tools`, `backend_tools`, `config`, `state_manager`, and `metrics`.
2. In the body of `run_with_tools()`, update all config parameter lookups to query properties on `config` directly.
3. Update callsites in `chat.py` and `lama_ole.py` to match the new signature.

### Phase 4: Refactor Test Suite
1. Audit all test files calling `run_with_tools()` in the `tests/` directory.
2. Refactor test helper functions (such as `_run_kwargs`) to instantiate and return a `RunConfig` object.
3. Pass `RunConfig` strictly to `run_with_tools()` in all test cases.

### Phase 5: Test Execution & Final Verification
1. Run the full test suite to confirm complete compliance and zero regressions:
   ```bash
   python3 tests/run_all_tests.py
   ```
2. Manually test CLI interaction and REPL operation.

---

## 2. Verification Checklist

- [ ] `RunConfig` dataclass created in `tool_base/config.py`.
- [ ] `ChatState` updated to contain a nested `RunConfig` object (`state.config`).
- [ ] All direct accesses to configuration fields on `state` refactored to `state.config.P`.
- [ ] `run_with_tools()` signature refactored to take `config` strictly.
- [ ] Callsites in `chat.py` and `lama_ole.py` updated to pass `config` strictly.
- [ ] Test helper `_run_kwargs` refactored to construct `RunConfig` objects.
- [ ] Entire test suite (`python3 tests/run_all_tests.py`) runs and passes completely green.
