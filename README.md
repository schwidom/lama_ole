***

# 🚀 lama_ole

A powerful, feature-rich CLI tool designed to interact with **Ollama** instances. `lama_ole` provides a streamlined way to communicate with local models while specifically handling "thinking" processes and providing flexible output options.

## ✨ Features

-   **Streaming Support:** Real-time output as the model generates text.
-   **Thinking Process Handling:** 
    -   Display the model's internal thought process in the console (`-t`).
    -   Save thoughts to a dedicated file independently of the console output (`--thoughtfile`).
-   **Output Redirection:** Save the final generated content directly to a file (`-o`).
-   **Flexible Input:** Support for both direct string input via `-i` and standard input (stdin) via `--stdin`.
-   **Full Ollama Integration:** Pass through parameters like `temperature`, `num_ctx`, `num_gpu`, and `keep_alive`.

## 📋 Prerequisites

Before running the tool, ensure you have:
1.  **Ollama** installed and running on your machine ([ollama.com](https://ollama.com)).
2.  **Python 3.x** installed.
3.  The `ollama` Python library installed.

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
If you are using models that support a thinking process, use the `-t` flag to see the thought process in your terminal:
```bash
python3 lama_ole.py -m gemma2:2b -t -i "Solve this complex math problem step by step."
```

### Saving Outputs to Files
You can save the model's thoughts and the final output to separate files automatically:
```bash
python3 lama_ole.py -m gemma2:2b -i "Write a 500-word story about a robot" --thoughtfile thoughts.txt -o story.txt
```

### Using Standard Input (Piping)
Perfect for use in shell scripts or piping output from other commands:
```bash
echo "Tell me a joke about programming." | python3 lama_ole.py --stdin -m lfm2.5:8b
```

## ⚙️ Configuration Options

| Flag | Description | Example |
| :--- | :--- | :--- |
| `-h, --help` | Show this help message and exit | |
| `--host` | The host of the ollama instance | `localhost:11434` |
| `-m, --model` | The model name to use | `gemma4:12b`, `qwen3.5:4b`, etc. |
| `-i, --input` | The input string to send to the model | `"Hello world"` |
| `--stdin` | Read input from standard input instead of `-i` | |
| `-t, --thinking` | Output the model's thought process to console | |
| `--thoughtfile` | Path to save thoughts (independent of `-t`) | `thoughts.txt` |
| `-o, --outfile` | Path where main output should be saved | `output.txt` |
| `--temperature` | Set sampling temperature (0.0 - 1.0) | `0.7` |
| `--num_ctx` | Set the context window size | `8192` |
| `--num_gpu` | Set the number of GPU cores to use | `4` |
| `--keep_alive` | Keep model in memory (e.g., '5m', '1h') | `30m` |

## 🛠 Troubleshooting

-   **Connection Error:** Ensure Ollama is running and the `--host` matches your local setup (default is `http://localhost:11434`).
-   **File Errors:** The script will exit if you attempt to create a file that already exists to prevent overwriting data.
-   **Missing Library:** If `ollama` module is not found, run `pip install ollama`.

## 📄 License
This project is open-source and available under the

[Apache License Version 2.0, January 2004](http://www.apache.org/licenses/).
