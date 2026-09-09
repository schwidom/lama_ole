# 005: Testing Strategy — Backend Encapsulation

## Problem Statement

The task requires that:
1. Tests depending on backend-specific libraries live in `tests_<backendname>/` directories.
2. In development, all libraries are available. In production, they may not be.
3. We need a way to **test the correct encapsulation** — verify that the core application doesn't crash when a backend library is missing.

---

## Test Directory Layout

```
tests/                                  # Core tests — no backend dependencies
    test_backend_encapsulation.py       # Proves encapsulation works
    test_backend_factory.py             # Tests factory, registry, creation
    test_echo_backend.py                # Tests EchoMockBackend (no deps)
    test_eliza_backend.py               # Tests ElizaBackend (no deps)
    test_engine_backend_agnostic.py     # Tests engine with mock backend
    ...                                 # Existing tests (unchanged)

tests_ollama/                           # Ollama-specific tests
    __init__.py
    test_ollama_backend.py              # Tests OllamaBackend adapter
    test_ollama_transfer.py             # Tests model transfer logic

tests_llamacpp/                         # llama.cpp-specific tests
    __init__.py
    test_llamacpp_backend.py            # Tests LlamaCppBackend adapter
    test_llamacpp_integration.py        # Integration against running server

tests_openai_compat/                    # OpenAI-compat-specific tests
    __init__.py
    test_openai_compat_backend.py       # Tests OpenAICompatBackend adapter
    test_openai_compat_integration.py   # Integration against running server
```

---

## Opt-In Env-Var Guards

Following the existing pattern from `tests/test_lsp_integration.py` and AGENTS.md:

### tests_ollama/

```python
# tests_ollama/test_ollama_backend.py
_OLLAMA_AVAILABLE = False
try:
    import ollama  # noqa: F401
    _OLLAMA_AVAILABLE = True
except ImportError:
    pass

pytestmark = pytest.mark.skipif(
    not _OLLAMA_AVAILABLE,
    reason="Ollama library not installed; pip install ollama to run these tests",
)
```

### tests_llamacpp/

```python
# tests_llamacpp/test_llamacpp_integration.py
_LLAMACPP_ENABLED = os.environ.get("LAMA_OLE_LLAMACPP_TEST", "") == "1"

pytestmark = pytest.mark.skipif(
    not _LLAMACPP_ENABLED,
    reason="llama.cpp integration tests are opt-in; set LAMA_OLE_LLAMACPP_TEST=1",
)
```

### tests_openai_compat/

```python
# tests_openai_compat/test_openai_compat_integration.py
_OPENAI_COMPAT_ENABLED = os.environ.get("LAMA_OLE_OPENAI_COMPAT_TEST", "") == "1"

pytestmark = pytest.mark.skipif(
    not _OPENAI_COMPAT_ENABLED,
    reason="OpenAI-compat integration tests are opt-in; set LAMA_OLE_OPENAI_COMPAT_TEST=1",
)
```

---

## Core Encapsulation Test

`tests/test_backend_encapsulation.py` — this is the critical test that proves the backend abstraction works correctly.

### Test 1: Core imports succeed without ollama

```python
def test_core_imports_without_ollama():
    """Verify that lama_ole's core modules can be imported
    even when the ollama library is missing."""
    import sys

    # Save and remove ollama from sys.modules
    saved = {}
    for key in list(sys.modules):
        if key == "ollama" or key.startswith("ollama."):
            saved[key] = sys.modules.pop(key)

    # Also block future imports of ollama
    import importlib
    import types

    class OllamaBlocker(types.ModuleType):
        def __getattr__(self, name):
            raise ImportError(
                "Simulated missing 'ollama' library"
            )

    sys.modules["ollama"] = OllamaBlocker("ollama")

    try:
        # These should all succeed
        from backends import create_backend, LlmBackend
        from backends.factory import create_backend
        from backends.registry import BACKEND_REGISTRY, SUPPORTED_BACKENDS
        from backends.base import ChatChunk, ModelInfo, RunningModel

        # Echo and Eliza should work
        echo = create_backend("echo")
        assert echo.name == "echo"

        eliza = create_backend("eliza")
        assert eliza.name == "eliza"

        # Ollama should fail with clear error
        with pytest.raises(ImportError, match="ollama"):
            create_backend("ollama")

    finally:
        # Restore ollama in sys.modules
        sys.modules.pop("ollama", None)
        sys.modules.update(saved)
```

