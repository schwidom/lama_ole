# 006: Eliza Backend — Usage with Scripted Tool Calling

## Overview

`ElizaBackend` (`backends/eliza_backend.py`) is a **deterministic, scripted
mock backend**. It does not talk to a server and has zero dependencies. Each
`chat()` call plays the next entry from a user-supplied *script*, so a full
turn — including a tool-calling round-trip — can be rehearsed offline, byte
for byte.

It is the tool-callable counterpart to `EchoMockBackend` (`echo`): echo streams
whatever content it is given, while Eliza replays a predefined sequence that
fits the engine's request/response loop (especially useful for *tool calls*,
which echo cannot script).

| Fact | Value |
|------|-------|
| Backend name | `eliza` (registry key `backends.eliza_backend.ElizaBackend`) |
| Dependencies | none |
| Network | none |
| Default host | `http://localhost:80` (`BACKEND_DEFAULT_PORTS/Schemes`) |
| `supports_keep_alive` | `False` |
| `list_models()` / `list_running()` | `eliza-mock` + named scripts (`read_test`, `chitchat`) / `eliza-mock` |
| `show_model(model)` | `ModelInfo(name=model, context_length=4096)` |
| `stop_model()` | `True` (no-op) |
| Script delivery | explicit `script=` **or** named script via `-m` / model name |
| Built-in scripts | `read_test`, `chitchat` (`backends/eliza_scripts.py::ELIZA_SCRIPTS`) |

---

## Script format

A script is a **list of entries**. Each entry is a dict:

```python
script = [
    {"content": "<assistant text>", "tool_calls": [<OpenAI-style call>, ...]},
    {"content": "<assistant text>", "tool_calls": [<OpenAI-style call>, ...]},
]
```

- `content` — **required**. The assistant text streamed for this entry.
- `tool_calls` — **optional**. A list of OpenAI-function-calling dicts:

  ```python
  {"function": {"name": "get_weather", "arguments": {"city": "Berlin"}}}
  ```

  `arguments` may be a dict or a JSON string; the engine normalizes either
  (`tool_base/engine.py::_normalize_tool_calls`).

Every call to `eliza.chat()` consumes **exactly one entry** (an internal
`_index` advances). When the script is exhausted, Eliza streams
`[Eliza: script exhausted]` instead of an entry.

---

## Lifecycle and special behavior

1. **Sequential, one-shot consumption.** The script is a tape: entry *i* is
   played on the *i*-th `chat()` call. There is no reading ahead, no branching,
   and the index is not reset between turns.
2. **Selecting a script.** There is no `--script` argument. A script is chosen
   either explicitly, or **by model name**: with `--backend eliza`, passing
   `-m <script>` (or `/model <script>` in the REPL) loads the matching built-in
   script from `ELIZA_SCRIPTS` on first `chat()` call. Unknown names simply
   play `[Eliza: script exhausted]`. `-l` lists the named scripts alongside
   `eliza-mock`, so they are discoverable as models.

   ```bash
   python3 lama_ole.py --backend eliza -m chitchat -i "hello"
   python3 lama_ole.py --backend eliza -m read_test -i "read test.txt" \
       --tool tools.example_tools
   ```

   Explicitly supplied scripts take precedence over model-name lookup:

   ```python
   from backends.factory import create_backend
   eliza = create_backend("eliza", script=[{"content": "hi"}])  # always wins
   ```

   or directly:

   ```python
   from backends.eliza_backend import ElizaBackend
   eliza = ElizaBackend(script=[{"content": "hi"}])
   ```
3. **Thinking marker.** If any *system* message's content contains the word
   `thinking`, Eliza first streams a `ChatChunk(thinking="*thinking*")`. The
   engine only passes system messages it composes itself (or `--system_prompt`),
   so this is opt-in: it is how you rehearse a thinking-then-output turn.
4. **keep_alive.** `supports_keep_alive` is `False`. The CLI / `/backend`
   print a one-time warning that `.keep_alive` is ignored on this backend.
5. **Model/listing.** For an explicitly supplied script the model name is
   ignored. For named scripts it selects which script to play.

---

## Tool calling with a script

The engine's tool loop is: model emits `tool_calls` → engine invokes the tools
→ results are appended as `role: "tool"` messages → the model is called again
for a final answer. With a scripted backend this means **one script entry per
engine round**:

| Engine round | Messages seen by `chat()` | Script entry to supply |
|--------------|---------------------------|------------------------|
| 1 (tool decision) | `[user]` | entry 0: `content` + `tool_calls` |
| 2 (final answer) | `[user, assistant(tool_calls), tool results]` | entry 1: `content` (no tool_calls) |

A three-round tool chain needs three entries, and so on. This makes the Eliza
script a precise, readable rehearsal of the whole `run_with_tools` exchange.

---

## Complete example — weather tool call

The following uses `tools.example_tools` → `get_weather`:

