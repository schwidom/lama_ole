# 007: Groq Backend Implementation Plan

## Overview & Background

Groq provides high-throughput, low-latency LLM inference via its LPU (Language Processing Unit) architecture. While Groq exposes an endpoint at `https://api.groq.com/openai/v1` modeled after OpenAI's REST API, **it cannot be treated as a direct drop-in for the generic `openai_compat` backend** due to several critical differences and constraints in behavior, defaults, options, and reasoning formatting.

This plan details why Groq requires a dedicated backend (`GroqBackend`, registry name `"groq"`), the exact differences from `openai_compat`, the architectural design, and the step-by-step implementation and testing strategy.

---

## 1. Why Groq Cannot Be Accessed Directly by `openai_compat`

The existing `OpenAICompatBackend` (`backends/openai_compat_backend.py`) makes generic assumptions that fail or cause HTTP 400 Bad Request errors against Groq's API:

### 1.1 Temperature Clamping & Zero-Value Restrictions
- In OpenAI and generic endpoints, `temperature=0.0` is standard for deterministic outputs.
- On Groq, `temperature=0` is strictly converted to `1e-8`, and some models / parameters reject values `<= 0`. Groq recommends float values in the range `(0.0, 2.0]`. If `temperature=0` is sent verbatim or unsupported edge values are supplied, errors occur.

### 1.2 Unsupported OpenAI Parameters (Strict 400 Rejections)
Generic OpenAI-compatible clients often forward standard parameters. Groq strictly rejects (HTTP 400) requests containing any of the following:
- `logprobs` (not supported on current models)
- `logit_bias` (not supported)
- `top_logprobs` (not supported)
- `messages[].name` (strict validation failure)
- `n != 1` (only `n=1` is supported)
- `frequency_penalty` and `presence_penalty` (not yet supported across most models)

### 1.3 Reasoning Tokens & Thinking Protocol
- `openai_compat` looks for `delta.reasoning_content` (the convention used by OpenAI o1/o3 or DeepSeek-R1 proxies).
- **Groq uses a distinct reasoning convention:**
  - Non-GPT-OSS models (e.g. `qwen/qwen3.6-27b`): Groq supports `reasoning_format` (`"parsed"`, `"raw"`, `"hidden"`). When `parsed`, reasoning comes in `message.reasoning` / `delta.reasoning`. When `raw`, reasoning is embedded in `<think>...</think>` tags in `delta.content`.
  - Crucially: Groq **returns an HTTP 400 error** if `reasoning_format="raw"` is used while tool use or JSON mode is active. In tool-use mode, `reasoning_format` must be set to `"parsed"` or `"hidden"`.
  - GPT-OSS models (e.g. `openai/gpt-oss-20b`, `openai/gpt-oss-120b`): do not support `reasoning_format`, but instead use `include_reasoning` (boolean) and stream reasoning in `delta.reasoning`.
  - `openai_compat` does not negotiate `reasoning_format` or `include_reasoning` and only reads `delta.reasoning_content`, missing Groq's `delta.reasoning` and failing to parse raw `<think>` streaming deltas.

### 1.4 Max Tokens Parameter Naming
- Groq deprecates `max_tokens` in favor of `max_completion_tokens`. While some backwards-compatibility exists, reasoning models require `max_completion_tokens` so that reasoning budget + completion budget are accounted for correctly.

### 1.5 Host & Default URL Differences
- `openai_compat` defaults to `http://localhost:443` or `https://localhost:443` via `normalize_host` if no host is given.
- Groq is a remote cloud service whose standard base URL is `https://api.groq.com/openai`. When using `normalize_host(host, "groq")`, the default host must resolve to `https://api.groq.com/openai`.

---

## 2. Architecture & Design

### 2.1 Backend Specification

| Property | Value |
|---|---|
| Backend Name | `groq` |
| Class Name | `GroqBackend` (`backends/groq_backend.py`) |
| Inherits From | `LlmBackend` (or `OpenAICompatBackend` base with custom overrides) |
| Default Base URL | `https://api.groq.com/openai` |
| Default Port / Scheme | Port 443, Scheme `https` |
| Auth Header | `Authorization: Bearer <GROQ_API_KEY>` |
| Environment Variables | `GROQ_API_KEY`, `LAMA_OLE_API_KEY`, `LAMA_OLE_HOST` |
| Dependencies | `urllib` (Standard library only — zero external package dependencies) |
| `supports_keep_alive` | `False` |
| `supports_thinking` | `True` (maps `delta.reasoning` & `<think>` streams to `ChatChunk.thinking`) |

### 2.2 Host Normalization (`backends/_compat.py`)

Update `BACKEND_DEFAULT_PORTS` and `BACKEND_DEFAULT_SCHEMES`:

```python
BACKEND_DEFAULT_PORTS = {
    "ollama": 11434,
    "llamacpp": 8080,
    "openai_compat": 443,
    "groq": 443,
    "eliza": 80,
    "echo": 80,
}

BACKEND_DEFAULT_SCHEMES = {
    "ollama": "http",
    "llamacpp": "http",
    "openai_compat": "https",
    "groq": "https",
    "eliza": "http",
    "echo": "http",
}
```

