#!/usr/bin/python3

import argparse
import sys
import os
from ollama import Client

# Ensure the script's directory is in sys.path for sibling imports
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

# Ensure the current working directory is in sys.path for user tool modules
_cwd = os.getcwd()
if _cwd not in sys.path:
    sys.path.insert(0, _cwd)

from tool_base import (
    get_tool_modules_info,
    load_tools,
    set_ollama_host,
    set_vision_models,
    to_ollama_tools,
    run_with_tools,
)
from chat import ChatState, run_chat

def main():
    parser = argparse.ArgumentParser(
        description="A CLI tool to interact with an Ollama instance."
    )
    # Define arguments
    parser.add_argument(
        "-V", "--version",
        action="version",
        version="0.0.6"
    )
    # Define arguments
    parser.add_argument(
        "--host",
        type=str,
        default="http://localhost:11434",
        help="The host of the ollama instance (e.g., localhost:11434)"
    )
    parser.add_argument(
        "-m", "--model",
        type=str,
        help="The model name to use (e.g., gemma2:2b)"
    )
    parser.add_argument(
        "-i", "--input",
        type=str,
        help="The input string to send to the model"
    )
    parser.add_argument(
        "-f", "--inputfile",
        type=str,
        help="Path to a file to be used as input"
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="If set, read the input from standard input instead of --input or --inputfile"
    )
    parser.add_argument(
        "-t", "--thinking",
        action="store_true",
        help="If set, output the model's thought process to the console"
    )
    # parameter for thoughts
    parser.add_argument(
        "--thoughtfile",
        type=str,
        help="Path to a file where the model's thoughts should be saved (independently of -t)"
    )
    # Added requested parameter: -o or --outfile
    parser.add_argument(
        "-o", "--outfile",
        type=str,
        help="Path to a file where the main output of the model should be saved"
    )
    # Parameter: temperature
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Set the sampling temperature (e.g., 0.7). Default is 0.0"
    )

    # Parameter: num_ctx
    parser.add_argument(
        "--num_ctx",
        type=int,
        default=None,
        help="Set the context window (e.g., 4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576)"
    )

    # Parameter: num_gpu
    parser.add_argument(
        "--num_gpu",
        type=int,
        default=None,
        help="Set the amount of GPU cores"
    )

    # Parameter: keep_alive
    parser.add_argument(
        "--keep_alive",
        type=str,
        default=None,
        help="Keep model in memory (e.g., '5m', '1h' or a number of seconds)"
    )

    # Parameter: list
    parser.add_argument(
        "-l", "--list",
        action="store_true",
        help="List all available models and exit"
    )

    # Parameter: list
    parser.add_argument(
        "--ps",
        action="store_true",
        help="List all running models and exit"
    )

    # Parameter: verbose (repeatable for levels)
    parser.add_argument(
        "-v", "--verbose",
        action="count",
        default=0,
        help="Increase verbosity level (repeat: -v, -vv, -vvv)"
    )

    # Parameter: chat
    parser.add_argument(
        "--chat",
        action="store_true",
        help="Start an interactive chat REPL session"
    )

    # Parameter: safe
    parser.add_argument(
        "--safe",
        action="store_true",
        help="Enable user confirmation before dangerous tool operations"
    )

    # Parameter: tool (repeatable)
    parser.add_argument(
        "--tool",
        type=str,
        action="append",
        dest="tools",
        default=None,
        help="Python module name providing tool functions (can be repeated)"
    )

    # Parameter: max_tool_rounds
    parser.add_argument(
        "--max_tool_rounds",
        type=int,
        default=None,
        help="Maximum number of tool-calling rounds (default: no limit)"
    )

    # Parameter: vision_model (repeatable)
    parser.add_argument(
        "--vision_model",
        type=str,
        action="append",
        dest="vision_models",
        default=None,
        help="Vision model name available for media understanding tools (can be repeated)"
    )

    # Parameter: help-tools
    parser.add_argument(
        "--help-tools",
        action="store_true",
        help="Show documentation for loaded tool modules and exit"
    )

    # Parameter: max_tool_rounds_continuation
    parser.add_argument(
        "--max_tool_rounds_continuation",
        type=str,
        default="ask",
        choices=["ask", "fallback"],
        help="Behavior when max_tool_rounds is reached: 'ask' (interactive menu) or 'fallback' (silent default)"
    )

    args = parser.parse_args()

    host_url = args.host
    if not host_url.startswith(('http://', 'https://')) and ':' in host_url:
        host_url = f"http://{host_url}"
    client = Client(host=host_url)

    # Propagate host and vision models to tools
    set_ollama_host(host_url)
    if args.vision_models:
        set_vision_models(args.vision_models)

    if args.list:
        print( "available models:")
        response = client.list()
        for model in response.models:
            print(model)

    if args.ps:
        print( "running models:")
        response = client.ps()
        for model in response.models:
            print(model)


    if args.list or args.ps:
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
    ollama_tools = to_ollama_tools(loaded_tools) if loaded_tools else None

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
        print("Error: You must provide content via -i, --inputfile, or use --stdin", file=sys.stderr)
        sys.exit(1)

    # File handles
    thought_file_handle = None
    output_file_handle = None

    # Open the thought file if provided
    if args.thoughtfile:
        if os.path.exists(args.thoughtfile):
            print(f"Error: The file '{args.thoughtfile}' already exists.", file=sys.stderr)
            sys.exit(1)
        thought_file_handle = open(args.thoughtfile, "w", encoding="utf-8")

    # Open the output file if provided
    if args.outfile:
        if os.path.exists(args.outfile):
            print(f"Error: The file '{args.outfile}' already exists.", file=sys.stderr)
            sys.exit(1)
        output_file_handle = open(args.outfile, "w", encoding="utf-8")

    try:
        options = {
            "temperature": args.temperature,
        }

        if None != args.num_ctx:
            options["num_ctx"] = args.num_ctx

        if None != args.num_gpu:
            options["num_gpu"] = args.num_gpu

        if args.chat:
            state = ChatState(
                client=client,
                model=args.model,
                loaded_tools=loaded_tools,
                ollama_tools=ollama_tools,
                options=options,
                keep_alive=args.keep_alive,
                show_thinking=args.thinking,
                verbose=args.verbose,
                safe=args.safe,
                thought_file_handle=thought_file_handle,
                output_file_handle=output_file_handle,
                max_tool_rounds=args.max_tool_rounds,
                max_tool_rounds_continuation=args.max_tool_rounds_continuation,
            )
            if content.strip():
                state.messages.append({"role": "user", "content": content})
                run_with_tools(
                    client=client,
                    model=args.model,
                    messages=state.messages,
                    loaded_tools=loaded_tools,
                    ollama_tools=ollama_tools,
                    options=options,
                    keep_alive=args.keep_alive,
                    show_thinking=args.thinking,
                    verbose=args.verbose,
                    safe=args.safe,
                    thought_file_handle=thought_file_handle,
                    output_file_handle=output_file_handle,
                    max_tool_rounds=args.max_tool_rounds,
                    max_tool_rounds_continuation=args.max_tool_rounds_continuation,
                )
            run_chat(state)
        else:
            messages = [{"role": "user", "content": content}]
            run_with_tools(
                client=client,
                model=args.model,
                messages=messages,
                loaded_tools=loaded_tools,
                ollama_tools=ollama_tools,
                options=options,
                keep_alive=args.keep_alive,
                show_thinking=args.thinking,
                verbose=args.verbose,
                safe=args.safe,
                thought_file_handle=thought_file_handle,
                output_file_handle=output_file_handle,
                max_tool_rounds=args.max_tool_rounds,
                max_tool_rounds_continuation=args.max_tool_rounds_continuation,
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

if __name__ == "__main__":
    main()
