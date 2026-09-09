# 002: Architecture — Backend Abstraction Layer

## Directory Structure

```
lama_ole/
├── backends/                          # NEW: Backend abstraction package
│   ├── __init__.py                    # Public re-exports
│   ├── base.py                        # LlmBackend ABC, ChatChunk, ModelInfo, normalized types
│   ├── factory.py                     # create_backend() — dynamic instantiation by name
│   ├── registry.py                    # BACKEND_REGISTRY: name → module path mapping
│   ├── ollama_backend.py              # OllamaBackend — wraps ollama.Client
│   ├── llamacpp_backend.py            # LlamaCppBackend — HTTP to llama.cpp server
│   ├── openai_compat_backend.py       # OpenAICompatBackend — OpenAI /v1/chat/completions
│   ├── eliza_backend.py               # ElizaBackend — deterministic scripted responses
│   ├── echo_backend.py                # EchoMockBackend — echo + tool calling mock
│   └── _compat.py                     # Graceful import helpers (_try_import_ollama, etc.)
├── tool_base/
│   ├── engine.py                      # MODIFIED: use backend methods instead of client.chat()
│   └── config.py                      # MODIFIED: generalize host config, add api_key config
├── chat.py                            # MODIFIED: ChatState uses backend, /backend command
├── lama_ole.py                        # MODIFIED: --backend flag, backend creation via factory
└── tests_<backendname>/               # NEW: per-backend test directories
    ├── __init__.py
    ├── test_ollama_backend.py
    ├── test_llamacpp_backend.py
    ├── test_openai_compat_backend.py
    ├── test_eliza_backend.py
    └── test_echo_backend.py
```

---

## 1. Normalized Types (`backends/base.py`)

All backends return results in these normalized forms. The core engine never touches backend-specific types.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Union


@dataclass
class ChatChunk:
    """One streamed chunk from a backend, normalized to a common shape."""
    content: Optional[str] = None          # Text content (delta for streaming)
    thinking: Optional[str] = None         # Thinking/reasoning text (delta)
    tool_calls: Optional[List[Dict]] = None  # Normalized tool calls
    done: bool = False                     # True on final chunk

    # Metrics (optional — not all backends provide these)
    prompt_eval_count: Optional[int] = None
    eval_count: Optional[int] = None
    eval_duration_ns: Optional[int] = None
    prompt_eval_duration_ns: Optional[int] = None


@dataclass
class ModelInfo:
    """Normalized model metadata."""
    name: str
    size: Optional[int] = None
    context_length: Optional[int] = None
    parameter_size: Optional[str] = None
    quantization: Optional[str] = None
    backend_specific: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RunningModel:
    """Normalized running model info."""
    name: str
    context_length: Optional[int] = None
    backend_specific: Dict[str, Any] = field(default_factory=dict)


class LlmBackend(ABC):
    """Abstract base class for all LLM backends."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Canonical name of this backend (e.g. 'ollama', 'openai_compat')."""
        ...

    @property
    @abstractmethod
    def supports_thinking(self) -> bool:
        """Whether this backend supports thinking/reasoning output."""
        ...

    @abstractmethod
    def chat(
        self,
        model: str,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        stream: bool = True,
        options: Optional[Dict] = None,
        keep_alive: Optional[Any] = None,
    ) -> Iterator[ChatChunk]:
        """Stream a chat completion. Yields ChatChunk objects."""
        ...

    @abstractmethod
    def list_models(self) -> List[ModelInfo]:
        """List available models on this backend."""
        ...

    @abstractmethod
    def list_running(self) -> List[RunningModel]:
        """List currently loaded/running models."""
        ...

    @abstractmethod
    def show_model(self, model: str) -> Optional[ModelInfo]:
        """Get details about a specific model."""
        ...

    @abstractmethod
    def stop_model(self, model: str) -> bool:
        """Stop/unload a model. Returns True on success."""
        ...

    @abstractmethod
    def convert_tools(self, tools: List[Any]) -> Optional[List[Dict]]:
        """Convert internal Tool objects to this backend's tool format."""
        ...

    def transfer_model(self, model: str, source: Any, dest: Any) -> bool:
        """Transfer a model between instances. Default: not supported."""
        raise NotImplementedError(
            f"Model transfer is not supported by the {self.name} backend."
        )

    def close(self) -> None:
        """Clean up resources. Called on shutdown."""
        pass