And in `normalize_host`: when `backend_name == "groq"` and `host is None`, return `https://api.groq.com/openai`.

### 2.3 Option Mapping & Message Sanitization

1. **Option Filter / Mapper:**
   - Map `num_predict` / `max_tokens` → `max_completion_tokens`.
   - Map `temperature`: if `temperature <= 0`, clamp to `1e-5` (or minimum valid float `> 0`).
   - Discard `frequency_penalty`, `presence_penalty`, `logprobs`, `logit_bias`, `top_logprobs`.
   - Pass through `top_p`, `seed`, `stop`.

2. **Message Sanitization (`_sanitize_messages`):**
   - Strip any `name` property from messages (`messages[].name` causes a 400 on Groq).
   - Strip internal lama_ole fields (`thinking`, `timestamp`, `tool_name`, `compacted`, etc.).
   - Merge multiple system prompts into a single leading system prompt.
   - Maintain `tool_call_id` pairing on `role: "tool"` messages.

3. **Reasoning & Tool Use Request Handling:**
   - If tools are provided (`tools` is non-empty):
     - For models supporting `reasoning_format` (e.g. Qwen): explicitly send `reasoning_format="parsed"` to prevent 400 error.
     - For GPT-OSS models: send `include_reasoning=True`.
   - If no tools and streaming: default to `reasoning_format="parsed"` or extract `<think>` tokens if in raw mode.

4. **SSE Stream Processing (`chat` loop):**
   - Extract `delta.content` → yield `ChatChunk(content=...)`.
   - Extract `delta.reasoning` or `delta.reasoning_content` → yield `ChatChunk(thinking=...)`.
   - Handle inline `<think>...</think>` tags if emitted by non-parsed reasoning streams.
   - Accumulate `delta.tool_calls` across streaming chunks until `finish_reason == "tool_calls"`.
   - Extract `usage.prompt_tokens` and `usage.completion_tokens` for metrics.

---

## 3. Implementation Steps

### Phase 1: Registry & Factory Plumbing
1. **`backends/_compat.py`**:
   - Register default host `https://api.groq.com/openai`, default port `443`, scheme `https`.
2. **`backends/registry.py`**:
   - Add `"groq": "backends.groq_backend.GroqBackend"` to `BACKEND_REGISTRY`.
3. **`parameters.py`**:
   - Ensure `--backend groq` is accepted and documented in parameter choices.
   - Support `GROQ_API_KEY` fallback if `LAMA_OLE_API_KEY` / `--api-key` is not specified.

### Phase 2: GroqBackend Implementation (`backends/groq_backend.py`)
1. Subclass `LlmBackend` (or inherit common HTTP/SSE mechanisms from `OpenAICompatBackend`).
2. Implement custom `_sanitize_messages()` without `name` fields.
3. Implement `chat()` with:
   - Base URL routing to `<host>/v1/chat/completions`.
   - Option mapping and validation (`max_completion_tokens`, temperature clamping).
   - Dynamic `reasoning_format="parsed"` injection when tools are present.
   - Streaming SSE reader handling `delta.reasoning` alongside `delta.content` and `delta.tool_calls`.
4. Implement `list_models()`:
   - Call `GET <host>/v1/models` using `_headers()`.
   - Parse `data` array into `List[ModelInfo]`.
5. Implement `show_model(model)`:
   - Call `GET <host>/v1/models/{model}` and extract `context_window` metadata into `ModelInfo.context_length`.
6. Implement `convert_tools()`:
   - Convert internal `Tool` definitions using `convert_tools_to_openai()`.

### Phase 3: Testing & Verification
1. **Unit Tests (`tests/test_groq_backend.py`)**:
   - Test message sanitization (removal of `name`, merging of system messages).
   - Test temperature conversion when `temperature=0`.
   - Test option mapping (`max_tokens` → `max_completion_tokens`).
   - Test tool calling request body (ensuring `reasoning_format="parsed"` is enforced when tools are attached).
   - Test SSE parsing with `delta.reasoning` and tool calls accumulation using mock SSE payloads.
2. **Encapsulation & Factory Tests (`tests/test_backend_encapsulation.py`, `tests/test_backend_factory.py`)**:
   - Verify `create_backend("groq", api_key="test")` works without third-party libraries installed.
   - Verify proper error reporting when API keys or network requests fail.
3. **Opt-in Integration Tests (`tests/tests_groq/test_groq_integration.py`)**:
   - Guarded by `LAMA_OLE_TEST_GROQ=1` and `GROQ_API_KEY`.
   - Test real text generation, streaming reasoning, and tool calling against Groq's live API.

---

## 4. Documentation & CLI Updates

1. **`llm_blueprint/backend/001_overview.md`**:
   - List `groq` among the supported pluggable backends.
2. **`README.md` & `AGENTS.md`**:
   - Document `--backend groq` usage and `GROQ_API_KEY` configuration.
3. **`chat.py`**:
   - Ensure `/backend groq` switches cleanly in the REPL.
