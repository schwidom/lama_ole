# 002: Proposals and recommendations — fixing openai_compat for Beam

Date: 2026-10-30
Companion to `001_report.md`. This document turns the analysis into concrete,
ordered, implementable proposals with code sketches, file/line targets, and
acceptance criteria. All proposals keep Python 3.9 compatibility and the
existing test conventions.

## 0. Decision: fix `openai_compat`, do not add a `beam` backend

**Recommendation: modify `backends/openai_compat_backend.py` (and small,
backend-agnostic additions to `tool_base/engine.py`). Do not create a new
`beam` backend.**

Rationale:
- vLLM and SGLang both expose an OpenAI-compatible `/v1/chat/completions`
  endpoint; the SSE plumbing, tool accumulation, sanitization and HTTP code are
  identical. A `beam` backend would duplicate ~400 lines of `chat()` for no
  behavioural gain.
- The defects are *classification* defects (which delta key is reasoning, in
  what order, inline tags), not protocol defects. They affect every
  OpenAI-compatible server, not just Beam.
- The existing `GroqBackend` already proves the correct pattern; `openai_compat`
  should reach parity with it.

## 1. Proposal A — Reasoning parity with Groq (minimal, fixes both symptoms)

**Files:** `backends/openai_compat_backend.py`, `tests/test_openai_compat.py`.
**Effort:** small. **Impact:** high.

### A.1 Read reasoning from both keys

Change:
```python
reasoning = delta.get("reasoning_content")
```
to:
```python
reasoning = (
    delta.get("reasoning")
    or delta.get("reasoning_content")
    or delta.get("reasoning_text")
    or delta.get("thinking")
)
```
Mirrors `GroqBackend.chat()` (`reasoning = delta.get("reasoning") or delta.get("reasoning_content")`).

### A.2 Yield thinking before content

Reorder so that, within one event, reasoning is emitted first:
```python
if reasoning:
    yield ChatChunk(thinking=reasoning, done=False)
if content:
    yield ChatChunk(content=content, done=False)
```
This keeps the engine's state machine from flipping `OUTPUTTING` before
`THINKING` when a server batches both fields into one delta.

### A.3 Inline reasoning-tag parsing in `content`

Port the Groq `<​think>` handling. When `content` contains
`<​think>…<​/think>` (and, for hygiene, `<thought>…</thought>` and
`<​|begin_of_thought|>`/`<​|end_of_thought|>`), split it into thinking and
content chunks instead of passing it through as output. Sketch:

```python
in_think_tag = False  # per-stream state, like Groq
...
if content:
    if "<think>" in content or "<thought>" in content or "<|begin_of_thought|>" in content:
        # normalize to a single delimiter pair for the parser
        ...
    # reuse Groq's partition logic
```