### Test 2: Echo backend chat round-trip

```python
def test_echo_backend_chat_roundtrip():
    """Echo backend echoes user content and can simulate tool calls."""
    from backends import create_backend

    backend = create_backend("echo")
    chunks = list(backend.chat(
        model="mock",
        messages=[{"role": "user", "content": "Hello"}],
    ))
    assert any(c.content == "Hello" for c in chunks)
```

### Test 3: Engine works with mock backend

```python
def test_engine_with_echo_backend():
    """The engine's run_with_tools loop works with any LlmBackend."""
    from backends import create_backend
    from tool_base.engine import run_with_tools

    backend = create_backend("echo")
    # Create tools list (empty for this test)
    response = run_with_tools(
        client=backend,
        model="mock",
        messages=[{"role": "user", "content": "Say hello"}],
        loaded_tools=[],
        backend_tools=None,
        options={},
        keep_alive=None,
        show_thinking=False,
        no_safety_system_prompt=True,
    )
    assert response  # Should get a non-empty response
```

### Test 4: Factory rejects unknown backend

```python
def test_factory_rejects_unknown():
    from backends.factory import create_backend
    with pytest.raises(ValueError, match="Unknown backend 'nonexistent'"):
        create_backend("nonexistent")
```

### Test 5: convert_tools produces correct format

```python
def test_echo_convert_tools():
    """convert_tools produces OpenAI-compatible format."""
    from backends import create_backend
    from tool_base.models import Tool

    backend = create_backend("echo")
    tool = Tool(
        name="test_tool",
        description="A test tool",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "test"}},
            "required": ["query"],
        },
        fn=lambda query: query,
    )
    result = backend.convert_tools([tool])
    assert len(result) == 1
    assert result[0]["type"] == "function"
    assert result[0]["function"]["name"] == "test_tool"
```

---

## How `run_all_tests.py` Discovers Backend Tests

The existing test runner discovers tests in the `tests/` directory. For backend-specific tests:

### Option A: Include `tests_<backend>/` in discovery

Modify `run_all_tests.py` to also discover tests in `tests_ollama/`, `tests_llamacpp/`, etc.:

```python
# In run_all_tests.py
BACKEND_TEST_DIRS = ["tests_ollama", "tests_llamacpp", "tests_openai_compat"]

for subdir in BACKEND_TEST_DIRS:
    path = os.path.join(lama_ole_dir, subdir)
    if os.path.isdir(path):
        _run(
            [sys.executable, "-m", "pytest", path, "-q"],
            f"backend tests ({subdir})",
        )
```

Backend tests that skip due to missing libraries will show as "skipped" in output, not as failures.

### Option B: Separate runner for backend tests

Keep `run_all_tests.py` for core tests only. Backend tests run separately:

```bash
cd lama_ole
python3 -m pytest tests_ollama/ -q       # skips if ollama missing
python3 -m pytest tests_llamacpp/ -q      # skips unless LAMA_OLE_LLAMACPP_TEST=1
python3 -m pytest tests_openai_compat/ -q # skips unless LAMA_OLE_OPENAI_COMPAT_TEST=1
```

### Recommendation

**Option A** — include in the main runner. The opt-in guards ensure backend tests skip gracefully when libraries are missing, keeping the suite green.

---

## Testing Checklist

- [ ] `tests/test_backend_encapsulation.py` proves imports work without `ollama`
- [ ] `tests/test_backend_factory.py` tests factory, registry, error handling
- [ ] `tests/test_echo_backend.py` tests EchoMockBackend (no deps)
- [ ] `tests/test_eliza_backend.py` tests ElizaBackend (no deps)
- [ ] `tests/test_engine_backend_agnostic.py` tests engine with mock backend
- [ ] `tests_ollama/test_ollama_backend.py` tests OllamaBackend adapter
- [ ] `tests_llamacpp/` and `tests_openai_compat/` have integration tests with opt-in guards
- [ ] `python3 tests/run_all_tests.py` stays green (core tests pass, backend tests skip when deps missing)
- [ ] In development env (all deps installed): all tests pass
- [ ] In production env (only core deps): backend tests skip, no failures
