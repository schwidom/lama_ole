#!/usr/bin/env python3

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from constants import TRUE_VALUES, FALSE_VALUES

# Ensure the script's directory is in sys.path for sibling imports
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

# Ensure the current working directory is in sys.path for user tool modules
_cwd = os.getcwd()
if _cwd not in sys.path:
    sys.path.insert(0, _cwd)

from parameters import PARAMETERS, process_inspection_flags
from backends.factory import create_backend
from tool_base import (
    RunConfig,
    load_tools,
    set_vision_models,
    run_with_tools,
    get_tool_modules_info,
    sanitize_ctx_threshold,
    DEFAULT_CTX_COMPACT_THRESHOLD,
)
import color_util
from chat import (
    ChatState,
    _drop_incomplete_trailing_messages,
    _replay_history,
    apply_session,
    autosave_session,
    find_recent_session,
    new_session_id,
    run_chat,
)

# ---------------------------------------------------------------------------
# Configuration defaults (env vars + config files)
# ---------------------------------------------------------------------------

_ENV_FILE_USER = os.path.join(os.path.expanduser("~"), ".config", "lama_ole", "lama_ole.env")
_ENV_FILE_PROJECT = os.path.join(os.getcwd(), "lama_ole.env")


def _parse_env_file(path):
    values = {}
    if not os.path.exists(path):
        return values
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                value = value[1:-1]
            values[key] = value
    return values


def load_env_files():
    """Load LAMA_OLE_* defaults from config files into os.environ.

    Precedence: existing shell env vars are never overwritten; the project
    file (./lama_ole.env in the CWD) overrides the user file
    (~/.config/lama_ole/lama_ole.env). Empty values are ignored.
    """
    merged = {}
    for path in (_ENV_FILE_USER, _ENV_FILE_PROJECT):
        merged.update(_parse_env_file(path))
    for key, value in merged.items():
        if value == "":
            continue
        os.environ.setdefault(key, value)


def _env_str(name, default):
    value = os.environ.get(name)
    if not value:
        return default
    return value


