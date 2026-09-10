# 002: Thinking-Block Tool-Call Pollution — Solution

Date: 2026-09-10
Scope: `lama_ole/tool_base/engine.py` (all changes in this file), `lama_ole/tests/test_text_tool_calls.py`

## Design decision

The fix lives entirely in `tool_base/engine.py` at the **stream/round level** —
not in any backend. The engine already owns display, storage, and re-injection,
so it is the single place where the directive must be (a) hidden from display,
(b) promoted to a real tool call, and (c) scrubbed from everything that is
stored and later re-injected. This keeps the fix backend-agnostic and
testable with plain `ChatChunk` streams.

Two complementary mechanisms were added:

1. **Display-time deferral** — while text is streaming, any suffix that could
   still grow into a `call:name{...}` directive is held back instead of printed.
2. **Round-end promotion + scrubbing** — after the stream closes, every
   `call:name{...}` directive embedded in `response_thinking` / `response_content`
   is parsed into a structured tool call and removed from the surfacing text.

---

## New helpers (`tool_base/engine.py`)

| Helper / constant | Lines | Purpose |
|---|---|---|
| `_TEXT_DELIM_RE` | 111-118 | Matches all chat-template/tool markers (`</?thought>`, `<|im_start|>`, `<|im_end|>`, `<|tool_call|>`, `<tool_call|>`, `<|tool_response>`). |
| `_TEXT_CALL_RE` | 120 | Matches a text directive: `call:name{` (name may contain `.`: `.-`). Negative lookbehind avoids matching parts of identifiers. |
| `_clean_stream_text()` | 123-132 | Strips marker tokens and converts `<|"|>` into `"`. Applies to each thinking/content chunk before display and accumulation. |
| `_brace_balanced()` | 135-163 | Finds the matching `}` for a `{`, skipping JSON string literals, so braces/commas inside argument values don't break nesting. Returns `None` when unclosed. |
| `_BARE_KEY_RE` / `_lenient_json_fix()` | 166, 171-239 | Repairs lenient JSON: quotes bare object keys (`{content:"x"}`) and escapes literal control characters (e.g. `\n`) inside string values only. Never rewrites anything outside key position / string literals. |
| `_parse_tool_arguments()` | 242-253 | Normalizes `<|"|">` quoting, applies `_lenient_json_fix`, strict-parses; `None` when not parseable or not an object. |
| `_text_call_tail_start()` | 256-268 | Index where a trailing in-progress *or just-closed* `call:` directive starts; used by display deferral to decide what must be held back. |
| `_extract_text_tool_calls()` | 271-295 | Parses every directive in text, returns `(remaining, calls)` — remaining text with the directives removed plus OpenAI-style call dicts. |
| `_stream_to_display()` | 298-310 | Deferred-display accumulation: emits every prefix that cannot still be the start of a directive, holds back the directive tail. |
| `_flush_pending_display()` | 313-320 | Drains the deferred buffer, scrubbing any fully-formed directive that ended exactly at the stream boundary. |

---

## Integration into `run_with_tools()` (`tool_base/engine.py`)

- Per-round deferred buffers are reset at `engine.py:636-637`; thinking/display
  are emitted through the `_emit_thinking` / `_emit_content` closures
  (`engine.py:521-527`) so a single emit path serves display, thought-logger and
  `show_thinking`.
- Thinking chunks (`engine.py:676-691`): each chunk is cleaned with
  `_clean_stream_text()` before being accumulated into `think_text` /
  `response_thinking` and routed through `_stream_to_display`. Markers never
  reach the screen.
- Content chunks (`engine.py:693-714`): likewise cleaned, and the thinking
  buffer is flushed first when the model transitions from thinking to output.
- After the stream closes (`engine.py:728-729`): both deferred buffers are
  flushed so a directive split across the last chunks is still fully emitted or
  scrubbed.
- Round end (`engine.py:734-741`): `_extract_text_tool_calls()` runs on
  `response_thinking` and `response_content`. Parsed calls are merged into
  `response_tool_calls` **only when `response_tool_calls is None`** — structured
  backend tool calls always keep priority. The scrubbed text replaces
  `response_thinking`, `response_content` and `think_text`.

Because the directives were removed from `response_thinking` before it is used
at `engine.py:777` (`<thought>\n{response_thinking}\n</thought>`), the stored
assistant message and therefore the re-injected context stay clean — the
corruption can no longer replay itself on subsequent rounds.

---

## Unparseable / partially emitted directives

- If `_parse_tool_arguments()` returns `None` (not strict-or-lenient JSON), the
  directive is **left as visible prose**; nothing is dropped and no warning is
  raised.
- Brace-unbalanced directives (stream truncated mid-object) are left in place
  for display/`think_text`, since there is no valid call to extract.

---

## Verification

`lama_ole/tests/test_text_tool_calls.py` — 33 tests, all passing:

- **Helper units** for every new helper: marker stripping, quoting restoration,
  brace matching (nested objects, strings with braces), lenient JSON repair
  (bare keys, control chars, commas inside strings, no false rewrites), tail
  detection, directive extraction (empty/`None` input, multiple calls, unclosed
  braces), and deferred display buffering/flushing.
- **Integration** (`run_with_tools()` with a scripted `ChatChunk` stream): a
  stream consisting only of polluted thinking (the exact `create_new_file`
  example from the task) now:
  - executes the tool (`path == "contacts.txt"`),
  - returns the final answer,
  - stores a clean `assistant` message with structured `tool_calls` and no
    `call:` / `<|tool_call|>` leftovers,
  - produces message roles `["system", "user", "assistant", "tool", "assistant"]`.
- A `capsys` test asserts the markers and directive never appear in printed
  output (split across several `ChatChunk`s, including a directive whose `{`-body
  continues past the previous chunk).

Full suite:

```bash
python3 -m pytest tests/ -q                 # 690 passed, 4 skipped
python3 tests/run_all_tests.py              # 723 passed, 4 skipped — "ALL TEST SUITES PASSED."
```

Python 3.9 syntax compatibility is kept (AST check passes with
`feature_version=(3, 9)` on both `engine.py` and the test file) per project
standard.