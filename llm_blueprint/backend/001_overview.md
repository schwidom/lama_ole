# 001: Overview and Requirements Analysis — Flexible Backends

## Context and Goal

`lama_ole` is currently tightly coupled to Ollama. The `ollama` Python library is imported directly in `lama_ole.py`, `engine.py`, and `chat.py`; the `client.chat()` call uses Ollama-specific streaming protocol, tool format, and options (`keep_alive`, `options`); and helper functions like `to_ollama_tools()`, `set_ollama_host()` / `get_ollama_host()` are Ollama-specific.

The goal is to decouple lama_ole from Ollama by introducing a **backend abstraction layer** so that:

1. Multiple LLM backends can run in parallel and be selected at runtime.
2. Ollama becomes just one backend among many.
3. New backends can be added without modifying the core engine.
4. The application can run without any backend installed (no crash, no hard dependency).

---

## Backends to Support

| Backend | Purpose | Dependencies |
|---------|---------|-------------|
| **Ollama** | Primary/default backend (existing) | `ollama` Python library |
| **llama.cpp** | Local inference via llama.cpp server HTTP API | HTTP client only (stdlib `urllib` or `requests` if available) |
| **OpenAI-compatible** | Any OpenAI API-compatible server (vLLM, text-generation-webui, LM Studio, etc.) | HTTP client only |
| **Eliza** | Testing backend — deterministic scripted responses | None |
| **Echo Mock** | Testing backend — echoes input back, supports tool calling | None |

---

## Current Ollama Coupling Points

These are all the locations where Ollama-specific code exists today. Each must be abstracted.

### Direct `ollama` library imports

| File | Line | Usage |
|------|------|-------|
| `lama_ole.py` | 14 | `from ollama import Client` |
| `tool_base/engine.py` | 7 | `from ollama import Tool as OllamaTool` |

### `ollama.Client` usage

| File | Line | Method | Purpose |
|------|------|--------|---------|
| `lama_ole.py` | 358 | `Client(host=host_url)` | Create client |
| `lama_ole.py` | 372 | `client.list()` | List available models |
| `lama_ole.py` | 378 | `client.ps()` | List running models |
| `lama_ole.py` | 387 | `client.generate(model=..., keep_alive=0)` | Stop a model |
| `lama_ole.py` | 397-401 | `Client(host=...)`, `client_src.show()` | Model transfer |
| `lama_ole.py` | 780, 935-942 | `client_dst.create_blob()`, `client_dst.create()` | Model transfer |
| `tool_base/engine.py` | 356 | `client.chat(model=..., messages=..., tools=..., stream=True, options=..., keep_alive=...)` | **Core: streaming chat** |
| `chat.py` | 512 | `state.client.ps()` | Context window detection |
| `chat.py` | 522 | `state.client.show(model=...)` | Context window detection |
| `chat.py` | 948 | `state.client.chat(...)` | Context compaction |

### Tool format conversion

| File | Line | Function |
|------|------|----------|
| `tool_base/engine.py` | 709-750 | `to_ollama_tools()` — converts internal `Tool` objects to `OllamaTool` |
| `chat.py` | 155-164 | `refresh_ollama_tools()` — calls `to_ollama_tools()` |
| `lama_ole.py` | 427 | `to_ollama_tools(loaded_tools)` |

### Ollama-specific response fields used in engine.py

| Field | Where Used | Backend Equivalents |
|-------|-----------|-------------------|
| `chunk.message.thinking` | engine.py:381 | Not available in OpenAI; o1 `reasoning_content` |
| `chunk.message.content` | engine.py:397 | Universal |
| `chunk.message.tool_calls` | engine.py:415 | Universal (but different format) |
| `chunk.prompt_eval_count` | engine.py:368 | Not available in OpenAI |
| `chunk.eval_count` | engine.py:371 | Not available in OpenAI |
| `chunk.eval_duration` | engine.py:373 | Not available in OpenAI |
| `chunk.prompt_eval_duration` | engine.py:375 | Not available in OpenAI |

### Config functions

| File | Function | Purpose |
|------|----------|---------|
| `tool_base/config.py` | `set_ollama_host()` / `get_ollama_host()` | Store Ollama host URL |
| `tools/media_understanding_tools.py` | `get_ollama_host()` | Vision model inference endpoint |

---

## Requirements Checklist

- [x] Abstract interface (`LlmBackend`) that all backends implement.
- [x] Ollama backend wraps existing `ollama.Client` — zero behavioral change.
- [x] llama.cpp backend using HTTP API (`/v1/chat/completions` or `/completion`).
- [x] OpenAI-compatible backend using `/v1/chat/completions`.
- [x] Eliza testing backend with scripted responses.
- [x] Echo mock backend with tool-calling echo capability.
- [x] Factory function to create backends by name, with dynamic import.
- [x] `--backend <name>` CLI flag (default: `ollama`), env var `LAMA_OLE_BACKEND`.
- [x] `--api-key <key>` CLI flag and `LAMA_OLE_API_KEY` env var (optional, applied to all backends).
- [x] `/backend <name>` slash command in chat REPL to switch backends at runtime.
- [x] Graceful degradation: missing backend library → clear error at instantiation, not at import.
- [x] lama_ole runs without any backend installed (help, version, list-params work fine).
- [x] Tool format normalization: internal `Tool` → backend-specific format, and backend response → normalized internal format.
- [x] Streaming response normalization: backend-specific chunks → unified content/thinking/tool_calls/metrics.
- [x] Backend-specific tests in `tests_<backendname>/` directories.
- [x] Encapsulation test that verifies core lama_ole imports succeed when `ollama` is absent.

---

## What Must NOT Change

1. The internal `Tool` dataclass (`tool_base/models.py`) remains the canonical tool representation.
2. The `@tool` decorator and tool registry (`tool_base/registry.py`) are backend-agnostic and stay unchanged.
3. The safety system prompt, plan mode, and entropy checking are backend-agnostic.
4. Message history format in `ChatState.messages` remains a list of `{"role": ..., "content": ..., ...}` dicts (OpenAI-style, which is the most widely compatible).
5. The `run_with_tools()` function in `engine.py` remains the core loop; it calls backend methods instead of `client.chat()` directly.
