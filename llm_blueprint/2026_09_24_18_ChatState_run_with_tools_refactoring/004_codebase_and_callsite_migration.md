# 004: Codebase & Callsite Migration

## 1. Full Field Refactoring (`state.config.P`)

As part of the strict class-based encapsulation, direct attributes on `ChatState` representing execution options are replaced by a nested `config` object (`RunConfig`).

All occurrences across `chat.py` and `lama_ole.py` must be migrated:

```python
# Before
state.model = "gpt-4"
state.show_thinking = True
if state.safe:
    ...

# After
state.config.model = "gpt-4"
state.config.show_thinking = True
if state.config.safe:
    ...
```

---

## 2. Callsite Migration in `chat.py` & `lama_ole.py`

### A. Callsite 1: REPL Turn (`chat.py` line 1131)
**Before:**
```python
run_with_tools(
    client=state.client,
    model=state.model,
    ...
    show_diff=state.show_diff,
)
```

**After:**
```python
run_with_tools(
    messages=state.messages,
    loaded_tools=state.loaded_tools,
    backend_tools=state.backend_tools,
    config=state.config,
    state_manager=state.state_manager,
    metrics=metrics,
)
```

### B. Callsite 2: `/feed` turn (`chat.py` line 1473)
Identical refactoring to pass `messages`, `loaded_tools`, `backend_tools`, `config`, `state_manager`, and `metrics`.

### C. Callsite 3: Interactive Turn (`lama_ole.py` line 617)
Identical refactoring to pass the consolidated `config` object instead of unpacking.

---

## 3. Test Suite Migration

All tests in `tests/` that call `run_with_tools()` must be updated to construct a `RunConfig` object instead of passing individual keyword arguments directly to `run_with_tools()`.

### Legacy Test Callsite Pattern:
```python
run_with_tools(
    client=client,
    model="test",
    messages=messages,
    loaded_tools=[],
    backend_tools=None,
    options={},
    color="never",
)
```

### Refactored Test Callsite Pattern:
```python
from tool_base.config import RunConfig

config = RunConfig(
    client=client,
    model="test",
    options={},
    color="never",
)

run_with_tools(
    messages=messages,
    loaded_tools=[],
    backend_tools=None,
    config=config,
)
```
This migration enforces robust compilation and consistency across both production and test suites.
