"""Parameter specifications and CLI/environment/config inspection module for lama_ole."""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union

from tool_base import DEFAULT_CTX_COMPACT_THRESHOLD, sanitize_ctx_threshold
from version import VERSION

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _parse_bool(val: Any) -> Optional[bool]:
    if isinstance(val, bool):
        return val
    if val is None:
        return None
    s = str(val).lower().strip()
    if s in _TRUE_VALUES:
        return True
    if s in _FALSE_VALUES:
        return False
    return None


@dataclass
class ParameterSpec:
    name: str
    flags: List[str]
    dest: Optional[str] = None
    env_var: Optional[str] = None
    type: Any = str
    default: Any = None
    choices: Optional[Sequence[Any]] = None
    action: Optional[Union[str, type]] = None
    nargs: Optional[Union[int, str]] = None
    metavar: Optional[Union[str, Tuple[str, ...]]] = None
    help: str = ""
    is_inspection: bool = False


# Catalog of all program parameters
PARAMETERS: List[ParameterSpec] = [
    ParameterSpec(
        name="version",
        flags=["-V", "--version"],
        action="version",
        # help="0.0.66",
        help=VERSION,
    ),
    ParameterSpec(
        name="host",
        flags=["--host"],
        env_var="LAMA_OLE_HOST",
        default="http://localhost:11434",
        help="The host of the ollama instance (e.g. http://localhost:11434)",
    ),
    ParameterSpec(
        name="model",
        flags=["-m", "--model"],
        env_var="LAMA_OLE_MODEL",
        default=None,
        help="The model name to use (e.g., gemma2:2b)",
    ),
    ParameterSpec(
        name="input",
        flags=["-i", "--input"],
        default=None,
        help="The input string to send to the model",
    ),
    ParameterSpec(
        name="inputfile",
        flags=["-f", "--inputfile"],
        default=None,
        help="Path to a file to be used as input",
    ),
    ParameterSpec(
        name="stdin",
        flags=["--stdin"],
        action="store_true",
        help="If set, read the input from standard input instead of --input or --inputfile",
    ),
    ParameterSpec(
        name="thinking",
        flags=["-t", "--thinking"],
        env_var="LAMA_OLE_THINKING",
        action=argparse.BooleanOptionalAction,
        default=False,
        type=_parse_bool,
        help="If set, output the model's thought process to the console",
    ),
    ParameterSpec(
        name="thoughtlog",
        flags=["--thoughtlog"],
        default=None,
        help="Path to a log file where the model's thoughts should be saved (independently of -t)",
    ),
    ParameterSpec(
        name="outlog",
        flags=["-o", "--outlog"],
        default=None,
        help="Path to a log file where the main output of the model should be saved",
    ),
    ParameterSpec(
        name="toolcalllog",
        flags=["--toolcalllog"],
        default=None,
        help="Path to a log file where tool calls should be logged (similar to -v output)",
    ),
    ParameterSpec(
        name="chatinputlog",
        flags=["--chatinputlog"],
        default=None,
        help="Path to a log file where all user input (stdin, --input/--inputfile, and chat REPL) should be logged with timestamps",
    ),
    ParameterSpec(
        name="logndjson",
        flags=["--logndjson"],
        default=None,
        help="Path to a newline-delimited JSON log file where every conversation message is appended as its own line",
    ),
    ParameterSpec(
        name="temperature",
        flags=["--temperature"],
        env_var="LAMA_OLE_TEMPERATURE",
        type=float,
        default=0.0,
        help="Set the sampling temperature (e.g., 0.7)",
    ),
    ParameterSpec(
        name="num_ctx",
        flags=["--num_ctx"],
        env_var="LAMA_OLE_NUM_CTX",
        type=int,
        default=None,
        help="Set the context window (e.g., 4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576)",
    ),
    ParameterSpec(
        name="num_gpu",
        flags=["--num_gpu"],
        env_var="LAMA_OLE_NUM_GPU",
        type=int,
        default=None,
        help="Set the amount of GPU cores",
    ),
    ParameterSpec(
        name="keep_alive",
        flags=["--keep_alive"],
        env_var="LAMA_OLE_KEEP_ALIVE",
        default=None,
        help="Keep model in memory (e.g., '5m', '1h' or a number of seconds)",
    ),
    ParameterSpec(
        name="list",
        flags=["-l", "--list"],
        action="store_true",
        help="List all available models and exit",
    ),
    ParameterSpec(
        name="ps",
        flags=["--ps"],
        action="store_true",
        help="List all running models and exit",
    ),
    ParameterSpec(
        name="stop",
        flags=["--stop"],
        metavar="MODEL",
        default=None,
        help="Stop/unload a running model (e.g., 'gemma2:2b')",
    ),
    ParameterSpec(
        name="ollama_websearch",
        flags=["--ollama_websearch"],
        env_var="LAMA_OLE_OLLAMA_WEBSRCH",
        action=argparse.BooleanOptionalAction,
        default=False,
        type=_parse_bool,
        help="Activate Ollama's built-in web search tool",
    ),
    ParameterSpec(
        name="verbose",
        flags=["-v", "--verbose"],
        env_var="LAMA_OLE_VERBOSE",
        action="count",
        default=0,
        type=int,
        help="Increase verbosity level (repeat: -v, -vv, -vvv)",
    ),
    ParameterSpec(
        name="chat",
        flags=["--chat"],
        env_var="LAMA_OLE_CHAT",
        action=argparse.BooleanOptionalAction,
        default=False,
        type=_parse_bool,
        help="Start an interactive chat REPL session",
    ),
    ParameterSpec(
        name="resume",
        flags=["--resume"],
        env_var="LAMA_OLE_RESUME",
        action=argparse.BooleanOptionalAction,
        default=True,
        type=_parse_bool,
        help="Automatically resume the most recent session for the current directory on startup (use --no-resume to always start fresh)",
    ),
    ParameterSpec(
        name="autosave",
        flags=["--autosave"],
        env_var="LAMA_OLE_AUTOSAVE",
        action=argparse.BooleanOptionalAction,
        default=True,
        type=_parse_bool,
        help="Automatically save the current chat session to disk after every turn and on exit (use --no-autosave to stop writing session files)",
    ),
    ParameterSpec(
        name="show_diff",
        flags=["--diff"],
        dest="show_diff",
        env_var="LAMA_OLE_SHOW_DIFF",
        action=argparse.BooleanOptionalAction,
        default=True,
        type=_parse_bool,
        help="Show a colored unified diff of each file write (edit/create/append/apply_patch) in the output (use --no-diff to hide it)",
    ),
    ParameterSpec(
        name="color",
        flags=["--color"],
        env_var="LAMA_OLE_COLOR",
        default="auto",
        choices=["auto", "always", "never", "none"],
        help="Colorize user input, thinking, and LLM output: 'auto' (TTY only), 'always', or 'never'/'none'",
    ),
    ParameterSpec(
        name="ctx_meter",
        flags=["--ctx-meter"],
        env_var="LAMA_OLE_CTX_METER",
        action=argparse.BooleanOptionalAction,
        default=True,
        type=_parse_bool,
        help="Show a context-window usage meter in chat mode (live prompt gauge). The window size is taken from --num_ctx, LAMA_OLE_CTX_SIZE, or the running model",
    ),
    ParameterSpec(
        name="auto_compact",
        flags=["--auto-compact"],
        env_var="LAMA_OLE_AUTO_COMPACT",
        action=argparse.BooleanOptionalAction,
        default=False,
        type=_parse_bool,
        help="Enable auto-compaction: when the context window crosses the threshold, summarize older context (keeping recent turns verbatim)",
    ),
    ParameterSpec(
        name="auto_compact_threshold",
        flags=["--auto-compact-threshold"],
        env_var="LAMA_OLE_AUTO_COMPACT_THRESHOLD",
        type=sanitize_ctx_threshold,
        default=sanitize_ctx_threshold(DEFAULT_CTX_COMPACT_THRESHOLD),
        help="Fraction of the context window at which auto-compaction triggers (must be in (0, 1])",
    ),
    ParameterSpec(
        name="auto_compact_model",
        flags=["--auto-compact-model"],
        env_var="LAMA_OLE_AUTO_COMPACT_MODEL",
        default=None,
        help="Model used to produce compaction summaries (falls back to the chat model)",
    ),
    ParameterSpec(
        name="safe",
        flags=["--safe"],
        env_var="LAMA_OLE_SAFE",
        action=argparse.BooleanOptionalAction,
        default=False,
        type=_parse_bool,
        help="Enable user confirmation before dangerous tool operations",
    ),
    ParameterSpec(
        name="mode",
        flags=["--mode"],
        env_var="LAMA_OLE_MODE",
        default="build",
        choices=["build", "plan"],
        help="Chat agent mode: 'build' (full tools, changes allowed) or 'plan' (all tools advertised, write tools blocked until /build)",
    ),
    ParameterSpec(
        name="tools",
        flags=["--tool"],
        dest="tools",
        env_var="LAMA_OLE_TOOL",
        action="append",
        default=None,
        help="Python module name providing tool functions (can be repeated); appends to tools configured via LAMA_OLE_TOOL",
    ),
    ParameterSpec(
        name="skills",
        flags=["--skill"],
        dest="skills",
        env_var="LAMA_OLE_SKILL",
        action="append",
        default=None,
        help="Path to a skill file whose text is loaded into the system role (can be repeated; files are concatenated); appends to skills configured via LAMA_OLE_SKILL",
    ),
    ParameterSpec(
        name="ignore_config_tools",
        flags=["--ignore-config-tools"],
        action="store_true",
        help="Ignore tools configured via LAMA_OLE_TOOL (shell/env/config) for this run; only --tool values are used",
    ),
    ParameterSpec(
        name="max_tool_rounds",
        flags=["--max_tool_rounds"],
        env_var="LAMA_OLE_MAX_TOOL_ROUNDS",
        type=int,
        default=None,
        help="Maximum number of tool-calling rounds (no limit when unset)",
    ),
    ParameterSpec(
        name="vision_models",
        flags=["--vision_model"],
        dest="vision_models",
        env_var="LAMA_OLE_VISION_MODEL",
        action="append",
        default=None,
        help="Vision model name available for media understanding tools (can be repeated)",
    ),
    ParameterSpec(
        name="help_tools",
        flags=["--help-tools"],
        action="store_true",
        help="Show documentation for loaded tool modules and exit",
    ),
    ParameterSpec(
        name="transfer",
        flags=["--transfer"],
        nargs=2,
        metavar=("SOURCE", "DEST"),
        help="Transfer a model from SOURCE to DEST ollama instance",
    ),
    ParameterSpec(
        name="serve_blobs",
        flags=["--serve-blobs"],
        action="store_true",
        help="Start a blob HTTP server for remote transfer",
    ),
    ParameterSpec(
        name="blob_host",
        flags=["--blob-host"],
        default="127.0.0.1",
        help="Host to bind blob server",
    ),
    ParameterSpec(
        name="blob_port",
        flags=["--blob-port"],
        type=int,
        default=0,
        help="Port for blob server (0 = random)",
    ),
    ParameterSpec(
        name="max_tool_rounds_continuation",
        flags=["--max_tool_rounds_continuation"],
        env_var="LAMA_OLE_MAX_TOOL_ROUNDS_CONTINUATION",
        default="ask",
        choices=["ask", "fallback"],
        help="Behavior when max_tool_rounds is reached: 'ask' (interactive menu) or 'fallback' (silent default)",
    ),
    ParameterSpec(
        name="system_prompt",
        flags=["--system_prompt"],
        env_var="LAMA_OLE_SYSTEM_PROMPT",
        default=None,
        help="The system prompt",
    ),
    ParameterSpec(
        name="system_prompt_file",
        flags=["--system_prompt_file"],
        env_var="LAMA_OLE_SYSTEM_PROMPT_FILE",
        default=None,
        help="The system prompt read from a file",
    ),
    ParameterSpec(
        name="no_safety_system_prompt",
        flags=["--no_safety_system_prompt"],
        action="store_true",
        help="Enables potential takeover when tools are used, it is placed after the system prompt, if given",
    ),
    ParameterSpec(
        name="debug",
        flags=["--debug"],
        action="store_true",
        help="Initialize the environment and enter interactive mode",
    ),
    # --- Parameter inspection (--show-* selectors + --as-* output formats) ---
    ParameterSpec(
        name="show_config",
        flags=["--show-config"],
        action="store_true",
        is_inspection=True,
        help="Include values that originate from the config files (lama_ole.env)",
    ),
    ParameterSpec(
        name="show_nonconfig",
        flags=["--show-nonconfig"],
        action="store_true",
        is_inspection=True,
        help="Exclude values that originate from the config files (lama_ole.env)",
    ),
    ParameterSpec(
        name="show_environment",
        flags=["--show-environment"],
        action="store_true",
        is_inspection=True,
        help="Include values that originate from shell environment variables",
    ),
    ParameterSpec(
        name="show_noenvironment",
        flags=["--show-noenvironment"],
        action="store_true",
        is_inspection=True,
        help="Exclude values that originate from shell environment variables",
    ),
    ParameterSpec(
        name="show_parameters",
        flags=["--show-parameters"],
        action="store_true",
        is_inspection=True,
        help="Include values set explicitly on the command line",
    ),
    ParameterSpec(
        name="show_noparameters",
        flags=["--show-noparameters"],
        action="store_true",
        is_inspection=True,
        help="Exclude values set explicitly on the command line",
    ),
    ParameterSpec(
        name="show_defaults",
        flags=["--show-defaults"],
        action="store_true",
        is_inspection=True,
        help="Include values that come from the built-in defaults",
    ),
    ParameterSpec(
        name="show_nondefaults",
        flags=["--show-nondefaults"],
        action="store_true",
        is_inspection=True,
        help="Show only values that differ from the built-in defaults",
    ),
    ParameterSpec(
        name="as_parameters",
        flags=["--as-parameters"],
        action="store_true",
        is_inspection=True,
        help="Print the selected values as CLI parameters and exit",
    ),
    ParameterSpec(
        name="as_environment",
        flags=["--as-environment"],
        action="store_true",
        is_inspection=True,
        help="Print the selected values as shell export statements and exit",
    ),
    ParameterSpec(
        name="as_natural",
        flags=["--as-natural"],
        action="store_true",
        is_inspection=True,
        help="Print the selected values in their natural representation and exit",
    ),
]

