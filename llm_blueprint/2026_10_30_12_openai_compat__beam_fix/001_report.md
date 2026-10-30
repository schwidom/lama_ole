# 001: openai_compat backend — chat-mode fallback and thinking/output confusion

Date: 2026-10-30
Scope: `lama_ole/backends/openai_compat_backend.py` (primary), `lama_ole/tool_base/engine.py` (consumer), `lama_ole/backends/groq_backend.py` (reference implementation), `lama_ole/tests/test_openai_compat.py` (tests). Target model family: Reflection Beam (501B MoE, served via vLLM/SGLang OpenAI-compatible endpoints).

## 1. Symptoms

When `--backend openai_compat` is selected (the path used to talk to vLLM / SGLang / LM Studio / TGI / …, and the path that will be used for Reflection Beam), two failure modes are reported:

1. **Frequent fall-back into chat mode.** A turn that should execute tools instead ends as a final answer and returns control to the REPL/one-shot prompt. Tool rounds are skipped; the model just "chats".
2. **Thinking and output are not distinguished.** Reasoning that the model produces is rendered and stored as ordinary assistant output; conversely, in some configurations the whole response is treated as output and no thinking block is ever shown. The engine's state machine (`THINKING` → `OUTPUTTING`) never (or wrongly) transitions.

## 2. Root-cause analysis

### 2.1 Reasoning field-name mismatch (primary cause of "treats all as output")

`OpenAICompatBackend.chat()` extracts reasoning from exactly one delta key:

```python
# backends/openai_compat_backend.py
content = delta.get("content")
reasoning = delta.get("reasoning_content")
if content:
    yield ChatChunk(content=content, done=False)
if reasoning:
    yield ChatChunk(thinking=reasoning, done=False)
```

OpenAI-compatible servers do **not** agree on the reasoning field name:

| Server / parser | Reasoning delta key |
|---|---|
| OpenAI o1/o3 | `reasoning_content` |
| Groq (parsed) | `reasoning` (and `reasoning_content` on some models) |
| vLLM (with `--reasoning-parser`) | `reasoning_content` **or** `reasoning`, depending on parser/version |
| SGLang Beam (`--reasoning-parser beam`) | typically `reasoning_content`, but `reasoning` is also emitted by some builds |
| Servers without a reasoning parser | reasoning stays **inside** `content`, wrapped in `<think>…</think>` (or `<thought>…</thought>`) tags |

Because only `reasoning_content` is read, any server that uses `reasoning` (or inline tags) causes the reasoning to be either **dropped entirely** (no chunk yielded → empty turn → chat fallback) or **misclassified as `content`** (rendered/stored as output). This is the direct cause of both symptoms.

By contrast, `GroqBackend.chat()` already does the right thing:

```python
reasoning = delta.get("reasoning") or delta.get("reasoning_content")
```

and additionally parses inline `<think>…</think>` blocks inside `content`, splitting them into `ChatChunk(thinking=…)` / `ChatChunk(content=…)`. `OpenAICompatBackend` has none of this, so it is strictly less capable than the Groq adapter it shares a protocol with.

### 2.2 Chunk emission order (thinking after content)

In `OpenAICompatBackend.chat()`, within a single SSE event that carries both fields, `content` is yielded **before** `reasoning`:

```python
if content:
    yield ChatChunk(content=content, done=False)
if reasoning:
    yield ChatChunk(thinking=reasoning, done=False)
```

`run_with_tools()` drives a state machine off the order of chunks:

```python
# tool_base/engine.py
if thinking:
    ...
    if not think_state:
        think_state = True
        state_manager.transition_to(ExecutionState.THINKING)
...
if content:
    if think_state:
        think_state = False
        state_manager.transition_to(ExecutionState.OUTPUTTING)
        ...
```

A content chunk arriving before the thinking chunk flips the state to `OUTPUTTING` first; the subsequent thinking chunk then flips it back to `THINKING`. On servers that batch both fields into one delta (common for the first chunk), this produces an `OUTPUTTING → THINKING` regression and the reasoning is printed/stored as if it were output. Groq avoids this by yielding reasoning first.