```

### Design Rationale

- **`ChatChunk` as normalized streaming unit**: Every backend adapter translates its native streaming protocol into `ChatChunk`. The engine never sees Ollama `Chunk` or OpenAI `Choice` objects.
- **Tool format is `List[Dict]`**: The OpenAI tool-calling JSON Schema format is the lingua franca — it's the most widely supported format. Ollama accepts it too. Backends that need a different format (Ollama's typed `OllamaTool`) convert internally.
- **`keep_alive` passes through**: Ollama uses this; other backends ignore it (the parameter is typed `Optional[Any]` and each backend documents whether it uses it).
- **`convert_tools()` lives on the backend**: Each backend knows its own tool format. The engine calls `backend.convert_tools(loaded_tools)` instead of `to_ollama_tools()`.

---

## 2. Backend Registry (`backends/registry.py`)

Maps backend names to their module paths. This is a static table — no dynamic discovery needed.

```python
BACKEND_REGISTRY = {
    "ollama":          "backends.ollama_backend.OllamaBackend",
    "llamacpp":        "backends.llamacpp_backend.LlamaCppBackend",
    "openai_compat":   "backends.openai_compat_backend.OpenAICompatBackend",
    "eliza":           "backends.eliza_backend.ElizaBackend",
    "echo":            "backends.echo_backend.EchoMockBackend",
}

DEFAULT_BACKEND = "ollama"
SUPPORTED_BACKENDS = list(BACKEND_REGISTRY.keys())
```

---

## 3. Backend Factory (`backends/factory.py`)

Creates backend instances by name with lazy import.

```python
def create_backend(
    name: str,
    host: Optional[str] = None,
    api_key: Optional[str] = None,
    **kwargs,
) -> LlmBackend:
    """Create a backend by name. Raises ValueError if unknown.

    Backend libraries are imported lazily — a missing library only fails
    when that specific backend is requested, not at application startup.
    """
    if name not in BACKEND_REGISTRY:
        raise ValueError(
            f"Unknown backend '{name}'. "
            f"Available: {', '.join(SUPPORTED_BACKENDS)}"
        )
    class_path = BACKEND_REGISTRY[name]
    module_path, class_name = class_path.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    return cls(host=host, api_key=api_key, **kwargs)
```

**Key behavior**: `importlib.import_module("backends.ollama_backend")` only fails if `ollama` is not installed AND someone tries to use the ollama backend. If they use `openai_compat`, the `ollama` import never happens.

---

## 4. Backend Implementations

### 4a. OllamaBackend (`backends/ollama_backend.py`)

Thin adapter around `ollama.Client`. This is the **zero-regression backend** — all existing behavior is preserved.

```python
class OllamaBackend(LlmBackend):
    def __init__(self, host=None, api_key=None, **kwargs):
        from ollama import Client  # lazy import — only fails if ollama used
        self._client = Client(host=host or "http://localhost:11434")

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def supports_thinking(self) -> bool:
        return True

    def chat(self, model, messages, tools=None, stream=True, options=None, keep_alive=None):
        # Convert internal tools to Ollama format
        ollama_tools = self._to_ollama_tools(tools) if tools else None
        native_stream = self._client.chat(
            model=model, messages=messages, tools=ollama_tools,
            stream=stream, options=options or {}, keep_alive=keep_alive,
        )
        for chunk in native_stream:
            msg = chunk.message
            yield ChatChunk(
                content=msg.content,
                thinking=getattr(msg, "thinking", None),
                tool_calls=self._normalize_tool_calls(msg.tool_calls) if msg.tool_calls else None,
                done=False,
                prompt_eval_count=getattr(chunk, "prompt_eval_count", None),
                eval_count=getattr(chunk, "eval_count", None),
                eval_duration_ns=getattr(chunk, "eval_duration", None),
                prompt_eval_duration_ns=getattr(chunk, "prompt_eval_duration", None),
            )
        yield ChatChunk(done=True)

    def convert_tools(self, tools):
        return self._to_ollama_tools(tools)

    def list_models(self):
        resp = self._client.list()
        return [ModelInfo(name=m.name, ...) for m in resp.models]

    def list_running(self):
        resp = self._client.ps()
        return [RunningModel(name=m.model, ...) for m in resp.models]

    def show_model(self, model):
        r = self._client.show(model=model)
        # Parse num_ctx from parameters...
        return ModelInfo(name=model, context_length=...)

    def stop_model(self, model):
        self._client.generate(model=model, keep_alive=0)
        return True
