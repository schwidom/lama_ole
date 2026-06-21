#!/usr/bin/python3

import argparse
import sys
import os
from ollama import Client

def main():
    parser = argparse.ArgumentParser(
        description="A CLI tool to interact with an Ollama instance."
    )
    # Define arguments
    parser.add_argument(
        "-V", "--version",
        action="version",
        version="0.0.1"
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

    args = parser.parse_args()

    host_url = args.host
    if not host_url.startswith(('http://', 'https://')) and ':' in host_url:
        host_url = f"http://{host_url}"
    client = Client(host=host_url)

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

    if not args.model :
        print( "Error: model has to be set (parameter -m , --model)", file=sys.stderr)
        sys.exit(1)

    # Logic to determine the content of the message
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
        # Read everything from stdin
        content = sys.stdin.read()
    else:
        # If neither input, inputfile, nor stdin flag is set, show error
        print("Error: You must provide content via -i, --inputfile, or use --stdin", file=sys.stderr)
        sys.exit(1)

    if not content.strip():
        print("Error: Input content is empty.", file=sys.stderr)
        sys.exit(1)

    # Initialize the Ollama client with the specified host
    think_state = False
    
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
        # Use stream=True to ensure the connection is active and 
        # a Ctrl-C will break the loop immediately.

        options={
            "temperature": args.temperature,
        }

        if None != args.num_ctx:
            options["num_ctx"] = args.num_ctx

        if None != args.num_gpu:
            options["num_gpu"] = args.num_gpu

        stream = client.chat(
            model=args.model,
            messages=[{'role': 'user', 'content': content}],
            stream=True,
            options=options,
            keep_alive=args.keep_alive,
        )

        for chunk in stream:
            # Handle Thinking logic
            if hasattr(chunk.message, 'thinking') and chunk.message.thinking:
                thought_text = chunk.message.thinking
                
                # 1. Logic for Console (controlled by -t)
                if args.thinking:
                    if not think_state:
                        print("Thinking starts")
                        think_state = True
                    print(thought_text, end='', flush=True)
                
                # 2. Logic for File (independent of -t)
                if args.thoughtfile and thought_file_handle:
                    thought_file_handle.write(thought_text)
                    thought_file_handle.flush()

            # Handle Content logic
            if hasattr(chunk.message, 'content') and chunk.message.content:
                if think_state: 
                    print()
                    print("Thinking ends")
                    print()
                    think_state = False
                
                content_to_print = chunk.message.content
                print(content_to_print, end='', flush=True)

                # Logic for Output File (New functionality)
                if args.outfile and output_file_handle:
                    output_file_handle.write(content_to_print)
                    output_file_handle.flush()

        print() # New line at the end

    except KeyboardInterrupt:
        # Catching Ctrl-C specifically to exit gracefully
        sys.exit(0)
    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Ensure the file handles are closed properly
        if thought_file_handle:
            thought_file_handle.close()
        if output_file_handle:
            output_file_handle.close()

if __name__ == "__main__":
    main()