### 2.3 No inline reasoning-tag handling

`OpenAICompatBackend` never inspects `content` for `<think>…</think>`, `<thought>…</thought>`, or Qwen3-style `<|begin_of_thought|>`/`<|end_of_thought|>` tokens. Servers that do not run a reasoning parser (the default for many self-hosted endpoints, and a realistic configuration for Beam) emit reasoning inline in `content`. The backend passes it straight through as `ChatChunk(content=…)`, so the engine treats the entire reasoning as output and never enters `THINKING`. The engine's own `_clean_stream_text()` / `_TEXT_DELIM_RE` scrubber runs later, but by then the chunk has already been classified as content and the state machine has already committed to `OUTPUTTING`.

### 2.4 Tool-call format mismatch (cause of "falls back into chat mode")

The engine promotes text-embedded tool calls to real structured calls, but only for one specific grammar:

```python
# tool_base/engine.py
_TEXT_CALL_RE = re.compile(r"(?<![A-Za-z0-9_])call:([A-Za-z_][A-Za-z0-9_.:-]*)(\{)")
```

i.e. Qwen3-style `call:name{…}` directives. Reflection Beam uses a **dedicated XML tool-call grammar** (SGLang: `--tool-call-parser beam`), and when the server-side parser is not enabled the calls arrive as XML inside the reasoning/content stream. Neither the backend nor the engine recognises that grammar, so:

- no structured `tool_calls` are produced,
- `_extract_text_tool_calls()` finds nothing to promote,
- `response_tool_calls` stays `None`,
- the round falls into the final-answer branch and appends an empty/answer-only assistant message,
- control returns to the prompt → "falls back into chat mode".

The same happens when a server uses `delta.reasoning` only (§2.1): reasoning chunks are skipped, no content is produced, and the turn ends immediately.

### 2.5 No Beam-specific request parameters

Beam supports:

- `reasoning_effort` ∈ {`low`, `medium` (default), `high`, `xhigh`, `max`} (passed to `apply_chat_template` / the server),
- `preserve_thinking` (reasoning stays in context across turns instead of being dropped),
- 1M-token context window.

`OpenAICompatBackend` has no mapping for `reasoning_effort` (it is not in `_OPTION_MAP`), and the engine/backend never send `preserve_thinking`. For long agentic Beam runs this means reasoning is discarded between turns, degrading multi-step tool use and increasing the chance that the model re-derives (and re-emits) tool calls as text. The backend also does not declare `supports_thinking`, unlike `GroqBackend`, so callers cannot tell whether reasoning will be surfaced.

### 2.6 No `reasoning_format` / `include_reasoning` negotiation

`GroqBackend` negotiates `reasoning_format="parsed"` (or `include_reasoning=True` for GPT-OSS) when tools are active, because Groq rejects raw reasoning interleaved with tool use (HTTP 400). `OpenAICompatBackend` sends no such hint. Servers that require an explicit opt-in to parsed reasoning (some vLLM builds) will either error out or stream raw `<think>` blocks in `content`, which the backend then misclassifies (§2.3).

### 2.7 Sanitization drops `thinking` but keeps no replay channel

`_sanitize_messages()` strips the internal `thinking` key (correct, since `engine.py` already strips `thinking` before sending). However, there is no backend-aware replay path: if `preserve_thinking` is desired, the thinking must travel in a structured channel (`reasoning_content` on the assistant message) rather than being re-injected as text tags — otherwise the server's chat template double-wraps it. The backend currently has no way to emit prior reasoning in the assistant message at all, so Beam's `preserve_thinking` cannot be honoured even if requested.

## 3. Why this is worse for Beam than for other models