def _env_int(name, default):
    value = os.environ.get(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        print(f"Warning: ignoring invalid integer for {name}: {value!r}",
              file=sys.stderr)
        return default


def _env_float(name, default):
    value = os.environ.get(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        print(f"Warning: ignoring invalid number for {name}: {value!r}",
              file=sys.stderr)
        return default


def _env_bool(name, default):
    value = os.environ.get(name)
    if not value:
        return default
    lowered = value.lower()
    if lowered in TRUE_VALUES:
        return True
    if lowered in FALSE_VALUES:
        return False
    print(f"Warning: ignoring invalid boolean for {name}: {value!r}",
          file=sys.stderr)
    return default


def _env_choice(name, default, choices):
    value = os.environ.get(name)
    if not value:
        return default
    if value in choices:
        return value
    print(f"Warning: ignoring invalid value for {name}: {value!r} "
          f"(must be one of {choices})", file=sys.stderr)
    return default


def _env_list(name):
    value = os.environ.get(name)
    if not value:
        return None
    parts = value.replace(",", " ").split()
    return parts or None


def build_parser():
    parser = argparse.ArgumentParser(
        description="A CLI tool to interact with an Ollama instance.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    for spec in PARAMETERS:
        kwargs = {}
        if spec.help:
            kwargs["help"] = spec.help
        if spec.action:
            kwargs["action"] = spec.action
        if spec.choices:
            kwargs["choices"] = spec.choices
        if spec.nargs is not None:
            kwargs["nargs"] = spec.nargs
        if spec.metavar is not None:
            kwargs["metavar"] = spec.metavar
        if spec.dest:
            kwargs["dest"] = spec.dest

        if spec.action == "version":
            kwargs["version"] = spec.help
            kwargs.pop("help", None)
            parser.add_argument(*spec.flags, **kwargs)
            continue

        if spec.type and spec.action not in ("store_true", "store_false", "count", argparse.BooleanOptionalAction):
            kwargs["type"] = spec.type

        # Compute dynamic default from env/config
        if spec.env_var and spec.action != "append":
            if spec.type is int:
                default_val = _env_int(spec.env_var, spec.default)
            elif spec.type is float:
                default_val = _env_float(spec.env_var, spec.default)
            elif spec.type is _env_bool or spec.action == argparse.BooleanOptionalAction or (callable(spec.type) and "bool" in getattr(spec.type, "__name__", "")):
                default_val = _env_bool(spec.env_var, spec.default)
            elif spec.choices:
                default_val = _env_choice(spec.env_var, spec.default, spec.choices)
            else:
                default_val = _env_str(spec.env_var, spec.default)
        else:
            default_val = spec.default

        if spec.action not in ("store_true", "store_false"):
            kwargs["default"] = default_val

        parser.add_argument(*spec.flags, **kwargs)

    return parser


def _merge_tool_lists(env_tools, cli_tools):
    """Combine env/config defaults with CLI tools, deduped, env-first.

    First occurrence wins so a module listed both in config and on the CLI is
    loaded once (load_tools() appends module info on every call).
    """
    merged = []
    for item in (env_tools or []) + (cli_tools or []):
        if item not in merged:
            merged.append(item)
    return merged or None


def _load_skill_text(skill_paths):
    """Load one or more skill files, entropy-check each, and concatenate.

    Each skill file must pass the entropy check (reject binary/random data).
    Returns the concatenated skill text with a blank line between files.
    Exits with an error message on missing/rejected/invalid files.
    """
    from security.entropychecker import EntropyChecker

    parts = []
    for path in skill_paths:
        if not os.path.exists(path):
            print(f"Error: The skill file '{path}' was not found.", file=sys.stderr)
            sys.exit(1)
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except Exception as e:
            print(f"Error reading skill file '{path}': {e}", file=sys.stderr)
            sys.exit(1)

        checker = EntropyChecker()
        result = checker.feed(raw)
        if result.is_suspicious:
            print(
                f"Error: skill file '{path}' rejected by entropy check: {result.reason}",
                file=sys.stderr,
            )
            sys.exit(1)

        content = raw.decode("utf-8", errors="replace")
        parts.append(content)

    return "\n\n".join(parts)


def _resolve_env_defaults(args):
    # --tool: merge env/config defaults with CLI values (unless ignored).
    # --vision_model: strict override (CLI replaces env/config defaults).
    if not args.ignore_config_tools:
        args.tools = _merge_tool_lists(_env_list("LAMA_OLE_TOOL"), args.tools)
    args.skills = _merge_tool_lists(_env_list("LAMA_OLE_SKILL"), args.skills)
    if args.vision_models is None:
        args.vision_models = _env_list("LAMA_OLE_VISION_MODEL")


def _default_sessions_dir():
    """XDG-aware sessions directory (~/.local/share/lama_ole/sessions)."""
    base = os.environ.get("LAMA_OLE_SESSION_DIR")
    if not base:
        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg:
            base = os.path.join(xdg, "lama_ole")
        else:
            base = os.path.join(os.path.expanduser("~"), ".local", "share", "lama_ole")
        base = os.path.join(base, "sessions")
    return base


# ---------------------------------------------------------------------------
# --stats helper functions
# ---------------------------------------------------------------------------


def _compute_stats(data: dict) -> str:
    """Compute statistics from a loaded session file data dict.

    Returns a human-readable string mirroring the /stats REPL command.
    """
    lines = []
    lines.append("Session Statistics")
    lines.append("==================")
    lines.append("")

    model = data.get("model")
    lines.append("Model: {}".format(model if model else "(none)"))

    messages = data.get("messages", [])
    lines.append("Messages: {}".format(len(messages)))
    lines.append("")

    # Message breakdown by role at message level
    role_counts = {}
    tool_call_count = 0
    thinking_count = 0
    for msg in messages:
        role = msg.get("role")
        if role == "assistant":
            if msg.get("thinking") is not None:
                thinking_count += 1
            if msg.get("tool_calls"):
                tool_call_count += 1
            else:
                role_counts["assistant"] = role_counts.get("assistant", 0) + 1
        else:
            role_counts[role] = role_counts.get(role, 0) + 1

    lines.append("Message breakdown by role:")
    for role in ("user", "assistant", "tool", "system"):
        count = role_counts.get(role, 0)
        lines.append("  {}: {}".format(role, count))
    lines.append("  tool_calls: {}".format(tool_call_count))
    lines.append("  thinking: {}".format(thinking_count))
    lines.append("")

    title = data.get("title") or "(untitled)"
    lines.append("Title: {}".format(title))

    session_id = data.get("session_id")
    lines.append("Session ID: {}".format(session_id if session_id else "(none)"))

    created_at = data.get("created_at")
    if created_at:
        lines.append("Created: {}".format(_format_timestamp(created_at)))
    else:
        lines.append("Created: (not set)")

    updated_at = data.get("updated_at")
    if updated_at:
        lines.append("Updated: {}".format(_format_timestamp(updated_at)))
    else:
        lines.append("Updated: (not set)")

    mode = data.get("mode")
    lines.append("Mode: {}".format(mode if mode else "(build)"))

    loaded_tools = data.get("loaded_tool_modules")
    if loaded_tools:
        lines.append("Loaded tools: {}".format(", ".join(loaded_tools)))
    else:
        lines.append("Loaded tools: (none)")

    skill = data.get("skill")
    lines.append("Skill: {}".format(skill if skill else "(none)"))

    sys_prompt = data.get("system_prompt")
    lines.append("System prompt: {}".format("set" if sys_prompt else "none"))

    ctx_usage = data.get("ctx_usage")
    ctx_usage_model = data.get("ctx_usage_model")
    if ctx_usage and ctx_usage.get("prompt_eval_count"):
        pe = ctx_usage["prompt_eval_count"]
        ec = ctx_usage.get("eval_count", 0)
        lines.append("Context usage: {}/{} tokens (model: {})".format(
            pe, ec, ctx_usage_model or "(none)"))
    else:
        lines.append("Context usage: (not recorded)")

    ctx_compact = data.get("ctx_compact")
    ctx_threshold = data.get("ctx_compact_threshold")
    ctx_model = data.get("ctx_compact_model")
    compact_str = "disabled"
    if ctx_compact:
        compact_str = "enabled"
        if ctx_threshold is not None:
            compact_str += " (threshold: {:.0%})".format(ctx_threshold)
        if ctx_model:
            compact_str += ", model: {}".format(ctx_model)
    lines.append("Context compaction: {}".format(compact_str))

    cwd = data.get("cwd")
    lines.append("CWD (from session): {}".format(cwd if cwd else "(not stored)"))
    lines.append("Current working directory: {}".format(os.getcwd()))

    return "\n".join(lines)


def _format_timestamp(ts):
    """Format a Unix timestamp to a human-readable string."""
    import datetime
    try:
        dt = datetime.datetime.fromtimestamp(ts)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, TypeError):
        return str(ts)


def _handle_stats(args):
    """Handle --stats: determine target file, validate, compute and print stats."""
    # Determine target file
    target_file = None
    if args.load is not None:
        target_file = args.load
    elif args.resume:
        sessions_dir = _default_sessions_dir()
        result = find_recent_session(sessions_dir, os.getcwd())
        if result is None:
            print("Error: --stats requires --load or --resume, and no recent session was found.",
                  file=sys.stderr)
            sys.exit(1)
        target_file = result[0]
    else:
        print("Error: --stats requires --load or --resume.", file=sys.stderr)
        sys.exit(1)

    # Validate file existence
    if not os.path.exists(target_file):
        print("Error: file not found: {}".format(target_file), file=sys.stderr)
        sys.exit(1)

    # Read and parse file
    try:
        with open(target_file, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print("Error: could not read file '{}': {}".format(target_file, e),
              file=sys.stderr)
        sys.exit(1)

    if not content or content.strip() == "":
        print("Error: the file is empty.", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        print("Error: invalid JSON in '{}': {}".format(target_file, e),
              file=sys.stderr)
        sys.exit(1)

    # Level 1 validation: must have 'messages' key
    if "messages" not in data:
        print("Error: the file does not contain a 'messages' key.",
              file=sys.stderr)
        sys.exit(1)

    # Check for no messages
    messages = data.get("messages", [])
    if not messages:
        print("Error: the session has no messages.", file=sys.stderr)
        sys.exit(1)

    # Compute and print stats
    stats_str = _compute_stats(data)
    print(stats_str)
    sys.exit(0)


def _resolve_load_path(args, config_dict):
    """Resolve effective load path from --load or LAMA_OLE_LOAD.

    Returns (load_path, warning_message) tuple.
    Warning message is set if --load overrides --resume.
    """
    # Precedence: --load CLI > LAMA_OLE_LOAD env > config
    load_path = None
    if args.load is not None:
        load_path = args.load
    else:
        load_path = os.environ.get("LAMA_OLE_LOAD")
        if not load_path:
            # Check config dict
            for key, value in config_dict.items():
                if key == "LAMA_OLE_LOAD" and value:
                    load_path = value
                    break

    if load_path is not None and not os.path.exists(load_path):
        print("Error: file not found: {}".format(load_path), file=sys.stderr)
        sys.exit(1)

    warning = None
    if load_path is not None and args.resume:
        warning = "Warning: --load overrides --resume; --resume is ignored."

    return load_path, warning


def _prompt_model_choice(cli_model, session_model):
    """Ask the user which model to keep when CLI and session disagree.

    Returns one of "session", "cli", or "abort".
    """
    while True:
        print(
            f"The session uses model '{session_model}' but the CLI set "
            f"'{cli_model}'.",
            file=sys.stderr,
        )
        ans = input(
            "Use the (s)ession model, the (c)li model, or (a)bort? [s/c/a]: "
        ).strip().lower()
        if ans in ("s", "session", ""):
            return "session"
        if ans in ("c", "cli"):
            return "cli"
        if ans in ("a", "abort"):
            return "abort"
        print("Please answer s, c or a.", file=sys.stderr)


def _load_session_into(state, path):
    """Load a session from a file into ``state``.

    Handles model mismatch prompt and session ID prompt.
    Does NOT apply ctx_* settings (informational only).
    """
    if not os.path.exists(path):
        print("Error: file not found: {}".format(path), file=sys.stderr)
        sys.exit(1)

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print("Error: could not read file '{}': {}".format(path, e),
              file=sys.stderr)
        sys.exit(1)

    if not content or content.strip() == "":
        print("Error: the file is empty.", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        print("Error: invalid JSON in '{}': {}".format(path, e),
              file=sys.stderr)
        sys.exit(1)

    # Level 1 validation: must have 'messages' key
    if "messages" not in data:
        print("Error: the file does not contain a 'messages' key.",
              file=sys.stderr)
        sys.exit(1)

    messages = data.get("messages", [])
    if not messages:
        print("Error: the session has no messages.", file=sys.stderr)
        sys.exit(1)

    # Model mismatch prompt
    session_model = data.get("model")
    cli_model = state.config.model
    if cli_model and session_model and cli_model != session_model:
        choice = _prompt_model_choice(cli_model, session_model)
        if choice == "abort":
            print("Aborted. Returning to chat.", file=sys.stderr)
            return
        if choice == "cli":
            data["model"] = cli_model

    # Session ID prompt
    if data.get("session_id"):
        title = data.get("title") or "(untitled)"
        while True:
            ans = input(
                "The loaded session has session_id '{}' "
                "(title: '{}').\n"
                "Preserve this session ID or create a new one? [p/n]: ".format(
                    data["session_id"], title
                )
            ).strip().lower()
            if ans in ("p", "preserve", ""):
                break
            if ans in ("n", "new"):
                data["session_id"] = new_session_id()
                break
            print("Please answer p or n.", file=sys.stderr)

    # Apply session without ctx_* settings (informational only)
    apply_session(state, data, source=path, skip_ctx_settings=True)
    title = data.get("title") or "(untitled)"
    n = len(state.messages)
    print(
        "Loaded session '{}' ({} messages) from {}.".format(
            title, n, path
        ),
        file=sys.stderr,
    )


def _resume_session_into(state, resume):
    """Restore the most recent session into ``state`` at startup.

    If the CLI model differs from the session's model, ask the user which to
    keep (the session model, the CLI model, or abort). ``args.model`` is not
    updated for the resumed turns; the chosen model is applied to the state.
    """
    path, data = resume
    session_model = data.get("model")
    cli_model = state.config.model
    if cli_model and session_model and cli_model != session_model:
        choice = _prompt_model_choice(cli_model, session_model)
        if choice == "abort":
            sys.exit(0)
        if choice == "cli":
            data["model"] = cli_model
    apply_session(state, data, source=path)
    title = data.get("title") or "(untitled)"
    n = len(state.messages)
    print(
        f"Resumed session '{title}' ({n} messages). Use --no-resume to start fresh.",
        file=sys.stderr,
    )
    _replay_history(state, color_util.color_mode_enabled(state.config.color))


def main():
    initial_env = dict(os.environ)
    config_dict = {}
    for path in (_ENV_FILE_USER, _ENV_FILE_PROJECT):
        config_dict.update(_parse_env_file(path))

    load_env_files()

    if process_inspection_flags(sys.argv[1:], config_dict, initial_env):
        sys.exit(0)

    # -----------------------------------------------------------------------
    # Segmented argv parsing (dynamic tool params): tool-contributed flags
    # (--docsearch/--docscan/--docdb/...) must appear AFTER the --tool that
    # provides them. Pre-load modules named via LAMA_OLE_TOOL env so their
    # params are available from the start.
    # -----------------------------------------------------------------------
    _env_tools = _env_list("LAMA_OLE_TOOL") or []
    for _m in _env_tools:
        try:
            load_tools(_m)
        except Exception as _e:
            print(f"Error loading tool module '{_m}': {_e}", file=sys.stderr)
            sys.exit(1)

    def _split_argv_by_tool(_argv):
        _segs = []
        _cur = []
        _i = 0
        _n = len(_argv)
        while _i < _n:
            if _argv[_i] == "--tool" and _i + 1 < _n:
                _segs.append((_cur, _argv[_i + 1]))
                _cur = []
                _i += 2
                continue
            _cur.append(_argv[_i])
            _i += 1
        _segs.append((_cur, None))
        return _segs

    def _flags_in_segment(_seg_tokens, _spec):
        _tset = set(_seg_tokens)
        for _f in _spec.flags:
            if _f in _tset:
                return True
        for _tok in _seg_tokens:
            if "=" in _tok and _tok.split("=", 1)[0] in _spec.flags:
                return True
        if _spec.action == argparse.BooleanOptionalAction:
            for _f in _spec.flags:
                if _f.startswith("--") and ("--no-" + _f[2:]) in _tset:
                    return True
        return False

    _segments = _split_argv_by_tool(sys.argv[1:])
    _cli_tool_modules = []
    _merged = None
    for _seg_tokens, _next_tool in _segments:
        _parser = build_parser()
        try:
            _seg_ns = _parser.parse_args(_seg_tokens)
        except SystemExit:
            raise
        if _merged is None:
            _merged = _seg_ns
        else:
            for _spec in PARAMETERS:
                if _flags_in_segment(_seg_tokens, _spec):
                    _attr = _spec.dest or _spec.name
                    try:
                        setattr(_merged, _attr, getattr(_seg_ns, _attr))
                    except Exception:
                        pass
        if _next_tool is not None:
            _cli_tool_modules.append(_next_tool)
            try:
                load_tools(_next_tool)
            except Exception as _e:
                print(f"Error loading tool module '{_next_tool}': {_e}", file=sys.stderr)
                sys.exit(1)

    if _merged is None:
        _merged = build_parser().parse_args([])
    args = _merged
    # carry the dynamically loaded tool module names so _resolve_env_defaults merges them
    if not getattr(args, "tools", None):
        args.tools = _cli_tool_modules if _cli_tool_modules else None
    else:
        # append cli modules not already present
        for _m in _cli_tool_modules:
            if _m not in args.tools:
                args.tools.append(_m)
    _resolve_env_defaults(args)

    # -----------------------------------------------------------------------
    # --stats: print session file statistics and exit (before any other work)
    # -----------------------------------------------------------------------
    if args.stats:
        _handle_stats(args)

    # -----------------------------------------------------------------------
    # --load / LAMA_OLE_LOAD resolution
    # -----------------------------------------------------------------------
    load_path, load_warning = _resolve_load_path(args, config_dict)

    if load_path is not None and not args.chat:
        print("Error: --load requires --chat", file=sys.stderr)
        sys.exit(1)

    if load_warning:
        print(load_warning, file=sys.stderr)

    color_util.configure(
        prompt=_env_str("LAMA_OLE_COLOR_PROMPT", None),
        thinking=_env_str("LAMA_OLE_COLOR_THINKING", None),
        output=_env_str("LAMA_OLE_COLOR_OUTPUT", None),
        input=_env_str("LAMA_OLE_COLOR_INPUT", None),
        meter_low=_env_str("LAMA_OLE_COLOR_METER_LOW", None),
        meter_mid=_env_str("LAMA_OLE_COLOR_METER_MID", None),
        meter_high=_env_str("LAMA_OLE_COLOR_METER_HIGH", None),
    )

    # --host defaults to None; each backend supplies its own default (plus
    # port/scheme normalization) via backends._compat.normalize_host.
    client = create_backend(args.backend, host=args.host, api_key=args.api_key)

    if (
        args.keep_alive is not None
        and not getattr(client, "supports_keep_alive", False)
    ):
        print(
            f"[WARNING] keep_alive is not supported by the '{args.backend}' "
            "backend; it will be ignored.",
            file=sys.stderr,
        )

    # Propagate vision models to tools (media understanding keeps talking to
    # an Ollama endpoint directly, see LAMA_OLE_VISION_HOST).
    if args.vision_models:
        set_vision_models(args.vision_models)

    if args.serve_blobs:
        from tools.blob_server import run_server
        run_server(host=args.blob_host, port=args.blob_port)
        sys.exit(0)

    if args.list:
        print("available models:")
        for model in client.list_models():
            print(model)

    if args.ps:
        print("running models:")
        for model in client.list_running():
            print(model.name)

    if args.list or args.ps:
        sys.exit(0)

    if args.stop:
        client.stop_model(args.stop)
        print(f"Stopped model: {args.stop}")
        sys.exit(0)

    if args.transfer:
        from ollama import Client  # lazy import: transfer stays Ollama-only

        src_raw, dst_host = args.transfer
        dst_host = _normalize_host(dst_host)
        if not args.model:
            print("Error: --model is required for --transfer", file=sys.stderr)
            sys.exit(1)
        client_dst = Client(host=dst_host)
        if src_raw == "localhost" or src_raw == "localhost:11434":
            source = FilesystemBlobSource()
            client_src = Client(host=_normalize_host("localhost"))
            show = client_src.show(model=args.model)
            create_kwargs = _parse_modelfile(show.modelfile or "")
            _transfer_model(client_dst, args.model, source, create_kwargs)
        elif src_raw.startswith("http://") or src_raw.startswith("https://"):
            blob_url = src_raw.rstrip("/")
            source = HttpBlobSource(blob_url)
            config = source.get_config(args.model)
            create_kwargs = _config_to_create_kwargs(config)
            _transfer_model(client_dst, args.model, source, create_kwargs)
        else:
            print("Error: source must be 'localhost' or a blob server URL "
                  "(http://...)", file=sys.stderr)
            sys.exit(1)
        source.cleanup()
        sys.exit(0)

    # Load tools if --tool was specified (needed early for --help-tools)
    loaded_tools = []
    if args.tools:
        for module_name in args.tools:
            try:
                module_tools = load_tools(module_name)
                loaded_tools.extend(module_tools)
            except Exception as e:
                print(f"Error loading tool module '{module_name}': {e}", file=sys.stderr)
                sys.exit(1)
    backend_tools = client.convert_tools(loaded_tools)

    # One-shot doc search / doc scan mode
    if getattr(args, "docsearch", None) or getattr(args, "docscan", None):
        loaded_names = [m.module_name for m in get_tool_modules_info()]
        if "tools.doc_search_tools" not in loaded_names and "doc_search_tools" not in loaded_names:
            print("doc_search_tools not loaded; add --tool tools.doc_search_tools (or set LAMA_OLE_TOOL=tools.doc_search_tools)", file=sys.stderr)
            sys.exit(1)
        from doc_search.search import search as _ds_search, index_path as _ds_index
        import json as _json
        db_root = getattr(args, "docdb", None)
        if db_root is None:
            db_root = os.environ.get("LAMA_OLE_DOCSEARCH_DB") or "./docsearch"
        if getattr(args, "docscan", None):
            res = _ds_index(args.docscan, db_root=db_root)
            print(_json.dumps(res, separators=(",", ":")))
            sys.exit(0 if res.get("status") == "success" else 1)
        if getattr(args, "docsearch", None):
            res = _ds_search(args.docsearch, db_root=db_root)
            print(_json.dumps(res, separators=(",", ":")))
            sys.exit(0 if res.get("status") == "success" else 1)

    if args.debug:
        import code
        print(f"Debug mode: model={args.model}, backend={args.backend}")
        local_vars = {
            'client': client,
            'loaded_tools': loaded_tools,
            'backend_tools': backend_tools,
            'args': args,
            'sys': sys,
            'os': os,
        }
        code.interact(local=locals())
        sys.exit(0)

    # Handle --help-tools
    if args.help_tools:
        modules = get_tool_modules_info()
        if not modules:
            print("No tool modules loaded. Use --tool to specify modules.", file=sys.stderr)
            sys.exit(1)
        for mod in modules:
            print(f"Tool Module: {mod.module_name}")
            if mod.env_vars:
                print("  Environment Variables:")
                for var, desc in mod.env_vars.items():
                    print(f"    {var}: {desc}")
            print("  Functions:")
            for t in mod.tools:
                sig_parts = []
                for pname, pinfo in t.parameters.get("properties", {}).items():
                    ptype = pinfo.get("type", "string")
                    if pname in t.parameters.get("required", []):
                        sig_parts.append(f"{pname}: {ptype}")
                    else:
                        sig_parts.append(f"[{pname}: {ptype}]")
                sig = ", ".join(sig_parts)
                print(f"    {t.name}({sig}) — {t.description}")
        sys.exit(0)

    if not args.model :
        print( "Error: model has to be set (parameter -m , --model)", file=sys.stderr)
        sys.exit(1)

    # Determine initial content (optional in chat mode)
    content = ""
    if args.input:
        content = args.input
    elif args.inputfile:
        if os.path.exists(args.inputfile):
            with open(args.inputfile, 'r', encoding='utf-8') as f:
                content = f.read()
        else:
            print(f"Error: The file '{args.inputfile}' was not found.", file=sys.stderr)
            sys.exit(1)
    elif args.stdin:
        content = sys.stdin.read()

    if not args.chat and not content.strip():
        print("Error: You must provide content via -i, --inputfile, --stdin or use --chat", file=sys.stderr)
        sys.exit(1)

    system_prompt = None
    if args.system_prompt :
        system_prompt = args.system_prompt
    elif args.system_prompt_file :
        if os.path.exists(args.system_prompt_file):
            with open(args.system_prompt_file, 'r', encoding='utf-8') as f:
                system_prompt = f.read()
        else:
            print(f"Error: The file '{args.system_prompt_file}' was not found.", file=sys.stderr)
            sys.exit(1)

    skill_text = None
    if args.skills:
        skill_text = _load_skill_text(args.skills)


    # File handles
    thought_file_handle = None
    output_file_handle = None

    # Open the thought log if provided
    if args.thoughtlog:
        if os.path.exists(args.thoughtlog):
            print(f"Error: The file '{args.thoughtlog}' already exists.", file=sys.stderr)
            sys.exit(1)
        thought_file_handle = open(args.thoughtlog, "w", encoding="utf-8")

    # Open the output log if provided
    if args.outlog:
        if os.path.exists(args.outlog):
            print(f"Error: The file '{args.outlog}' already exists.", file=sys.stderr)
            sys.exit(1)
        output_file_handle = open(args.outlog, "w", encoding="utf-8")

    # Open the toolcall log if provided
    toolcall_file_handle = None
    if args.toolcalllog:
        if os.path.exists(args.toolcalllog):
            print(f"Error: The file '{args.toolcalllog}' already exists.", file=sys.stderr)
            sys.exit(1)
        toolcall_file_handle = open(args.toolcalllog, "w", encoding="utf-8")

    # Open the chat input log if provided
    chatinput_file_handle = None
    if args.chatinputlog:
        if os.path.exists(args.chatinputlog):
            print(f"Error: The file '{args.chatinputlog}' already exists.", file=sys.stderr)
            sys.exit(1)
        chatinput_file_handle = open(args.chatinputlog, "w", encoding="utf-8")

    # Open the ndjson conversation log if provided
    ndjson_log_file_handle = None
    if args.logndjson:
        if os.path.exists(args.logndjson):
            print(f"Error: The file '{args.logndjson}' already exists.", file=sys.stderr)
            sys.exit(1)
        ndjson_log_file_handle = open(args.logndjson, "w", encoding="utf-8")

    options = {
        "temperature": args.temperature,
    }

    if None != args.top_p:
        options["top_p"] = args.top_p

    if None != args.top_k:
        options["top_k"] = args.top_k

    if None != args.repeat_penalty:
        options["repeat_penalty"] = args.repeat_penalty

    if None != args.presence_penalty:
        options["presence_penalty"] = args.presence_penalty

    if None != args.num_ctx:
        options["num_ctx"] = args.num_ctx

    if None != args.num_gpu:
        options["num_gpu"] = args.num_gpu

    run_config = RunConfig(
        client=client,
        model=args.model,
        options=options,
        keep_alive=args.keep_alive,
        show_thinking=args.thinking,
        no_safety_system_prompt=args.no_safety_system_prompt,
        system_prompt=system_prompt,
        skill_text=skill_text,
        verbose=args.verbose,
        safe=args.safe,
        mode=args.mode,
        show_diff=args.show_diff,
        thought_file_handle=thought_file_handle,
        output_file_handle=output_file_handle,
        toolcall_file_handle=toolcall_file_handle,
        chatinput_file_handle=chatinput_file_handle,
        max_tool_rounds=args.max_tool_rounds,
        max_tool_rounds_continuation=args.max_tool_rounds_continuation,
        websearch=args.ollama_websearch,
        ndjson_log_file_handle=ndjson_log_file_handle,
        color=args.color,
    )

    try:
        if args.chat:
            sessions_dir = _default_sessions_dir()

            state = ChatState(
                config=run_config,
                backend_name=args.backend,
                host=args.host,
                api_key=args.api_key,
                loaded_tools=loaded_tools,
                loaded_tool_modules=list(args.tools or []),
                backend_tools=backend_tools,
                ndjson_log_path=args.logndjson,
                sessions_dir=sessions_dir,
                session_autosave=args.autosave,
                ctx_meter=args.ctx_meter,
                ctx_max=_env_int("LAMA_OLE_CTX_SIZE", None),
                ctx_compact=args.auto_compact,
                ctx_compact_threshold=args.auto_compact_threshold,
                ctx_compact_model=args.auto_compact_model,
            )
            # Handle --load or --resume session source
            if load_path is not None:
                _load_session_into(state, load_path)
            elif args.resume:
                resume = find_recent_session(sessions_dir, os.getcwd())
                if resume:
                    _resume_session_into(state, resume)
            if not state.session_id:
                state.session_id = new_session_id()
                state.session_created_at = time.time()
            if content.strip():
                user_msg = {"role": "user", "content": content}
                state.stamp_message(user_msg)
                state.messages.append(user_msg)
                state.log_ndjson(user_msg)
                try:
                    metrics = {}
                    run_with_tools(
                        messages=state.messages,
                        loaded_tools=state.loaded_tools,
                        backend_tools=state.backend_tools,
                        config=state.config,
                        state_manager=state.state_manager,
                        metrics=metrics,
                    )
                    state.ctx_usage = metrics
                    state.ctx_usage_model = state.config.model
                    autosave_session(state)
                except KeyboardInterrupt:
                    print(
                        "\nInterrupted during initial response. Entering chat mode.",
                        file=sys.stderr,
                    )
                    state.state_manager.reset()
                    # Partial rollback: keep the user message (and the system
                    # prompt that run_with_tools prepended for this turn) plus
                    # any completed tool rounds; drop only a trailing tool call
                    # that never got its result.
                    _drop_incomplete_trailing_messages(state, user_msg)
            run_chat(state)
        else:
            from tool_base.logging import _log_ndjson_message

            messages = [{"role": "user", "content": content}]
            if ndjson_log_file_handle:
                _log_ndjson_message(ndjson_log_file_handle, args.model, messages[0])
            run_with_tools(
                messages=messages,
                loaded_tools=loaded_tools,
                backend_tools=backend_tools,
                config=run_config,
            )

    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if thought_file_handle:
            thought_file_handle.close()
        if output_file_handle:
            output_file_handle.close()
        if toolcall_file_handle:
            toolcall_file_handle.close()
        if chatinput_file_handle:
            chatinput_file_handle.close()
        if ndjson_log_file_handle:
            ndjson_log_file_handle.close()
        if args.chat and args.autosave and "state" in locals():
            try:
                autosave_session(state)
            except Exception as e:
                print(f"Error saving session on exit: {e}", file=sys.stderr)

# ---------------------------------------------------------------------------
# Transfer implementation
# ---------------------------------------------------------------------------


def _normalize_host(host):
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    if ":" not in host.split("/")[-1]:
        host = f"{host}:11434"
    return host


def _find_models_dir():
    env = os.environ.get("OLLAMA_MODELS")
    if env and os.path.isdir(os.path.join(env, "blobs")):
        return env
    candidates = [
        os.path.expanduser("~/.ollama/models"),
        "/usr/share/ollama/.ollama/models",
        "/var/snap/ollama/common/models",
    ]
    for path in candidates:
        if os.path.isdir(os.path.join(path, "blobs")):
            return path
    return os.path.expanduser("~/.ollama/models")


def _parse_model_name(model):
    if ":" in model:
        name, tag = model.split(":", 1)
    else:
        name, tag = model, "latest"
    return name, tag


def _manifest_path(models_dir, model):
    name, tag = _parse_model_name(model)
    if "/" in name:
        parts = ["manifests", "registry.ollama.ai"] + name.split("/")
    else:
        parts = ["manifests", "registry.ollama.ai", "library", name]
    return os.path.join(models_dir, *parts, tag)


def _read_manifest(models_dir, model):
    path = _manifest_path(models_dir, model)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def _find_gguf_digest(manifest):
    for layer in manifest.get("layers", []):
        if layer.get("mediaType") == "application/vnd.ollama.image.model":
            return layer["digest"]
    layers = manifest.get("layers", [])
    if layers:
        return max(layers, key=lambda l: l.get("size", 0))["digest"]
    return None


def _upload_blobs(client_dst, blob_source, manifest):
    digests = [l["digest"] for l in manifest.get("layers", [])]
    config = manifest.get("config")
    if config:
        digests.append(config["digest"])
    for digest in digests:
        print(f"  Uploading blob {digest[:20]}...", file=sys.stderr, end=" ")
        try:
            blob_path = blob_source.get_blob_path(digest)
            client_dst.create_blob(Path(blob_path))
            print("OK", file=sys.stderr)
        except Exception as e:
            print(f"error: {e}", file=sys.stderr)
            raise


def _parse_param_value(val):
    val = val.strip()
    if len(val) >= 2 and val[0] == val[-1] == '"':
        return val[1:-1]
    if val.lower() == "true":
        return True
    if val.lower() == "false":
        return False
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


def _is_model_name(value):
    if value.startswith(("/", "./", "../", "~", "@")):
        return False
    if "\\" in value:
        return False
    if value.lower().endswith((".gguf", ".bin", ".safetensors")):
        return False
    return True

def _parse_modelfile(modelfile):
    kwargs = {}
    params = {}
    text = re.sub(r"(?m)^\s*#.*$", "", modelfile)

    m = re.search(r"^FROM\s+(.+)$", text, re.MULTILINE)
    if m:
        from_val = m.group(1).strip()
        if _is_model_name(from_val):
            kwargs["from_"] = from_val

    for directive in ("TEMPLATE", "SYSTEM", "LICENSE"):
        m = re.search(
            rf'^{directive}\s+"""(.*?)"""\s*$',
            text, re.MULTILINE | re.DOTALL,
        )
        if m:
            kwargs[directive.lower()] = m.group(1).strip()

    for m in re.finditer(r"^PARAMETER\s+(\S+)\s+(.+)$", text, re.MULTILINE):
        key = m.group(1)
        val = m.group(2).strip()
        if key == "stop":
            params.setdefault("stop", []).append(_parse_param_value(val))
        else:
            params[key] = _parse_param_value(val)

    if params:
        kwargs["parameters"] = params
    return kwargs



def _config_to_create_kwargs(config):
    kwargs = {}
    params = {}
    for key, val in config.items():
        if key == "template":
            kwargs["template"] = val
        elif key == "system":
            kwargs["system"] = val
        elif key == "license":
            kwargs["license"] = val
        elif key == "stop" and isinstance(val, list):
            params["stop"] = val
        elif not isinstance(val, (list, dict)):
            params[key] = val
    if params:
        kwargs["parameters"] = params
    return kwargs


class BlobSource:
    def get_manifest(self, model_name):
        raise NotImplementedError

    def get_blob_path(self, digest):
        raise NotImplementedError

    def cleanup(self):
        pass


class FilesystemBlobSource(BlobSource):
    def __init__(self, models_dir=None):
        self.models_dir = models_dir or _find_models_dir()

    def get_manifest(self, model_name):
        return _read_manifest(self.models_dir, model_name)

    def get_blob_path(self, digest):
        safe = digest.replace(":", "-")
        return os.path.join(self.models_dir, "blobs", safe)


class HttpBlobSource(BlobSource):
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")
        self._temp_dir = tempfile.mkdtemp(prefix="lama_ole_blobs_")

    def get_manifest(self, model_name):
        name, tag = _parse_model_name(model_name)
        url = f"{self.base_url}/manifest/{name}/{tag}"
        with urllib.request.urlopen(url) as resp:
            return json.loads(resp.read().decode())

    def get_blob_path(self, digest):
        safe = digest.replace(":", "-")
        local_path = os.path.join(self._temp_dir, safe)
        if os.path.exists(local_path):
            return local_path
        url = f"{self.base_url}/blobs/{safe}"
        with urllib.request.urlopen(url) as resp, \
             open(local_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
        return local_path

    def get_config(self, model_name):
        name, tag = _parse_model_name(model_name)
        url = f"{self.base_url}/show/{name}/{tag}"
        with urllib.request.urlopen(url) as resp:
            data = json.loads(resp.read().decode())
        return data.get("config", {})

    def cleanup(self):
        shutil.rmtree(self._temp_dir, ignore_errors=True)


def _transfer_model(client_dst, model, blob_source, create_kwargs):
    print(f"Transferring '{model}' ...", file=sys.stderr)

    manifest = blob_source.get_manifest(model)
    if not manifest:
        print("Error: manifest not found", file=sys.stderr)
        sys.exit(1)

    _upload_blobs(client_dst, blob_source, manifest)

    gguf_digest = _find_gguf_digest(manifest)
    if gguf_digest:
        create_kwargs.setdefault("files", {})["model.gguf"] = gguf_digest

    print("  Creating model ...", file=sys.stderr, end=" ")
    client_dst.create(model=model, stream=False, **create_kwargs)
    print("OK", file=sys.stderr)
    print(f"Model '{model}' transferred successfully.", file=sys.stderr)


if __name__ == "__main__":
    main()
