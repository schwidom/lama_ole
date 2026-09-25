# Configuration for Ollama and Vision Models
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# Vision models configured via CLI --vision_model (populated at startup)
_VISION_MODELS: list[str] = []


@dataclass
class RunConfig:
    """Static execution settings for a ``run_with_tools()`` turn.

    Holds every non-mutable execution parameter so the engine no longer needs
    a 27-parameter signature. Mutable runtime state (messages, loaded_tools,
    backend_tools, state_manager, metrics) stays out of this object.
    """

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

    # Mid-turn interaction hooks (park/resume the hotkey listener around
    # blocking stdin prompts; no-op when None).
    hotkey_pause: Optional[Callable[[], None]] = None
    hotkey_resume: Optional[Callable[[], None]] = None

    # Models already warned about missing thinking output, so the warning
    # fires at most once per model per config (REPL session).
    _warned_no_thinking_models: set = field(
        default_factory=set, repr=False, compare=False
    )


def set_vision_models(models: list[str]):
    global _VISION_MODELS
    _VISION_MODELS.clear()
    _VISION_MODELS.extend(models)


def get_vision_models() -> list[str]:
    return list(_VISION_MODELS)


# Fixed Ollama host used as fallback by media understanding tools. The user
# can override it via LAMA_OLE_VISION_HOST (see tools/media_understanding_tools.py).
def get_ollama_host() -> str:
    return "http://localhost:11434"
