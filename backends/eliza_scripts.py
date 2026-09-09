"""Built-in named scripts for the Eliza backend.

Each script is a list of ``{"content": ..., "tool_calls": ...}`` entries played
one per ``chat()`` call, exactly as a script passed explicitly to
``ElizaBackend(script=...)`` / ``create_backend("eliza", script=...)``.

A named script is selected by model name: with ``--backend eliza`` a ``-m``
value that matches a key here loads that script (see
``backends/eliza_backend.py``). The keys are also listed by
``ElizaBackend.list_models()`` so ``-l`` shows them as usable "models".
"""

from __future__ import annotations

from typing import Dict, List

ELIZA_SCRIPTS: Dict[str, List[Dict]] = {
    # Reads a file literally named ``test.txt`` from the current working
    # directory via the ``read_file`` tool; requires the tool module
    # ``tools.example_tools`` to be loaded with ``--tool``.
    "read_test": [
        {
            "content": "Let me read the file test.txt for you.",
            "tool_calls": [
                {"function": {"name": "read_file", "arguments": {"path": "test.txt"}}}
            ],
        },
        {
            "content": "I read test.txt; its contents were shown in the tool result.",
        },
    ],
    # A fixed ten-sentence dialog. Each sentence is one script entry, i.e. one
    # assistant turn, so the REPL (or ten consecutive ``chat()`` calls) plays
    # the whole conversation in order.
    "chitchat": [
        {"content": "Hello! Welcome to my little corner of the internet."},
        {"content": "I have been re-reading a lot of poetry lately."},
        {"content": "Do you write your own haiku too?"},
        {"content": "A haiku should taste like a morning breath, they say."},
        {"content": "Shall we talk about what brings you here today?"},
        {"content": "Hmm, silence is also an answer, is it not?"},
        {"content": "When in doubt, I go for a long walk."},
        {"content": "Flowers bloom even in the cracks of the pavement."},
        {"content": "I hope today treats you kindly."},
        {"content": "Come back anytime; the teapot is always warm."},
    ],
}