- Beam is explicitly an **agentic / coding** model; its value depends on multi-step tool calling. A backend that silently drops tool rounds (§2.4) defeats the primary use case.
- Beam's reasoning is **long** (up to thousands of tokens per turn at `high`/`xhigh`/`max`). Misclassifying it as output (§2.1–2.3) pollutes the stored history and the context window, and the engine's `_warn_missing_thinking` / empty-answer paths trigger frequently.
- Beam is served almost exclusively through OpenAI-compatible endpoints (vLLM, SGLang, HF Inference Providers), so `openai_compat` is the only viable backend — there is no Ollama fallback for this model family.

## 4. Recommended fixes

### A. Backend parity with Groq (small, high-impact)

In `backends/openai_compat_backend.py::chat()`:

1. Read reasoning from **both** keys: `reasoning = delta.get("reasoning") or delta.get("reasoning_content")` (also tolerate `reasoning_text` / `thinking` for completeness).
2. **Yield thinking before content** within a single event.
3. Parse inline `<think>…</think>` (and `<thought>…</thought>`, `<|begin_of_thought|>`/`<|end_of_thought|>`) blocks in `content`, splitting into thinking/content chunks (reuse the Groq logic).
4. Add `supports_thinking` property (return `True`, since the backend surfaces reasoning when the server provides it).
5. Add `reasoning_effort` to `_OPTION_MAP` (pass through as `reasoning_effort`), and optionally `preserve_thinking`.

### B. Request-side negotiation

- When `tools` are supplied, send `reasoning_format="parsed"` (or `include_reasoning=True` for GPT-OSS-style models) like Groq, so servers that need an explicit opt-in stream parsed reasoning instead of raw tags.
- Allow `reasoning_effort` to be forwarded from `options` (and from a dedicated CLI/config knob if added).

### C. Tool-call grammar

- Prefer **server-side parsing**: document that Beam must be served with `--tool-call-parser beam` (SGLang) / the equivalent vLLM flag, so tool calls arrive as standard OpenAI `tool_calls` and the existing accumulation logic works.
- As a defensive fallback, extend the engine's text-tool-call promotion to recognise Beam's XML grammar (or add a backend-specific hook), so that even unparsed XML tool calls are promoted instead of being treated as output. This mirrors the existing Qwen3 `call:` handling and keeps the fix backend-agnostic.

### D. Thinking replay (optional, gated)

- Implement `preserve_thinking` by carrying prior reasoning in the **structured** channel: when building the assistant message for a tool round, include `reasoning_content` (mapped per backend) instead of (or in addition to) the internal `thinking` field, and let each backend map it. Gate this to thinking-capable families; never re-inject reasoning as text tags (see `llm_blueprint/thinking_issue/003_reinjection_sideeffect.md`).

### E. Tests

Extend `tests/test_openai_compat.py` to cover:

- `delta.reasoning` → `ChatChunk(thinking=…)` (currently only `reasoning_content` is tested).
- Inline `<think>…</think>` splitting in `content`.
- Emission order when both fields appear in one event (thinking first).
- `reasoning_effort` forwarding in the request payload.
- A regression test asserting that a Beam-style stream (reasoning in `reasoning`, tool call in `tool_calls`) executes the tool instead of falling back to a final answer.

## 5. Minimal change set (recommended first step)

The smallest change that resolves both reported symptoms is **A.1 + A.2 + A.3** (field-name tolerance, emission order, inline-tag parsing), ported verbatim from `GroqBackend`. That alone makes `openai_compat` correctly classify reasoning as thinking instead of output, and stops the empty-turn chat fallback for servers that use `reasoning` or inline tags. Items B–D are follow-ups for full Beam feature parity (`reasoning_effort`, `preserve_thinking`, XML tool calls).

## 6. Non-goals

- No change to the internal `Tool`/message format or to `run_with_tools()` control flow is required for the minimal fix; the engine already handles `ChatChunk.thinking`/`content` correctly once the backend classifies them right.
- No new backend is needed: `openai_compat` is the correct vehicle for Beam (vLLM/SGLang are OpenAI-compatible). A separate "beam" backend would only duplicate the SSE plumbing.
