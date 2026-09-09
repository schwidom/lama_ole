"""llama.cpp server backend adapter.

Talks to llama.cpp's ``/v1/chat/completions`` endpoint, which follows the
OpenAI streaming SSE protocol with identical tool-calling support.
Inherits :class:`OpenAICompatBackend` and only overrides the canonical name
and default host/port (``http://localhost:8080``).
"""

from __future__ import annotations

from typing import Any, Optional

from backends.openai_compat_backend import OpenAICompatBackend


class LlamaCppBackend(OpenAICompatBackend):
    """Adapter for llama.cpp's OpenAI-compatible ``/v1/chat/completions``."""

    _default_backend_name = "llamacpp"

    def __init__(
        self,
        host: Optional[str] = None,
        api_key: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        # llama.cpp never needs an API key; ignore if provided.
        super().__init__(host=host, api_key=None, **kwargs)