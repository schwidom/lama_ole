from __future__ import annotations

import importlib
from typing import Any, Optional

from .base import LlmBackend
from .registry import BACKEND_REGISTRY, SUPPORTED_BACKENDS


def create_backend(
    name: str,
    host: Optional[str] = None,
    api_key: Optional[str] = None,
    **kwargs: Any,
) -> LlmBackend:
    """Create a backend by name. Raises ValueError if unknown.

    Backend libraries are imported lazily -- a missing library only fails
    when that specific backend is requested, not at application startup.
    """
    if name not in BACKEND_REGISTRY:
        raise ValueError(
            f"Unknown backend '{name}'. "
            f"Available: {', '.join(SUPPORTED_BACKENDS)}"
        )
    class_path = BACKEND_REGISTRY[name]
    module_path, class_name = class_path.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    return cls(host=host, api_key=api_key, **kwargs)
