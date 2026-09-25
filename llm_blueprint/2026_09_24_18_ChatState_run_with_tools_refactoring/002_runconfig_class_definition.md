# 002: RunConfig Class Definition

## 1. Class Schema & Location

The new `RunConfig` dataclass will be placed in a new module: `tool_base/config.py` (or integrated into `tool_base/models.py`). This guarantees that `chat.py` and other modules can import it without introducing any circular dependency back into `chat.py`.

```python
from dataclasses import dataclass, field
from typing import Optional, Any, List, Dict

@dataclass
class RunConfig:
    # Model & Client Parameters
    client: Any = None
    model: str = ""
    options: Dict[str, Any] = field(default_factory=dict)
    keep_alive: Any = None
    
    # Engine Execution Settings
    verbose: int = 0
    safe: bool = False
    websearch: bool = False
    show_diff: bool = True
    color: str = "auto"
    max_tool_rounds: Optional[int] = None
    max_tool_rounds_continuation: str = "ask"
    mode: str = "build"
    
    # Prompts & Skills
    show_thinking: bool = False
    no_safety_system_prompt: bool = False
    system_prompt: Optional[str] = None
    skill_text: Optional[str] = None
    
    # File Handles & Logging Targets
    thought_file_handle: Any = None
    output_file_handle: Any = None
    toolcall_file_handle: Any = None
    chatinput_file_handle: Any = None
    ndjson_log_file_handle: Any = None
```

---

## 2. Parameter Segregation

To ensure a clean separation between configuration and runtime state, only static execution settings are housed in `RunConfig`.

### Configured Parameters (Housed in `RunConfig`):
- Connection/client parameters (`client`, `model`, `options`, `keep_alive`).
- Behavioral flags and modes (`verbose`, `safe`, `websearch`, `show_diff`, `color`, `mode`).
- Prompt modifiers (`show_thinking`, `no_safety_system_prompt`, `system_prompt`, `skill_text`).
- Limits and strategies (`max_tool_rounds`, `max_tool_rounds_continuation`).
- Logging file handles (`thought_file_handle`, `output_file_handle`, `toolcall_file_handle`, `chatinput_file_handle`, `ndjson_log_file_handle`).

### Runtime State Parameters (Kept outside `RunConfig`):
- `messages` (List of dicts representing mutable conversation history).
- `loaded_tools` (List of active, executable `Tool` instances).
- `backend_tools` (List of dictionaries representing OpenAI-style tool definitions).
- `state_manager` (Instance of `StateManager` representing the active execution flow).
- `metrics` (Output dictionary populated with token usage statistics during execution).