```python
from backends.factory import create_backend
from tool_base.engine import run_with_tools
from tool_base.registry import load_tools

script = [
    # Round 1: the "model" decides to call the tool.
    {
        "content": "Sure, let me check the current conditions.",
        "tool_calls": [
            {"function": {"name": "get_weather", "arguments": {"city": "Berlin"}}}
        ],
    },
    # Round 2: after the tool result was fed back, the "model" answers.
    {"content": "The weather in Berlin is 22°C, partly cloudy."},
]

eliza = create_backend("eliza", script=script)
tools = load_tools("tools.example_tools")
backend_tools = eliza.convert_tools(tools)

run_with_tools(
    client=eliza,
    model="any",                                  # backend ignores the name
    messages=[{"role": "user", "content": "What is the weather in Berlin?"}],
    loaded_tools=tools,
    backend_tools=backend_tools,                  # OpenAI dict format
    options={},
    keep_alive=None,
    show_thinking=False,
    no_safety_system_prompt=True,
    verbose=1,
)
```

Observed output (with `verbose=1`):

```
Sure, let me check the current conditions.
[2026-09-09 21:57:05] [tool: get_weather(city='Berlin')]
[tool result: {
  "status": "success",
  "data": "Weather in Berlin: 22\u00b0C, partly cloudy"
}]
The weather in Berlin is 22°C, partly cloudy.
```

- `convert_tools(tools)` returns the shared OpenAI format
  (`backends/_tools.py::convert_tools_to_openai`) — `None` when the tool list
  is empty, which the engine treats as "no tools".
- The tool result message is wrapped (`[data from ...]`), stamped, and fed
  back before round 2 — this is why the script needs a second entry that
  "heard" the result.

---

## Multi-call / multi-tool rounds

Emit several calls in one entry to rehearse a parallel tool round; the tool
loop executes each and feeds the results back in order. The following entry
(output after the results) must then answer with all of them in context:

```python
script = [
    {
        "content": "Let me look both things up.",
        "tool_calls": [
            {"function": {"name": "get_weather", "arguments": {"city": "Paris"}}},
            {"function": {"name": "calculate", "arguments": {"expression": "6 * 7"}}},
        ],
    },
    {"content": "In Paris it is 18°C; 6 * 7 = 42."},
]
```

---

## Rehearsing thinking output

To also rehearse the thinking stream, ensure a system message contains the word
`thinking` (manual `system_prompt`, skill text, or simply not using
`--no_safety_system_prompt` if that prompt happens to contain it). Eliza then
prepends a `*thinking*` chunk to the entry:

```python
run_with_tools(
    ...,
    system_prompt="You are a thinking assistant.",   # contains "thinking"
    show_thinking=True,
)
```

produces (per round): `*thinking*` labeled as thinking, then the entry content.

---

## Pitfalls

- **Script exhausted is not an error.** It is an ordinary chunk; the engine
  just keeps streaming `[Eliza: script exhausted]` for every subsequent call.
  An under-provisioned script (fewer entries than engine rounds) will therefore
  surface as a nonsense final answer, not a crash.
- **No reset between turns.** In a REPL-style loop the index never restarts;
  a fresh `create_backend` is needed to replay the script.
  (The REPL `/backend eliza` always creates a fresh backend; pair it with
  `/model read_test` / `/model chitchat` to select a named script.)
- **`arguments` must be plain JSON types.** The engine normalizes each call to
  `{"function": {"name", "arguments"}}` and invokes the tool via `**arguments`,
  and the call is recorded (and NDJSON-logged) as JSON. Use real dicts of
  JSON values (or valid JSON strings, which the engine parses) — exactly as an
  OpenAI model would emit them; a Python object such as a set or pathlib.Path
  will not round-trip.
- **`content` and `tool_calls` in the same entry both take effect**: text is
  streamed to the user *and* the calls are executed. Keep spoken text generic
  so it stays correct when the tool result arrives.

---

## Built-in named scripts

`backends/eliza_scripts.py::ELIZA_SCRIPTS` ships two scripts, selectable by
model name. Because each entry is one `chat()` call, *two REPL turns* play
`read_test` back-to-back, and *ten consecutive turns* play the whole `chitchat`
dialog.

### `read_test` — reads `test.txt` via a tool call

Two entries: the first streams a sentence and emits a `read_file` tool call for
`path="test.txt"`; after the engine executes it and feeds back the result, the
second entry streams the closing line.

```bash
python3 lama_ole.py --backend eliza -m read_test -i "read test.txt" --tool tools.example_tools
```

The tool **requires a `test.txt` in the working directory** and the
`tools.example_tools` module loaded. If the file (or the module) is missing,
`read_file` returns an error which is fed back and the closing line still
plays — so the script always terminates gracefully.

### `chitchat` — a ten-sentence dialog

Ten entries, one sentence each; play all ten by driving ten turns (e.g. ten
REPL prompts or ten `chat()` calls). The dialog is human-authored so the
sentences form a coherent conversation.

```bash
python3 lama_ole.py --backend eliza -m chitchat -i "hello"   # sentence 1
```

The script index advances regardless of the user text, so subsequent REPL
prompts produce sentences 2..10 in order, then `[Eliza: script exhausted]`.

---

## Tests

`tests/test_eliza_backend.py` covers both dialogues:

- `test_read_test_dialogue` — drives `run_with_tools` with `model="read_test"`
  in a temp working dir containing `test.txt` and asserts the tool ran against
  `./test.txt` (its content appears in the tool result) and both sentences
  streamed in order.
- `test_chitchat_dialogue_ten_sentences` — plays all ten `chat()` calls and
  asserts each returns the expected sentence in order, then exhaustion.
- Plus resolution/fallback cases: named scripts listed by `list_models()`,
  unknown model names exhaust without crashing, and an explicit `script=`
  beats a model name.