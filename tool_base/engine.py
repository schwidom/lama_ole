import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import color_util

from .models import Tool
from .constants import DANGEROUS_TOOLS
from .utils import create_uuid_15

_MISSING = object()

# Models for which we already warned that the backend produced no thinking
# output (module-level fallback for one-shot runs; the REPL keeps a per-state
# copy so the warning fires at most once per model in a session).
_WARNED_NO_THINKING_MODELS = set()


def _normalize_tool_calls(tool_calls: Any) -> List[Dict]:
    """Normalize backend tool calls to OpenAI-style dicts.

    The engine's conversation history and the LlmBackend interface use the
    OpenAI function-calling shape:
        {"function": {"name": ..., "arguments": {...}}}
    This helper also tolerates the legacy object style (OllamaTool-like) so
    defensive paths never crash on either representation.
    """
    result: List[Dict] = []
    for tc in tool_calls:
        fn = tc.get("function") if isinstance(tc, dict) else getattr(tc, "function", {})
        if fn is None:
            fn = {}
        name = fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", None)
        arguments = fn.get("arguments") if isinstance(fn, dict) else getattr(fn, "arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except Exception:
                arguments = {}
        elif isinstance(arguments, dict):
            arguments = dict(arguments)
        else:
            arguments = {}
        result.append({"function": {"name": name, "arguments": arguments}})
    return result


def _websearch_tool() -> Dict:
    """Build the optional web_search tool in the shared OpenAI dict format."""
    return {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query",
                    },
                },
                "required": ["query"],
            },
        },
    }


def _warn_missing_thinking(model: str, mode_state) -> None:
    """Warn (once per model per session) that no thinking output was produced."""
    store = None
    if mode_state is not None:
        store = getattr(mode_state, "_warned_no_thinking_models", None)
    if store is None:
        store = _WARNED_NO_THINKING_MODELS
    if model in store:
        return
    store.add(model)
    print(
        f"[WARNING] Model '{model}' produced no thinking output on this "
        "backend; the thinking process will be hidden.",
        file=sys.stderr,
    )


