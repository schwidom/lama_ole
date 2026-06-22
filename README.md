***

# 🚀 lama_ole

A powerful, feature-rich CLI tool designed to interact with **Ollama** instances.
`lama_ole` provides streaming chat, tool calling, thinking-process handling, and
flexible output options.

## ✨ Features

- **Streaming Support:** Real-time output as the model generates text.
- **Thinking Process Handling:**
  - Display the model's internal thought process in the console (`-t`).
  - Save thoughts to a dedicated file independently of the console output (`--thoughtfile`).
- **Output Redirection:** Save the final generated content directly to a file (`-o`).
- **Flexible Input:** Direct string input via `-i`, file input via `-f`, or standard
  input via `--stdin`.
- **Chat Mode:** Interactive multi-turn REPL with slash commands (`--chat`).
- **Tool Calling:** Load Python modules as callable tools that the model can invoke
  automatically (`--tool`).
- **Model Listing:** List available or running models (`-l`, `--ps`).
- **Full Ollama Integration:** Pass through parameters like `temperature`, `num_ctx`,
  `num_gpu`, and `keep_alive`.

## 📋 Prerequisites

Before running the tool, ensure you have:
1. **Ollama** installed and running on your machine ([ollama.com](https://ollama.com)).
2. **Python 3.9+** installed.
3. The `ollama` Python library installed.

### Installation
```bash
pip install ollama
```

## 🚀 Getting Started

### Basic Usage
To send a simple prompt to a model:
```bash
python3 lama_ole.py -m gemma2:2b -i "Explain the theory of relativity in one paragraph."
```

### Using the "Thinking" Feature
If you are using models that support a thinking process, use the `-t` flag to see the
thought process in your terminal:
```bash
python3 lama_ole.py -m gemma2:2b -t -i "Solve this complex math problem step by step."
```

### Saving Outputs to Files
You can save the model's thoughts and the final output to separate files automatically:
```bash
python3 lama_ole.py -m gemma2:2b -i "Write a 500-word story about a robot" \
    --thoughtfile thoughts.txt -o story.txt
```

### Using Standard Input (Piping)
Perfect for use in shell scripts or piping output from other commands:
```bash
echo "Tell me a joke about programming." | python3 lama_ole.py --stdin -m lfm2.5:8b
```

### Chat Mode
Start an interactive multi-turn conversation:
```bash
python3 lama_ole.py --chat -m llama3:2b
```

Optionally provide an initial message:
```bash
python3 lama_ole.py --chat -m llama3:2b -i "You are a helpful assistant."
```

### Tool Calling (Single-Shot)
Load tool modules and let the model invoke them:
```bash
python3 lama_ole.py -m llama3:2b -i "What's the weather in Paris?" \
    --tool tools.example_tools
```

### Chat Mode with Tools
Combine chat and tools for an interactive agent session:
```bash
python3 lama_ole.py --chat -m llama3:2b --tool tools.example_tools
```

## 🛠 Writing Custom Tools

Tools are Python functions decorated with `@tool`. Create a `.py` file:

```python
from tool_base import tool


@tool(description="Multiply two numbers")
def multiply(a: int, b: int) -> int:
    return a * b


@tool(description="Get the population of a city")
def get_population(city: str) -> str:
    # Replace with real lookup
    return f"Population of {city}: 2.5 million"
```

Parameter names and types are automatically inferred from function annotations.
Alternatively, pass explicit `params`:

```python
@tool(
    description="Search the web",
    params={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
        },
        "required": ["query"],
    },
)
def web_search(query: str) -> str:
    ...
```

Load your tool module:
```bash
python3 lama_ole.py -m llama3:2b -i "search for python tutorials" --tool mytools
```

### Bundled Example Tools

The project ships with `tools.example_tools`:
- `get_weather(city)` — returns a fake weather report
- `calculate(expression)` — evaluates a math expression safely
- `read_file(path)` — reads a text file from disk

## 💬 Chat Commands

In chat mode (`--chat`), lines starting with `/` are interpreted as commands:

| Command | Description |
|---------|-------------|
| `/feed <path>` | Read a file and send its content as a message |
| `/clear` | Clear the conversation history |
| `/model <name>` | Switch to a different model |
| `/save <path>` | Save the conversation to a JSON file |
| `/load <path>` | Load a conversation from a JSON file |
| `/tools` | List loaded tools |
| `/context` | Show message count and total characters |
| `/help` | Show this help message |
| `/exit`, `/quit` | Exit the chat |

## ⚙️ Configuration Options

| Flag | Description | Example |
| :--- | :--- | :--- |
| `-h, --help` | Show this help message and exit | |
| `-V, --version` | Show program version and exit | |
| `--host HOST` | The host of the ollama instance | `localhost:11434` |
| `-m, --model` | The model name to use | `gemma4:12b`, `qwen3.5:4b` |
| `-i, --input` | The input string to send to the model | `"Hello world"` |
| `-f, --inputfile` | Path to a file to use as input | `prompt.txt` |
| `--stdin` | Read input from standard input | |
| `-t, --thinking` | Output the model's thought process to console | |
| `--thoughtfile` | Path to save thoughts (independent of `-t`) | `thoughts.txt` |
| `-o, --outfile` | Path where main output should be saved | `output.txt` |
| `--temperature` | Set sampling temperature (0.0 - 1.0) | `0.7` |
| `--num_ctx` | Set the context window size | `8192` |
| `--num_gpu` | Set the number of GPU cores to use | `4` |
| `--keep_alive` | Keep model in memory (e.g., `'5m'`, `'1h'`) | `30m` |
| `-l, --list` | List all available models | |
| `--ps` | List all running models | |
| `--chat` | Start an interactive chat REPL session | |
| `--tool MODULE` | Load tool module (can be repeated) | `tools.example_tools` |
| `--safe` | Enable user confirmation before dangerous tool operations | |
| `-v, --verbose` | Increase verbosity level (repeat: `-v`, `-vv`, `-vvv`) | `-vv` |

## 📢 Verbosity Levels

Repeat `-v` to increase output detail to stderr:

| Level | Flag | Output |
|-------|------|--------|
| 0 | (default) | Silent — no debug output |
| 1 | `-v` | Tool call names + truncated results (500 chars) |
| 2 | `-vv` | Full tool results + messages payload before each API call |
| 3 | `-vvv` | Raw streaming chunks as they arrive from the model |

## 🛠 Troubleshooting

- **Connection Error:** Ensure Ollama is running and the `--host` matches your local
  setup (default is `http://localhost:11434`).
- **File Errors:** The script will exit if you attempt to create a file that already
  exists to prevent overwriting data.
- **Missing Library:** If `ollama` module is not found, run `pip install ollama`.
- **Tool not found:** Use dotted module names, not file paths. For example,
  `--tool tools.example_tools` (not `--tool tools/example_tools.py`).
- **Chat errors:** Model errors in chat mode are caught gracefully and printed
  without exiting the REPL.

## 📄 License
This project is open-source and available under the

[Apache License Version 2.0, January 2004](http://www.apache.org/licenses/).
