# 001: Thinking-Block Tool-Call Pollution — Issue Analysis

Date: 2026-09-10
Scope: `lama_ole/tool_base/engine.py` (fix), `lama_ole/backends/{ollama,openai_compat}_backend.py` (root cause), `lama_ole/tests/test_text_tool_calls.py` (tests)

## Summary

Some models (Qwen3-style) emit function calls **as plain text inside their
reasoning stream** instead of populating the structured `tool_calls` channel:

```
</thought><|tool_call|>call:create_new_file{content:<|"|>Name: Bob Ross<|"|>,path:<|"|>contacts.txt<|"|>}<tool_call|><|tool_response>
```

The tokenizers/backends bucket these tokens into the thinking channel
(`chunk.thinking`), and `run_with_tools()` in `tool_base/engine.py` printed that
thinking block verbatim without ever examining it. The result was a triple
failure:

1. The text tool-call directive was printed inside the thought block and
   **never executed** — silent dead turn (empty final answer, no `tool_calls`).
2. The raw directive was stored verbatim as assistant thinking and **re-injected
   into the context on every following tool-call round**, so the pollution grew
   in the conversation history.
3. No `content` / `tool_calls` were produced, so the turn ended with an empty
   assistant message that broke tool-round control flow.

---

## Root-cause chain

1. **Model output** — the model emits the call as text delimited by chat-template
   markers (`<|tool_call|>`, `<|tool_response>`, `<|"|">` string quoting) rather
   than a structured tool call.

2. **Backend bucketing** — those tokens land on the *thinking* channel:
   - Ollama: `msg.thinking` (`ollama_backend.py:66`).
   - OpenAI-compat: `reasoning_content` mapped to `chunk.thinking`
     (`openai_compat_backend.py:251-255`).

3. **Engine ignores thinking content** — `run_with_tools()` streamed
   `chunk.thinking` straight to the thought block and accumulated it into
   `response_thinking` / `think_text`, but never parsed it for directives.

4. **Silent dead turn** — with no `content` and no `tool_calls`, the round fell
   into the final-answer branch and appended an empty assistant message.

5. **Pollution re-injection** — `engine.py:777` builds the stored assistant
   content as `<thought>\n{response_thinking}\n</thought>`; because
   `response_thinking` still contained the raw directive, the corrupted
   thinking was fed back to the model on the next tool round as if it were real
   reasoning. Each round could add more of the same, compounding the context.

---

## Behavioral requirements implied by the issue

- Markers (`</?thought>`, `<|im_start|>/<|im_end|>`, `<|tool_call|>`,
  `<tool_call|>`, `<|tool_response>`, `<|"|">`) must never appear in the
  displayed thought block, in stored history, or in what is re-injected.
- `call:name{...}` directives must be promoted to real structured tool calls and
  executed, not printed as reasoning.
- This must work **across chunk boundaries**: the directive is frequently split
  across multiple `ChatChunk`s (e.g. one chunk ends with an unterminated
  `{`-object).
- If a directive's arguments are not parseable, the text must stay visible as
  prose instead of being silently swallowed or crashing the round.
- Structured `tool_calls` (when a backend provides them) must keep priority over
  text-promoted calls.