# Add inspection parameters
INSPECTION_FLAGS = [
    "--show-config",
    "--show-nonconfig",
    "show-nonconfig",
    "--show-environment",
    "--show-noenvironment",
    "--show-parameters",
    "--show-noparameters",
    "--show-defaults",
    "--show-nondefaults",
    "--as-parameters",
    "--as-environment",
    "--as-natural",
]


def format_bash_c_quote(value: str) -> str:
    """Format string value using bash C-quoting ($'...') if it contains special chars/newlines."""
    if not isinstance(value, str):
        value = str(value)

    has_special = any(
        c in value for c in ("\n", "\r", "\t", "\x0b", "\x0c")
    ) or any(ord(c) < 32 or ord(c) == 127 for c in value)

    if has_special:
        escaped = (
            value.replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        return f"$'{escaped}'"

    # If it contains spaces or quotes, double quote it safely
    if re.search(r'[\s"$\\`]', value):
        escaped = value.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`')
        return f'"{escaped}"'

    return value


def _coerce_type(val: Any, type_fn: Any) -> Any:
    if val is None or type_fn is None:
        return val
    if type_fn is _parse_bool:
        return _parse_bool(val)
    if type_fn is int:
        try:
            return int(val)
        except (ValueError, TypeError):
            return val
    if type_fn is float:
        try:
            return float(val)
        except (ValueError, TypeError):
            return val
    if callable(type_fn):
        try:
            return type_fn(val)
        except Exception:
            return val
    return val


def parse_cli_explicit_params(argv: List[str]) -> Dict[str, Any]:
    """Parse argv to find parameters explicitly supplied on command line."""
    explicit = {}
    i = 0
    n = len(argv)

    flag_to_spec = {}
    for spec in PARAMETERS:
        for flag in spec.flags:
            flag_to_spec[flag] = spec
        if spec.action == argparse.BooleanOptionalAction:
            for flag in spec.flags:
                if flag.startswith("--"):
                    flag_to_spec["--no-" + flag[2:]] = spec

    while i < n:
        arg = argv[i]
        if arg in INSPECTION_FLAGS:
            i += 1
            continue

        if arg in flag_to_spec:
            spec = flag_to_spec[arg]
            if spec.action in ("store_true", "store_false"):
                explicit[spec.name] = (spec.action == "store_true")
                i += 1
            elif spec.action == argparse.BooleanOptionalAction:
                explicit[spec.name] = not arg.startswith("--no-")
                i += 1
            elif spec.action == "count":
                explicit[spec.name] = explicit.get(spec.name, 0) + 1
                i += 1
            elif spec.action == "append":
                if i + 1 < n and not argv[i + 1].startswith("-"):
                    val = argv[i + 1]
                    if spec.name not in explicit:
                        explicit[spec.name] = []
                    explicit[spec.name].append(val)
                    i += 2
                else:
                    i += 1
            elif spec.nargs == 2:
                if i + 2 < n:
                    explicit[spec.name] = [argv[i + 1], argv[i + 2]]
                    i += 3
                else:
                    i += 1
            else:
                if i + 1 < n and not argv[i + 1].startswith("-"):
                    explicit[spec.name] = _coerce_type(argv[i + 1], spec.type)
                    i += 2
                else:
                    i += 1
        elif "=" in arg and arg.startswith("-"):
            key, _, val = arg.partition("=")
            if key in flag_to_spec:
                spec = flag_to_spec[key]
                explicit[spec.name] = _coerce_type(val, spec.type)
            i += 1
        else:
            i += 1

    return explicit


def process_inspection_flags(
    argv: List[str],
    config_dict: Dict[str, str],
    initial_env: Dict[str, str],
) -> bool:
    """Check if any inspection actions (--as-...) are in argv. If so, execute and return True."""
    has_as_flag = any(a in ("--as-parameters", "--as-environment", "--as-natural") for a in argv)
    if not has_as_flag:
        return False

    cli_explicit = parse_cli_explicit_params(argv)

    active_selectors: Set[str] = set()

    for token in argv:
        if token == "--show-config":
            active_selectors.add("config")
        elif token in ("--show-nonconfig", "show-nonconfig"):
            active_selectors.discard("config")
        elif token == "--show-environment":
            active_selectors.add("environment")
        elif token == "--show-noenvironment":
            active_selectors.discard("environment")
        elif token == "--show-parameters":
            active_selectors.add("parameters")
        elif token == "--show-noparameters":
            active_selectors.discard("parameters")
        elif token == "--show-defaults":
            active_selectors.add("defaults")
        elif token in ("--show-nondefaults", "--show-nondefault"):
            active_selectors.add("nondefaults")
        elif token in ("--as-parameters", "--as-environment", "--as-natural"):
            mode = token[5:]  # 'parameters', 'environment', or 'natural'
            _output_inspection_group(
                mode=mode,
                selectors=set(active_selectors),
                config_dict=config_dict,
                initial_env=initial_env,
                cli_explicit=cli_explicit,
            )
            active_selectors.clear()

    return True


def _output_inspection_group(
    mode: str,
    selectors: Set[str],
    config_dict: Dict[str, str],
    initial_env: Dict[str, str],
    cli_explicit: Dict[str, Any],
):
    """Output values matching selectors in specified mode."""
    # Determine which tiers are included
    show_config = "config" in selectors
    show_env = "environment" in selectors
    show_params = "parameters" in selectors
    show_defaults = "defaults" in selectors
    show_nondefaults = "nondefaults" in selectors

    # If no selectors given, default to matching all set sources
    if not selectors:
        show_config = show_env = show_params = show_defaults = True

    for spec in PARAMETERS:
        if spec.name == "version" or spec.is_inspection:
            continue

        # Evaluate tiers
        val_param = cli_explicit.get(spec.name)
        has_param = spec.name in cli_explicit

        val_env = None
        has_env = False
        if spec.env_var and spec.env_var in initial_env:
            has_env = True
            val_env = initial_env[spec.env_var]

        val_config = None
        has_config = False
        if spec.env_var and spec.env_var in config_dict:
            has_config = True
            val_config = config_dict[spec.env_var]

        val_default = spec.default
        has_default = val_default is not None or spec.action in ("store_true", argparse.BooleanOptionalAction)

        # Determine winning value and tier
        winning_tier = None
        winning_val = None

        if has_param:
            winning_tier = "parameters"
            winning_val = val_param
        elif has_env:
            winning_tier = "environment"
            winning_val = val_env
        elif has_config:
            winning_tier = "config"
            winning_val = val_config
        elif show_defaults and has_default:
            winning_tier = "defaults"
            winning_val = val_default

        if winning_tier is None:
            continue

        # Check nondefaults filter
        if show_nondefaults and not show_defaults:
            # Must differ from spec.default or be non-default source
            if winning_tier == "defaults":
                continue

        # Check source filter match
        if winning_tier == "parameters" and not (show_params or show_nondefaults):
            continue
        if winning_tier == "environment" and not (show_env or show_nondefaults):
            continue
        if winning_tier == "config" and not (show_config or show_nondefaults):
            continue
        if winning_tier == "defaults" and not show_defaults:
            continue

        # Build overwritten comments
        overridden = []
        if winning_tier == "parameters":
            if has_env:
                overridden.append(f'environment: "{val_env}"')
            if has_config:
                overridden.append(f'config: "{val_config}"')
        elif winning_tier == "environment":
            if has_config:
                overridden.append(f'config: "{val_config}"')

        comment = ""
        if overridden:
            comment = f" # (overrides {', '.join(overridden)})"

        # Format output
        _print_formatted_param(spec, mode, winning_val, winning_tier, comment)


def _print_formatted_param(spec: ParameterSpec, mode: str, val: Any, winning_tier: str, comment: str):
    primary_flag = spec.flags[-1] if len(spec.flags) > 1 else spec.flags[0]

    if mode == "parameters":
        if spec.action in ("store_true", "store_false"):
            if val:
                print(f"{primary_flag}{comment}")
        elif spec.action == argparse.BooleanOptionalAction:
            if val is True:
                print(f"{primary_flag}{comment}")
            elif val is False:
                flag = primary_flag if primary_flag.startswith("--") else spec.flags[0]
                neg_flag = "--no-" + flag[2:] if flag.startswith("--") else flag
                print(f"{neg_flag}{comment}")
        elif isinstance(val, list):
            for item in val:
                qitem = format_bash_c_quote(str(item))
                print(f"{primary_flag} {qitem}{comment}")
        elif val is not None:
            qval = format_bash_c_quote(str(val))
            print(f"{primary_flag} {qval}{comment}")

    elif mode == "environment":
        if spec.env_var:
            if isinstance(val, list):
                sval = " ".join(str(x) for x in val)
            elif isinstance(val, bool):
                sval = "true" if val else "false"
            else:
                sval = str(val) if val is not None else ""
            qval = format_bash_c_quote(sval)
            print(f'export {spec.env_var}={qval}{comment}')

    elif mode == "natural":
        if winning_tier == "parameters":
            _print_formatted_param(spec, "parameters", val, winning_tier, comment)
        else:
            if spec.env_var:
                if isinstance(val, list):
                    sval = " ".join(str(x) for x in val)
                elif isinstance(val, bool):
                    sval = "true" if val else "false"
                else:
                    sval = str(val) if val is not None else ""
                qval = format_bash_c_quote(sval)
                print(f'{spec.env_var}={qval}{comment}')
            else:
                _print_formatted_param(spec, "parameters", val, winning_tier, comment)