```

The `to_ollama_tools()` function moves from `engine.py` into `OllamaBackend` as a private method. Other backends have their own format converters.

### 4b. LlamaCppBackend (`backends/llamacpp_backend.py`)

Uses llama.cpp's server HTTP API. Two API styles are supported:
- **OpenAI-compatible** (`/v1/chat/completions`) — if the llama.cpp server was started with `--chat`
- **Native** (`/completion`) — llama.cpp native completion API

```python
class LlamaCppBackend(LlmBackend):
    def __init__(self, host=None, api_key=None, **kwargs):
        self._base_url = (host or "http://localhost:8080").rstrip("/")

    def chat(self, model, messages, tools=None, stream=True, options=None, keep_alive=None):
        # Uses /v1/chat/completions with stream=True
        # Converts tool format to OpenAI function-calling schema
        # Yields ChatChunk from SSE events
        ...

    def convert_tools(self, tools):
        # llama.cpp accepts OpenAI function-calling format directly
        return [self._tool_to_openai_format(t) for t in tools]
```

### 4c. OpenAICompatBackend (`backends/openai_compat_backend.py`)

Covers any server exposing OpenAI-compatible `/v1/chat/completions` (vLLM, LM Studio, text-generation-webui, etc.).

```python
class OpenAICompatBackend(LlmBackend):
    def __init__(self, host=None, api_key=None, **kwargs):
        self._base_url = (host or "http://localhost:11434").rstrip("/")
        self._api_key = api_key  # Bearer token

    def chat(self, model, messages, tools=None, stream=True, options=None, keep_alive=None):
        # POST /v1/chat/completions with stream=True
        # SSE parsing for chunks
        # Tool calls in OpenAI format (choices[0].delta.tool_calls)
        # Thinking: o1 models have reasoning_content; others don't support it
        ...
```

**API key handling**: The `api_key` parameter from `--api-key` or `LAMA_OLE_API_KEY` is passed as `Authorization: Bearer <key>` header. Ollama and llama.cpp backends ignore it.

### 4d. ElizaBackend (`backends/eliza_backend.py`)

Deterministic scripted backend for testing. Accepts a script of predefined responses.

```python
class ElizaBackend(LlmBackend):
    def __init__(self, host=None, api_key=None, script=None, **kwargs):
        self._script = script or []

    def chat(self, model, messages, tools=None, stream=True, options=None, keep_alive=None):
        # Returns scripted responses in order
        # Supports tool-call scripted responses for integration testing
        ...
```

### 4e. EchoMockBackend (`backends/echo_backend.py`)

Echoes back the user's last message. Supports tool calling by detecting tool-call triggers in the input.

```python
class EchoMockBackend(LlmBackend):
    def chat(self, model, messages, tools=None, stream=True, options=None, keep_alive=None):
        last_user = next(m for m in reversed(messages) if m["role"] == "user")
        # If message contains a tool-call trigger, yield a tool_call chunk
        # Otherwise echo the content back as assistant response
        ...
```

---

## 5. Engine Changes (`tool_base/engine.py`)

### Before (Ollama-coupled)

```python
from ollama import Tool as OllamaTool

