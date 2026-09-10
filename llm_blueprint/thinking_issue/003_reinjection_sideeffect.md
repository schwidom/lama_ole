# 003: The `<thought>…</thought>` Re-Injection Side-Effect

Date: 2026-09-10
Scope: `lama_ole/tool_base/engine.py` (behavior analysis), decision for the `big_pickle/task_004.txt` question

## Observed behavior (from task_004 log)

A small model (lfm2.5-thinking:1.2b) produced a final answer *wrapped in* a
`<thought>…</thought>` block:

```
[2026-09-10 03:10:37] [tool: list_dir(path='/')]
[tool result: {
  "status": "error", "message": ["Blocked by safety check: only relative paths are allowed: /"]
}]
[2026-09-10 03:10:47] Thinking starts
... (thinking) ...
[2026-09-10 03:10:56] Thinking ends

<thought>
The system attempted to use `list_dir` with path "/". Here's the output:
```
c3fa7f290b2e4e2
```
This indicates there are entries in the root directory. ...
</thought>
```

`c3fa7f290b2e4e2` is the nonce from the tool-result wrapper — the model
misreads it as directory content (model-capability issue), but that is not the
point of this document. The question asked: *is there any meaningful intent to
encapsulate output in this `<thought>…</thought>` enclosure?*

## Where the `<thought>` wrapper comes from

`tool_base/engine.py:777`:

```python
if response_thinking:
    combined_content += f"<thought>\n{response_thinking}\n</thought>\n\n"
```

This runs **only** in the tool-call branch (`engine.py:773-806`), when building
the stored assistant message that accompanies structured `tool_calls`. That
message is appended to `messages` and re-sent to the model on the next round
(`engine.py:649-656`). The final-answer branch does **not** wrap anything —
`engine.py:974` stores `{"role": "assistant", "content": response_content}`
plain; thinking goes into a separate `thinking` field only when
`show_thinking` is on (`engine.py:975-976`).

## Intended intent (input side only)

The `<thought>` delimiter is a home-grown, *model-visible* convention whose
purpose is to separate the assistant's prior reasoning from its tool-call
payload in the re-sent transcript — so the model treats the block as "inner
monologue that led to the call below", not as a final answer and not as part
of the tool result.

It was never intended to wrap the user-facing / final output. The engine never
emits `<thought>` around the final response.

## What is actually happening (the leak)

The model **mimics** the delimiter it sees in its own context. Because every
tool-call round injects `<thought>\n…\n</thought>` into an assistant message
that is sent back to the model, small/weak models learn the convention and
reproduce it around their *answers* — producing exactly the artifact in the
log. So:

- The meaningful intent is real, but it lives on the **input** side.
- The `<thought>`-wrapped final answer came from the **model** (parroting), not
  from `engine.py`.

## Mitigation already present (task_003)

The task_003 fix already strips model-emitted `</?thought>` (and other
delimiter tokens) from streamed thinking/content via `_TEXT_DELIM_RE`
(`engine.py:111-118`) + `_clean_stream_text()` (applied at `engine.py:677` /
`engine.py:694`). A model-published `<thought>…</thought>` around its answer is
therefore removed before display/storage/re-injection. **BUT** the engine's own
injection at `engine.py:777` is precisely what teaches the model the tag, so
the fix suppresses the symptom while the root teaching signal remains.

Note: `_TEXT_DELIM_RE` does **not** yet strip Qwen3's native
`<|begin_of_thought|>` / `<|end_of_thought|>` tokens. If a Qwen3-family model
ever emits them inside content/thinking, they would currently leak through to
display and storage.

## Is `<|begin_of_thought|>` a viable replacement? (research finding)

**No — not as a generic default.** Findings:

- `<|begin_of_thought|>` / `<|end_of_thought|>` are **Qwen3-family-specific
  special tokens** (Qwen3, Qwen3.5/3.7/3.8). vLLM's
  `qwen3_reasoning_parser.py` uses exactly these as reasoning delimiters; they
  are part of Qwen3's own chat template, not a cross-vendor standard.
- For non-Qwen3 models the text is ordinary BPE tokens with no template
  support; injecting it can confuse them (Gemma, Llama, DeepSeek-R1, Kimi-K2,
  Phi, …).
- Even for Qwen3 itself the official best practice is: *historical model output
  should only include the final answer; thinking content does not need to be in
  history.* Thinking replay is only recommended for multi-step tool use, and
  then it must travel in the **structured channel** (`reasoning_content` /
  `msg.thinking`), **not** as text tags inside `content` — otherwise the tags
  can be double-wrapped by the server-side chat template.

## Recommendation

1. **Drop the `<thought>` injection at `engine.py:777`** and keep prior
   thinking entirely out of the `content` that is re-sent to the model. Thinking
   continues to be stored in the `thinking` field / ndjson for display and
   offline inspection; `engine.py:651` already strips `thinking` before sending.
   This removes the teaching signal that causes models to parrot the tag.
2. If thinking **replay** for multi-step tool use is ever needed, implement it
   properly: add an explicit thinking parameter to the `LlmBackend.chat()`
   interface and let each backend map it to its native channel (Ollama
   `msg.thinking`, OpenAI-compat `reasoning_content`). Gate it to
   thinking-capable model families instead of textual tags.
3. Independently, extend `_TEXT_DELIM_RE` with Qwen3's
   `<|begin_of_thought|>` / `<|end_of_thought|>` (and `<|`…`|>` general
   variants) so model-emitted native thinking tags are also scrubbed from
   display/storage.

## Implementation (Decided: option 2 + regex hygiene)

Applied in this session:

- **Dropped the `<thought>` injection**: the tool-call branch now stores
  `assistant_msg = {"role": "assistant", "content": response_content or None,
  "tool_calls": ...}` (`engine.py:775-781`). Prior thinking is kept only in the
  `thinking` field (when `show_thinking`) and in the ndjson log; it is no longer
  re-sent to the model in `content` (`engine.py:653` already strips the
  `thinking` field before sending).
- **Regex hygiene**: `_TEXT_DELIM_RE` now also strips Qwen3's native
  `<|begin_of_thought|>` and `<|end_of_thought|>` tokens from streamed
  thinking/content (`engine.py:111-120`), so a model emitting them natively can
  no longer leak them into display or storage.

**Not done (deferred):** the proper backend-aware thinking-replay channel
(LlmBackend.chat() thinking parameter mapped to Ollama `msg.thinking` /
OpenAI-compat `reasoning_content`). It only becomes relevant for
thinking-capable model families and multi-step tool use; re-visit if/when those
flows degrade without prior reasoning.

**Tests:** two regressions added to `tests/test_text_tool_calls.py`
(35 total): Qwen3 native-token stripping unit test, and an integration test
asserting a tool round's thinking stays out of `content` (stored message and the
second-round messages re-sent to the backend contain no `<thought>`).