To avoid duplicating the Groq block, extract a shared helper
`_split_thinking_tags(text, state)` in `backends/_compat.py` or a new
`backends/_reasoning.py` and call it from both `GroqBackend` and
`OpenAICompatBackend`. This keeps the two adapters in sync and is the single
place to add new delimiters (e.g. Beam's own tags if any appear).

### A.4 Declare `supports_thinking`

```python
@property
def supports_thinking(self) -> bool:
    return True
```
Matches `GroqBackend`. Lets callers (and `/stats`-style reporting) know the
backend surfaces reasoning when the server provides it.

### A.5 Add `reasoning_effort` (and `preserve_thinking`) to `_OPTION_MAP`

```python
_OPTION_MAP = {
    ...
    "reasoning_effort": "reasoning_effort",
    "preserve_thinking": "preserve_thinking",
}
```
Forwarded verbatim to the server. `reasoning_effort` is Beam's knob
(`low`/`medium`/`high`/`xhigh`/`max`); `preserve_thinking` is Beam's
cross-turn reasoning retention flag.

### Acceptance criteria (A)
- `test_openai_compat.py` gains tests for `delta.reasoning`, inline-tag
  splitting, and thinking-first ordering; all pass.
- A stream that puts reasoning in `reasoning` and a tool call in `tool_calls`
  now yields the tool call (no empty final answer).
- No regression in the 20 existing `test_openai_compat.py` tests.

## 2. Proposal B — Request-side reasoning negotiation

**Files:** `backends/openai_compat_backend.py`.
**Effort:** small.

When `tools` are supplied, send an explicit opt-in so servers that need it
stream parsed reasoning instead of raw tags, mirroring Groq:

```python
if tools:
    payload["tools"] = tools
    payload["tool_choice"] = "auto"
    if "gpt-oss" in model.lower():
        payload["include_reasoning"] = True
    else:
        payload["reasoning_format"] = "parsed"
```

Also forward `reasoning_effort` from `options` (already handled by A.5) and,
if a dedicated config knob is added later, from `config`.

### Acceptance criteria (B)
- Captured payload in tests contains `reasoning_format == "parsed"` when tools
  are passed (mirrors `test_tool_use_enforces_parsed_reasoning` in
  `test_groq_backend.py`).
- No HTTP 400 from vLLM/SGLang builds that require the opt-in.

## 3. Proposal C — Tool-call grammar (server-side first, defensive fallback)

### C.1 Server-side parsing (documentation + defaults)

Document (README + AGENTS.md) that Beam must be served with the dedicated
parser:
- SGLang: `--tool-call-parser beam --reasoning-parser beam`
- vLLM: the equivalent Beam tool-call parser flag

so tool calls arrive as standard OpenAI `tool_calls` and the existing
accumulation logic in `OpenAICompatBackend.chat()` works unchanged. This is the
primary path; no code change needed.

### C.2 Defensive text-promotion fallback (engine)

**Files:** `tool_base/engine.py`.
**Effort:** medium.

Extend `_extract_text_tool_calls()` / `_TEXT_CALL_RE` to also recognise Beam's
XML tool-call grammar when a server emits it unparsed. Two options:

1. **Backend-specific hook:** add an optional `extract_text_tool_calls(text)`
   method to `LlmBackend` (default: the existing Qwen3 `call:` logic) and let
   `openai_compat` override it with a Beam-XML parser. Keeps the engine
   backend-agnostic.
2. **Generic XML fallback in the engine:** add a second regex pass for
   `<tool_call …>` / `<function …>` style directives, gated so it only fires
   when no structured calls were produced.

Option 1 is preferred: it keeps model-specific grammar knowledge in the
backend that knows the model, and avoids false positives in the engine's
generic text path.

### Acceptance criteria (C)
- With `--tool-call-parser beam` enabled, a Beam turn that calls a tool
  executes it (integration test with a mocked SSE stream containing
  `tool_calls`).
- Without the parser, XML tool calls are still promoted (unit test), so the
  turn does not fall back to chat mode.

## 4. Proposal D — `preserve_thinking` replay (optional, gated)

**Files:** `backends/openai_compat_backend.py`, `backends/base.py`,
`tool_base/engine.py`.
**Effort:** larger. **Defer until A–C ship.**

- Add an optional `thinking` parameter to `LlmBackend.chat()` (default
  `None`), mapped per backend:
  - openai_compat: include prior reasoning as `reasoning_content` on the
    assistant message when replaying.
  - ollama: `msg.thinking`.
- In `run_with_tools()`, when `preserve_thinking` is requested and the backend
  supports it, pass the accumulated `think_text` into the next round's chat
  call instead of re-injecting it as `<thought>` text tags (which the engine
  already avoids after `003_reinjection_sideeffect.md`).
- Gate to thinking-capable families; never double-wrap (see
  `llm_blueprint/thinking_issue/003_reinjection_sideeffect.md`).

### Acceptance criteria (D)
- A two-round Beam conversation retains reasoning across turns when
  `preserve_thinking` is on, and does not when it is off.
- No `<thought>`/`<​think>` tags appear in re-sent `content`.

## 5. Proposal E — Tests

Extend `tests/test_openai_compat.py` (and add a `tests/tests_openai_compat/`
integration dir if real-server tests are wanted):

1. `delta.reasoning` → `ChatChunk(thinking=…)` (unit).
2. Inline `<​think>…<​/think>` splitting in `content` (unit, ported from Groq
   test `test_think_tag_stream_yields_thinking`).
3. Emission order: event with both `content` and `reasoning` yields thinking
   first (unit).
4. `reasoning_effort` and `preserve_thinking` forwarded in payload (unit).
5. `reasoning_format == "parsed"` when tools passed (unit, mirrors Groq).
6. Regression: Beam-style stream (reasoning in `reasoning`, tool call in
   `tool_calls`) executes the tool — integration via `run_with_tools()` with a
   scripted backend (mirrors `test_text_tool_calls.py`).

## 6. Implementation order

1. **A** (reasoning parity) — fixes both reported symptoms; smallest change.
2. **B** (negotiation) — prevents HTTP 400 / raw-tag streams.
3. **C.1** (docs) — unblocks correct Beam serving.
4. **C.2** (defensive XML promotion) — robustness for unparsed servers.
5. **E** (tests) — alongside each step.
6. **D** (`preserve_thinking`) — only after A–C are stable.

## 7. What not to do

- Do not create a separate `beam` backend (duplicates SSE plumbing).
- Do not re-inject reasoning as `<thought>`/`<​think>` text tags into
  `content` (see `003_reinjection_sideeffect.md`); use the structured channel.
- Do not change `run_with_tools()` control flow for the minimal fix — the
  engine already handles `ChatChunk.thinking`/`content` correctly once the
  backend classifies them right.
- Do not drop `reasoning_content` support (OpenAI o1/o3 still use it); always
  read both keys.
