"""Shared Tool -> OpenAI function-calling dict conversion for all backends."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def convert_tools_to_openai(tools: List[Any]) -> Optional[List[Dict]]:
    """Convert internal Tool objects to the OpenAI function-calling format.

    Returns None when the list is empty so callers can pass a falsy value to
    the engine and the backend chat() as "no tools".
    """
    if not tools:
        return None
    result = []
    for t in tools:
        if isinstance(t, dict):
            result.append(t)
        else:
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": getattr(t, "name", ""),
                        "description": getattr(t, "description", ""),
                        "parameters": getattr(t, "parameters", {}),
                    },
                }
            )
    return result