def _stamp_message(msg) -> None:
    """Attach the event time to a message dict (idempotent).

    /history uses this timestamp to show when each entry happened. Existing
    timestamps (e.g. from /load) are left untouched.
    """
    if isinstance(msg, dict) and "timestamp" not in msg:
        msg["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Text-based tool calls (Qwen3-style `call:name{...}`)
#
# Some models emit function calls as plain text instead of populating the
# structured `tool_calls` channel, e.g.:
#     </thought><|tool_call|>call:create_new_file{content:<|"|>...<|"|>}<tool_call|><|tool_response>
# When the backend classifies those tokens as part of the thinking stream they
# used to be printed verbatim inside the thought block and the turn died with
# an empty reply. The helpers below strip the delimiter tokens and turn the
# embedded `call:` directives into normal structured tool calls.
# ---------------------------------------------------------------------------

_TEXT_DELIM_RE = re.compile(
    r"</?thought>"
    r"|<\|begin_of_thought\|>"
    r"|<\|end_of_thought\|>"
    r"|<\|im_start\|>(?:think|reasoning|response|assistant|user|system|tool)"
    r"|<\|im_end\|>"
    r"|<\|tool_call\|>"
    r"|<tool_call\|>"
    r"|<\|tool_response>"
)

_TEXT_CALL_RE = re.compile(r"(?<![A-Za-z0-9_])call:([A-Za-z_][A-Za-z0-9_.:-]*)(\{)")


def _clean_stream_text(text: str) -> str:
    """Remove model tool-call / chat-template delimiter tokens.

    Runs on every thinking/output chunk before display and accumulation so the
    markers never leak into the thought block or the stored history. Qwen3's
    `<|"|">` string-quote token is converted to a normal quote.
    """
    if not text:
        return ""
    return _TEXT_DELIM_RE.sub("", text).replace('<|"|>', '"')


def _brace_balanced(text: str, start: int) -> Optional[int]:
    """Return the index matching the ``{`` at ``start``, or None if unclosed.

    JSON string literals are skipped so braces inside argument values do not
    throw off the nesting count.
    """
    depth = 0
    in_str = False
    escaped = False
    i = start
    while i < len(text):
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


_BARE_KEY_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(\s*:)")

_JSON_CONTROL_ESCAPES = {"\n": r"\n", "\r": r"\r", "\t": r"\t", "\b": r"\b", "\f": r"\f"}


def _lenient_json_fix(text: str) -> str:
    """Repair a leniently-formatted JSON object emitted as a text tool call.

    Two model-isms are tolerated: bare (unquoted) object keys
    (`{content:"x",path:"y"}`) and literal control characters (e.g. newlines)
    inside string values. The scanner only rewrites identifiers in key
    position (right after ``{`` / ``,``) and escapes control chars inside
    string literals only, so values are never corrupted.
    """
    out: List[str] = []
    i = 0
    n = len(text)
    in_str = False
    escaped = False
    expect_key = False
    while i < n:
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
                out.append(ch)
            elif ch == "\\":
                escaped = True
                out.append(ch)
            elif ch == '"':
                in_str = False
                out.append(ch)
            elif ord(ch) < 0x20:
                out.append(_JSON_CONTROL_ESCAPES.get(ch, "\\u%04x" % ord(ch)))
            else:
                out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_str = True
            expect_key = False
            out.append(ch)
            i += 1
            continue
        if ch == "{":
            expect_key = True
            out.append(ch)
            i += 1
            continue
        if ch == "}":
            expect_key = False
            out.append(ch)
            i += 1
            continue
        if ch == ",":
            expect_key = True
            out.append(ch)
            i += 1
            continue
        if expect_key:
            m = _BARE_KEY_RE.match(text, i)
            if m:
                out.append('"')
                out.append(m.group(1))
                out.append('"')
                out.append(m.group(2))
                expect_key = False
                i = m.end()
                continue
        out.append(ch)
        if not ch.isspace():
            expect_key = False
        i += 1
    return "".join(out)


def _parse_tool_arguments(raw: str) -> Optional[Dict]:
    """Parse a Qwen3 text-tool-call argument object.

    Tolerates ``<|"|">`` quoting, bare object keys and literal control
    characters inside string values. None when not parseable.
    """
    raw = raw.replace('<|"|>', '"')
    try:
        obj = json.loads(_lenient_json_fix(raw))
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def _text_call_tail_start(text: str) -> Optional[int]:
    """Index where a trailing in-progress (or just-closed) `call:` directive
    starts, so the live display can hold it back; None when nothing matches."""
    matches = list(_TEXT_CALL_RE.finditer(text))
    if not matches:
        return None
    m = matches[-1]
    close = _brace_balanced(text, m.start(2))
    if close is None:
        return m.start()
    if not text[close + 1:].strip():
        return m.start()
    return None


def _extract_text_tool_calls(text: str) -> Tuple[str, List[Dict]]:
    """Parse every `call:name{...}` directive embedded in ``text``.

    Returns ``(remaining, calls)``: ``remaining`` is ``text`` with every
    successfully parsed directive removed (keeps surrounding reasoning clean
    for storage / re-injection) and ``calls`` is a list of OpenAI-style
    tool-call dicts.
    """
    if not text:
        return text, []
    pieces: List[str] = []
    calls: List[Dict] = []
    pos = 0
    for m in _TEXT_CALL_RE.finditer(text):
        close = _brace_balanced(text, m.start(2))
        if close is None:
            continue
        args = _parse_tool_arguments(text[m.start(2):close + 1])
        if args is None:
            continue
        pieces.append(text[pos:m.start()])
        pos = close + 1
        calls.append({"function": {"name": m.group(1), "arguments": args}})
    pieces.append(text[pos:])
    return "".join(pieces), calls


def _stream_to_display(pending: str, new_text: str, emit) -> str:
    """Append ``new_text`` to the deferred display buffer and immediately emit
    every prefix that cannot still be the start of a text tool call."""
    text = pending + new_text
    tail = _text_call_tail_start(text)
    if tail is None:
        if text:
            emit(text)
        return ""
    safe = text[:tail]
    if safe:
        emit(safe)
    return text[tail:]


def _flush_pending_display(pending: str, emit) -> str:
    """Emit the remaining non-directive text of a deferred display buffer."""
    if not pending:
        return ""
    remainder, _ = _extract_text_tool_calls(pending)
    if remainder:
        emit(remainder)
    return ""


def _entropy_check_tool_result(result, tool_name) -> None:
    """Defensive entropy check on a tool result dict (opt-in, see below).

    Warns on stderr and truncates the data when the content looks binary or
    random. Enabled only when LAMA_OLE_ENTROPY_CHECK is set or verbose >= 2,
    so normal operation is not slowed down.
    """
    if not isinstance(result, dict) or result.get("status") != "success":
        return
    content = result.get("data", "")
    if isinstance(content, bytes):
        data_bytes = content
    elif isinstance(content, str):
        data_bytes = content.encode("utf-8", errors="replace")
    else:
        try:
            data_bytes = json.dumps(content).encode("utf-8")
        except Exception:
            return

    from security.entropychecker import EntropyChecker

    check = EntropyChecker().feed(data_bytes)
    if check.is_suspicious:
        print(
            f"[WARNING] Tool '{tool_name}' result failed entropy check: "
            f"{check.reason}",
            file=sys.stderr,
        )
        if isinstance(content, bytes):
            result["data"] = content[:1000] + b"... [TRUNCATED BY ENTROPY CHECK]"
        else:
            result["data"] = str(content)[:1000] + "... [TRUNCATED BY ENTROPY CHECK]"


_MAX_DIFF_LINES = 200


def _print_diff_block(file, diff, use_color) -> None:
    """Print a colored unified diff block to stdout (mirrors opencode's edit card)."""
    if not diff:
        return
    lines = diff.split("\n")
    additions = 0
    deletions = 0
    for line in lines:
        if line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1

    if len(lines) > _MAX_DIFF_LINES + 2:
        shown = lines[:_MAX_DIFF_LINES]
        truncated = True
    else:
        shown = lines
        truncated = False

    header = f"[edit: {file}] +{additions} -{deletions}"
    print(color_util.colored(header, color_util.C_PROMPT, use_color))
    for line in shown:
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            color = color_util.C_METER_MID
        elif line.startswith("+"):
            color = color_util.C_METER_LOW
        elif line.startswith("-"):
            color = color_util.C_METER_HIGH
        else:
            color = color_util.C_THINK
        print(color_util.colored(line, color, use_color))
    if truncated:
        print(color_util.colored(f"... diff truncated ({len(lines) - _MAX_DIFF_LINES} lines omitted)", color_util.C_THINK, use_color))


def compose_system_prompt(
    system_prompt: Optional[str] = None,
    skill_text: Optional[str] = None,
    no_safety_system_prompt: bool = False,
    mode: Optional[str] = None,
) -> str:
    """Build the system message content from its ordered parts.

    Order: base system prompt -> optional skill block -> optional plan-mode
    block -> safety prompts. The skill block is delimited so it can be
    identified and stripped on unload, and so it stays visually distinct from
    the base prompt.
    """
    sp = ""
    if system_prompt is not None:
        sp += system_prompt
        sp += "\n"
    if skill_text:
        sp += "[SKILL BEGIN]\n"
        sp += skill_text
        sp += "\n[SKILL END]\n"
    if mode == "plan":
        from .constants import PLAN_MODE_SYSTEM_PROMPT

        sp += "[PLAN MODE BEGIN]\n"
        sp += PLAN_MODE_SYSTEM_PROMPT
        sp += "\n[PLAN MODE END]\n"
    if not no_safety_system_prompt:
        from .constants import SAFETY_SYSTEM_PROMPT, JSON_RETURN_PROMPT

        sp += SAFETY_SYSTEM_PROMPT
        sp += JSON_RETURN_PROMPT
    return sp


def run_with_tools(
    client,
    model,
    messages: List[dict],
    loaded_tools: List[Tool],
    backend_tools: Optional[List[Dict]],
    options: dict,
    keep_alive: Any,
    show_thinking: bool,
    no_safety_system_prompt: bool,
    system_prompt: Optional[str] = None,
    skill_text: Optional[str] = None,
    mode: Optional[str] = None,
    verbose: int = 0,
    safe: bool = False,
    thought_file_handle=None,
    output_file_handle=None,
    toolcall_file_handle=None,
    chatinput_file_handle=None,
    max_tool_rounds: Optional[int] = None,
    max_tool_rounds_continuation: str = "ask",
    websearch: bool = False,
    ndjson_log_file_handle=None,
    color: str = "auto",
    state_manager=None,
    metrics: Optional[dict] = None,
    mode_state=None,
    show_diff: bool = True,
):
    from .loop_states import ExecutionState, StateManager, ExecutionInterrupted
    from .logging import StateLogger

    if state_manager is None:
        state_manager = StateManager()
    use_color = color_util.color_mode_enabled(color)
    tool_rounds = 0
    think_state = False
    final_response = ""
    last_prompt_eval_count = None
    last_eval_count = None
    last_eval_duration_ns = None
    last_prompt_eval_duration_ns = None
    turn_rounds = []
    turn_elapsed_started = None

    def _current_mode() -> str:
        """Effective mode right now (may change mid-turn via the hotkey)."""
        if mode_state is not None:
            current = getattr(mode_state, "mode", None)
            if current is not None:
                return current
        return mode or "build"

    def _refresh_tools_for_request():
        """Adopt mode_state's advertised tool list after a mid-turn toggle."""
        if mode_state is None:
            return tools_for_request
        new_tools = getattr(mode_state, "backend_tools", _MISSING)
        if new_tools is not _MISSING and new_tools is not tools_for_request:
            return new_tools
        return tools_for_request

    tools_for_request = backend_tools

    from contextlib import contextmanager

    @contextmanager
    def _hotkey_suspended():
        """Park the mid-turn hotkey listener around a blocking stdin prompt."""
        pause = getattr(mode_state, "hotkey_pause", None)
        resume = getattr(mode_state, "hotkey_resume", None)
        if pause is not None:
            pause()
        try:
            yield
        finally:
            if resume is not None:
                resume()

    thought_logger = (
        StateLogger(handle=thought_file_handle) if thought_file_handle else None
    )
    output_logger = (
        StateLogger(handle=output_file_handle) if output_file_handle else None
    )
    toolcall_logger = (
        StateLogger(handle=toolcall_file_handle) if toolcall_file_handle else None
    )

    def _emit_thinking(text: str) -> None:
        if show_thinking:
            print(color_util.colored(text, color_util.C_THINK, use_color), end='', flush=True)
        if thought_logger:
            thought_logger.write_thought(text)

    def _emit_content(text: str) -> None:
        print(color_util.colored(text, color_util.C_OUTPUT, use_color), end='', flush=True)
        if output_logger:
            output_logger.write_output(text)

    has_system = any(m.get("role") == "system" for m in messages)
    if not has_system:
        sp = compose_system_prompt(
            system_prompt=system_prompt,
            skill_text=skill_text,
            no_safety_system_prompt=no_safety_system_prompt,
            mode=mode,
        )

        system_msg = {"role": "system", "content": sp}
        _stamp_message(system_msg)
        messages.insert(0, system_msg)
        if ndjson_log_file_handle:
            from .logging import _log_ndjson_message
            _log_ndjson_message(ndjson_log_file_handle, model, system_msg)

    if websearch:
        web_tool = _websearch_tool()
        if backend_tools:
            backend_tools.append(web_tool)
        else:
            backend_tools = [web_tool]
        tools_for_request = backend_tools

    if verbose >= 2:
        from .logging import _log_messages_payload
        _log_messages_payload(messages, file=sys.stderr)

    while True:
        if max_tool_rounds is not None and tool_rounds >= max_tool_rounds:
            if max_tool_rounds_continuation == "fallback":
                print(
                    "Reached maximum number of tool-calling rounds.",
                    file=sys.stderr,
                )
                state_manager.reset()
                break
            elif max_tool_rounds_continuation == "ask":
                print(
                    f"Maximum tool rounds ({max_tool_rounds}) reached.",
                    file=sys.stderr,
                )
                print("Options:", file=sys.stderr)
                print("  1. Set a new max round limit", file=sys.stderr)
                print("  2. Set unlimited (continue indefinitely)", file=sys.stderr)
                print("  3. Fallback (current mode default)", file=sys.stderr)
                print("  4. Quit", file=sys.stderr)
                print("Enter choice (1-4): ", file=sys.stderr, end='', flush=True)
                try:
                    with _hotkey_suspended():
                        choice = sys.stdin.readline().strip()
                except EOFError:
                    choice = "3"
                except KeyboardInterrupt:
                    state_manager.reset()
                    print("\nInterrupted.", file=sys.stderr)
                    break
                if choice == "1":
                    print(
                        "Enter new max round limit: ",
                        file=sys.stderr, end='', flush=True,
                    )
                    try:
                        with _hotkey_suspended():
                            new_val = sys.stdin.readline().strip()
                        max_tool_rounds = int(new_val)
                        print(
                            f"New limit set to {max_tool_rounds}.",
                            file=sys.stderr,
                        )
                    except (ValueError, EOFError):
                        print("Invalid input. Falling back.", file=sys.stderr)
                        state_manager.reset()
                        break
                    except KeyboardInterrupt:
                        state_manager.reset()
                        print("\nInterrupted.", file=sys.stderr)
                        break
                elif choice == "2":
                    max_tool_rounds = None
                    print("Unlimited rounds set.", file=sys.stderr)
                elif choice == "4":
                    state_manager.reset()
                    print("Exiting.", file=sys.stderr)
                    return final_response
                else:
                    state_manager.reset()
                    break
                continue

        if verbose >= 2:
            from .logging import _log_messages_payload
            _log_messages_payload(messages, file=sys.stderr)

        # A fresh model generation round starts a new slice for thought/output logs.
        if thought_logger:
            thought_logger.new_slice()
        if output_logger:
            output_logger.new_slice()

        response_content = ""
        response_thinking = ""
        response_tool_calls = None
        think_text = ""
        pending_think_display = ""
        pending_content_display = ""
        round_prompt_eval_count = None
        round_eval_count = None
        round_eval_duration_ns = None
        round_prompt_eval_duration_ns = None
        round_started = time.monotonic()
        if turn_elapsed_started is None:
            turn_elapsed_started = round_started

        tools_for_request = _refresh_tools_for_request()

        try:
            stream = client.chat(
                model=model,
                messages=[{k: v for k, v in m.items() if k != "thinking"} for m in messages],
                tools=tools_for_request,
                stream=True,
                options=options,
                keep_alive=keep_alive,
            )
            try:
                for chunk in stream:
                    if getattr(chunk, "prompt_eval_count", None) is not None:
                        last_prompt_eval_count = chunk.prompt_eval_count
                    if getattr(chunk, "eval_count", None) is not None:
                        last_eval_count = chunk.eval_count
                    if getattr(chunk, "eval_duration_ns", None) is not None:
                        last_eval_duration_ns = chunk.eval_duration_ns
                    if getattr(chunk, "prompt_eval_duration_ns", None) is not None:
                        last_prompt_eval_duration_ns = chunk.prompt_eval_duration_ns

                    if verbose >= 3:
                        from .logging import _log_chunk
                        _log_chunk(chunk, file=sys.stderr)

                    thinking = getattr(chunk, "thinking", None)
                    content = getattr(chunk, "content", None) or ""
                    tool_calls = getattr(chunk, "tool_calls", None)

                    if thinking:
                        thinking = _clean_stream_text(thinking)
                        if thinking:
                            think_text += thinking
                            if not think_state:
                                think_state = True
                                state_manager.transition_to(ExecutionState.THINKING)
                                if thought_logger:
                                    thought_logger.new_slice()
                                if show_thinking:
                                    ts = time.strftime("%Y-%m-%d %H:%M:%S")
                                    print(color_util.colored(f"[{ts}] Thinking starts", color_util.C_THINK, use_color))
                            response_thinking += thinking
                            pending_think_display = _stream_to_display(
                                pending_think_display, thinking, _emit_thinking
                            )

                    if content:
                        content = _clean_stream_text(content)
                        if content:
                            if think_state:
                                think_state = False
                                state_manager.transition_to(ExecutionState.OUTPUTTING)
                                if output_logger:
                                    output_logger.new_slice()
                                pending_think_display = _flush_pending_display(
                                    pending_think_display, _emit_thinking
                                )
                                if show_thinking:
                                    ts = time.strftime("%Y-%m-%d %H:%M:%S")
                                    print()
                                    print(color_util.colored(f"[{ts}] Thinking ends", color_util.C_THINK, use_color))
                                    print()
                            elif state_manager.current_state != ExecutionState.OUTPUTTING:
                                state_manager.transition_to(ExecutionState.OUTPUTTING)
                            response_content += content
                            pending_content_display = _stream_to_display(
                                pending_content_display, content, _emit_content
                            )

                    if tool_calls:
                        response_tool_calls = tool_calls
            finally:
                if stream is not None and hasattr(stream, "close"):
                    stream.close()
        except KeyboardInterrupt:
            interrupted_state = state_manager.current_state
            state_manager.reset()
            think_state = False
            print("\nInterrupted during model response. Returning to prompt.", file=sys.stderr)
            raise ExecutionInterrupted(interrupted_state)

        pending_think_display = _flush_pending_display(pending_think_display, _emit_thinking)
        pending_content_display = _flush_pending_display(pending_content_display, _emit_content)

        # Promote text-based tool calls (`call:name{...}`) to real structured
        # tool calls and scrub the directive out of the text that is stored
        # and re-injected as context, so it is never replayed as "thinking".
        think_cleaned, calls_from_thinking = _extract_text_tool_calls(response_thinking)
        content_cleaned, calls_from_content = _extract_text_tool_calls(response_content)
        if calls_from_thinking or calls_from_content:
            response_thinking = think_cleaned
            response_content = content_cleaned
            think_text = think_cleaned
            if response_tool_calls is None:
                response_tool_calls = calls_from_thinking + calls_from_content

        if think_state:
            think_state = False
            state_manager.transition_to(ExecutionState.IDLE)
            if show_thinking:
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                print()
                print(color_util.colored(f"[{ts}] Thinking ends", color_util.C_THINK, use_color))
                print()

        print()

        if metrics is not None:
            metrics["prompt_eval_count"] = last_prompt_eval_count
            metrics["eval_count"] = last_eval_count
            metrics["eval_duration_ns"] = last_eval_duration_ns
            metrics["prompt_eval_duration_ns"] = last_prompt_eval_duration_ns
            metrics["last_round_kind"] = "tool call" if response_tool_calls else "final answer"
            metrics["rounds_model"] = model

        if metrics is not None:
            turn_rounds.append(
                {
                    "kind": "tool call" if response_tool_calls else "final answer",
                    "eval_count": last_eval_count,
                    "eval_duration_ns": last_eval_duration_ns,
                    "prompt_eval_count": last_prompt_eval_count,
                    "prompt_eval_duration_ns": last_prompt_eval_duration_ns,
                }
            )

        if response_tool_calls:
            normalized_calls = _normalize_tool_calls(response_tool_calls)
            assistant_msg = {
                "role": "assistant",
                "content": response_content or None,
                "tool_calls": normalized_calls,
            }
            if show_thinking and think_text.strip():
                assistant_msg["thinking"] = think_text
            _stamp_message(assistant_msg)
            messages.append(assistant_msg)
            if ndjson_log_file_handle:
                from .logging import _log_ndjson_message
                if response_thinking:
                    thought_msg = {
                        "role": "assistant",
                        "content": response_thinking,
                        "mode": "thinking"
                    }
                    _log_ndjson_message(ndjson_log_file_handle, model, thought_msg)
                
                if response_thinking:
                    output_msg = {
                        "role": "assistant",
                        "content": response_content or None,
                        "tool_calls": normalized_calls,
                        "mode": "output",
                    }
                    _log_ndjson_message(ndjson_log_file_handle, model, output_msg)
                else:
                    _log_ndjson_message(ndjson_log_file_handle, model, assistant_msg)

            for tc in normalized_calls:
                fn = tc.get("function") or {}
                tool_name = fn.get("name")
                arguments = fn.get("arguments") or {}
                if not isinstance(arguments, dict):
                    arguments = {}
                args_str = ", ".join(
                    f"{k}={v!r}" for k, v in arguments.items()
                )

                tool_obj = next(
                    (t for t in loaded_tools if t.name == tool_name),
                    None,
                )

                if verbose >= 1:
                    ts = time.strftime("%Y-%m-%d %H:%M:%S")
                    print(
                        f"[{ts}] [tool: {tool_name}({args_str})]",
                        file=sys.stderr,
                        flush=True,
                    )

                state_manager.transition_to(ExecutionState.TOOLCALLING)

                if toolcall_logger:
                    toolcall_logger.new_slice()
                    toolcall_logger.write_tool_call(f"[tool: {tool_name}({args_str})]\n")

                try:
                    if tool_obj:
                        if _current_mode() == "plan" and not tool_obj.readonly:
                            # Mid-turn safety net: a write tool proposed before
                            # the user toggled to plan mode must not run. The
                            # model should learn the tool still exists and will
                            # work once build mode is activated.
                            result = {
                                "status": "error",
                                "message": (
                                    f"Execution of '{tool_name}' blocked: plan mode is "
                                    "currently enforced. This tool is still available and "
                                    "will run once build mode is activated (/build). Do not "
                                    "retry it; continue planning with read-only tools."
                                ),
                            }
                        else:
                            should_run = True
                            if safe and tool_name in DANGEROUS_TOOLS:
                                print(
                                    f"\n[DANGER] Tool '{tool_name}' called with: {args_str}",
                                    file=sys.stderr,
                                )
                                print(
                                    "Proceed? (y/N): ",
                                    file=sys.stderr, end='', flush=True,
                                )
                                try:
                                    with _hotkey_suspended():
                                        answer = sys.stdin.readline().strip().lower()
                                except EOFError:
                                    answer = 'n'
                                except KeyboardInterrupt:
                                    answer = 'n'
                                should_run = answer == 'y'

                            if should_run:
                                try:
                                    raw_result = tool_obj.fn(**arguments)
                                    if isinstance(raw_result, dict):
                                        result = raw_result
                                    else:
                                        result = {"status": "success", "data": raw_result}
                                except Exception as e:
                                    result = {"status": "error", "message": str(e)}
                            else:
                                result = {"status": "error", "message": f"Execution of '{tool_name}' cancelled by user (safe mode)."}
                    else:
                        result = {"status": "error", "message": f"unknown tool '{tool_name}'"}
                except KeyboardInterrupt:
                    interrupted_state = state_manager.current_state
                    state_manager.reset()
                    print("\nInterrupted during tool execution. Returning to prompt.", file=sys.stderr)
                    raise ExecutionInterrupted(interrupted_state)

                # Defensive entropy check (opt-in): catches future tools that
                # bypass the per-tool integration.
                if verbose >= 2 or os.environ.get("LAMA_OLE_ENTROPY_CHECK"):
                    _entropy_check_tool_result(result, tool_name)

                if verbose >= 1:
                    display = json.dumps(result, indent=2) if isinstance(result, dict) else str(result)
                    if verbose < 2 and len(display) > 500:
                        display = display[:500] + "..."
                    print(
                        f"[tool result: {display}]",
                        file=sys.stderr,
                        flush=True,
                    )

                if show_diff and isinstance(result, dict):
                    _print_diff_block(
                        result.get("file") or tool_name,
                        result.get("diff") or "",
                        use_color,
                    )

                # --- NEW NONCE LOGIC START ---
                nonce = create_uuid_15()
                if isinstance(result, dict) and result.get("status") == "success":
                    status_str = "Success"
                    content_str = result.get("data", "")
                elif isinstance(result, dict) and result.get("status") == "error":
                    status_str = "Error"
                    content_str = result.get("message", "")
                else:
                    status_str = "Result"
                    content_str = result

                if not isinstance(content_str, str):
                    content_str = json.dumps(content_str)

                nonce_wrapped_content = f"{nonce} {status_str} {nonce} {content_str} {nonce}"

                wrapped = (
                    f"[data from {tool_name}: {args_str}]\n"
                    f"---BEGIN DATA---\n"
                    f"{nonce_wrapped_content}\n"
                    f"---END DATA---"
                )
                # --- NEW NONCE LOGIC END ---

                if toolcall_logger:
                    toolcall_logger.new_slice()
                    toolcall_logger.write_tool_result(f"[result: {nonce_wrapped_content}]\n")

                tool_msg = {
                    "role": "tool",
                    "content": wrapped,
                    "tool_name": tool_name,
                    "diff": result.get("diff") if isinstance(result, dict) else None,
                    "file": result.get("file") if isinstance(result, dict) else None,
                }
                _stamp_message(tool_msg)
                messages.append(tool_msg)
                if ndjson_log_file_handle:
                    from .logging import _log_ndjson_message
                    _log_ndjson_message(ndjson_log_file_handle, model, tool_msg)

            if verbose >= 2:
                total_chars = sum(
                    len(m.get("content", "") or "") for m in messages
                )
                print(
                    f"[round {tool_rounds + 1} complete: "
                    f"{len(messages)} messages, {total_chars} chars]",
                    file=sys.stderr,
                    flush=True,
                )

            tool_rounds += 1
        else:
            if show_thinking and not response_thinking:
                _warn_missing_thinking(model, mode_state)

            assistant_msg = {"role": "assistant", "content": response_content}
            if show_thinking and think_text.strip():
                assistant_msg["thinking"] = think_text
            _stamp_message(assistant_msg)

            messages.append(assistant_msg)
            if ndjson_log_file_handle:
                from .logging import _log_ndjson_message
                if response_thinking:
                    thought_msg = {
                        "role": "assistant",
                        "content": response_thinking,
                        "mode": "thinking"
                    }
                    _log_ndjson_message(ndjson_log_file_handle, model, thought_msg)

                    output_msg = {
                        "role": "assistant",
                        "content": response_content or None,
                        "mode": "output",
                    }
                    _log_ndjson_message(ndjson_log_file_handle, model, output_msg)
                else:
                    _log_ndjson_message(ndjson_log_file_handle, model, assistant_msg)

            final_response = response_content
            state_manager.transition_to(ExecutionState.IDLE)
            break

    if metrics is not None:
        metrics["rounds"] = list(turn_rounds)
        metrics["turn_rounds"] = len(turn_rounds)
        metrics["turn_eval_count"] = sum(r.get("eval_count") or 0 for r in turn_rounds)
        metrics["turn_eval_duration_ns"] = sum(r.get("eval_duration_ns") or 0 for r in turn_rounds)
        metrics["turn_prompt_eval_count"] = sum(r.get("prompt_eval_count") or 0 for r in turn_rounds)
        metrics["turn_prompt_eval_duration_ns"] = sum(r.get("prompt_eval_duration_ns") or 0 for r in turn_rounds)
        if turn_elapsed_started is not None:
            metrics["turn_elapsed_s"] = time.monotonic() - turn_elapsed_started

    return final_response
