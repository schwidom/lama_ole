# 003: run_with_tools() Signature & Logic

## 1. Refactored Function Signature

Under the strict `RunConfig` configuration constraint, `run_with_tools()` accepts only the active mutable runtime structures, the `RunConfig` configuration block, and operational metrics.

```python
from typing import Optional, List, Dict, Any
from .config import RunConfig
from .loop_states import StateManager
from .models import Tool

def run_with_tools(
    messages: List[Dict[str, Any]],
    loaded_tools: List[Tool],
    backend_tools: Optional[List[Dict[str, Any]]],
    config: RunConfig,
    state_manager: Optional[StateManager] = None,
    metrics: Optional[Dict[str, Any]] = None,
) -> str:
```

---

## 2. Refactored Internal Parameter Access

Within `run_with_tools()`, all references to config parameters are updated to access properties directly on the `config` parameter:

| Old Local Parameter | Refactored Parameter Access |
|---|---|
| `client` | `config.client` |
| `model` | `config.model` |
| `options` | `config.options` |
| `keep_alive` | `config.keep_alive` |
| `verbose` | `config.verbose` |
| `safe` | `config.safe` |
| `websearch` | `config.websearch` |
| `show_diff` | `config.show_diff` |
| `color` | `config.color` |
| `max_tool_rounds` | `config.max_tool_rounds` |
| `max_tool_rounds_continuation` | `config.max_tool_rounds_continuation` |
| `show_thinking` | `config.show_thinking` |
| `no_safety_system_prompt` | `config.no_safety_system_prompt` |
| `system_prompt` | `config.system_prompt` |
| `skill_text` | `config.skill_text` |
| `thought_file_handle` | `config.thought_file_handle` |
| `output_file_handle` | `config.output_file_handle` |
| `toolcall_file_handle` | `config.toolcall_file_handle` |
| `chatinput_file_handle` | `config.chatinput_file_handle` |
| `ndjson_log_file_handle` | `config.ndjson_log_file_handle` |

---

## 3. Resolving the `mode_state` Reference

In the previous architecture, `mode_state` was a reference to the `ChatState` object itself, used inside `run_with_tools()` to inspect dynamic changes (such as mid-turn operational mode changes or pausing the hotkey listener).

With the new design:
- The `config` object itself (`RunConfig`) is passed into `run_with_tools()`.
- Dynamic properties (like `config.mode`) are accessed on `config` directly, reflecting any mid-turn mode switches.
- Hotkey pause/resume actions can be implemented via a callback or by referencing an object on `config` or the `state_manager`.
- The `_warn_missing_thinking` function is updated to track `_warned_no_thinking_models` within `RunConfig` or as a property of `config`, keeping warnings deduplicated correctly.