def run_with_tools(client, model, messages, loaded_tools, ollama_tools, ...):
    ...
    stream = client.chat(model=model, messages=messages, tools=tools_for_request, ...)
    for chunk in stream:
        msg = chunk.message
        if msg.thinking: ...
        if msg.content: ...
        if msg.tool_calls: ...
```

### After (backend-agnostic)

```python
def run_with_tools(client, model, messages, loaded_tools, backend_tools, ...):
    """
    Args:
        client: LlmBackend instance (replaces raw ollama.Client)
        backend_tools: pre-converted tool format for this backend (List[Dict])
    """
    ...
    for chunk in client.chat(model=model, messages=messages, tools=backend_tools, ...):
        if chunk.thinking: ...
        if chunk.content: ...
        if chunk.tool_calls: ...
```

### Parameter renames

| Old | New | Reason |
|-----|-----|--------|
| `ollama_tools` | `backend_tools` | Backend-agnostic naming |
| `ollama_websearch` | `websearch` | Not Ollama-specific concept |
| `to_ollama_tools()` call | `backend.convert_tools()` | Each backend handles its own format |

---

## 6. ChatState Changes (`chat.py`)

```python
@dataclass
class ChatState:
    client: object           # Now typed as LlmBackend (but kept as object for flexibility)
    backend_name: str = "ollama"  # NEW: current backend name
    ...
    # ollama_tools renamed:
    backend_tools: object = None  # was: ollama_tools

    def refresh_backend_tools(self) -> None:
        """Recompute backend tool list from loaded_tools."""
        self.backend_tools = (
            self.client.convert_tools(self.loaded_tools)
            if self.loaded_tools else None
        )
```

### New `/backend` slash command

```
/backend              Show current backend and available backends
/backend ollama       Switch to Ollama backend
/backend echo         Switch to Echo mock backend
```

Switching the backend requires:
1. `create_backend(new_name, host=..., api_key=...)`
2. Replacing `state.client` with the new backend
3. Replacing `state.model` with a model name valid for the new backend (prompt user)
4. Calling `state.refresh_backend_tools()`

---

## 7. CLI Changes (`lama_ole.py`, `parameters.py`)

New parameter specs in `parameters.py`:

```python
ParameterSpec(
    name="backend",
    flags=["--backend"],
    env_var="LAMA_OLE_BACKEND",
    default="ollama",
    choices=SUPPORTED_BACKENDS,  # ["ollama", "llamacpp", "openai_compat", "eliza", "echo"]
    help="LLM backend to use for inference",
),
ParameterSpec(
    name="api_key",
    flags=["--api-key"],
    env_var="LAMA_OLE_API_KEY",
    default=None,
    help="API key for backends that require authentication",
),
```

In `lama_ole.py`, replace:
```python
# OLD:
client = Client(host=host_url)

# NEW:
from backends.factory import create_backend
backend = create_backend(
    name=args.backend,
    host=host_url,
    api_key=args.api_key,
)
```

Model transfer (`--transfer`) is Ollama-only. When `--transfer` is used, it implicitly uses the Ollama backend for transfer operations regardless of `--backend`.

---

## 8. Config Generalization (`tool_base/config.py`)

```python
# Generalized backend config
_BACKEND_NAME = "ollama"
_BACKEND_HOST = "http://localhost:11434"
_API_KEY: Optional[str] = None

def set_backend_config(name: str, host: str, api_key: Optional[str] = None):
    global _BACKEND_NAME, _BACKEND_HOST, _API_KEY
    _BACKEND_NAME = name
    _BACKEND_HOST = host
    _API_KEY = api_key

def get_backend_host() -> str:
    return _BACKEND_HOST

def get_api_key() -> Optional[str]:
    return _API_KEY

# Backward-compatible aliases
def set_ollama_host(host: str):
    set_backend_config(_BACKEND_NAME, host, _API_KEY)

def get_ollama_host() -> str:
    return _BACKEND_HOST
```

This preserves backward compatibility for `tools/media_understanding_tools.py` which calls `get_ollama_host()`. Over time, tool modules should migrate to `get_backend_host()`.
