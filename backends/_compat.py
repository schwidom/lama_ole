from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse, urlunparse

BACKEND_DEFAULT_PORTS = {
    "ollama": 11434,
    "llamacpp": 8080,
    "openai_compat": 443,
    "groq": 443,
    "eliza": 80,
    "echo": 80,
}

BACKEND_DEFAULT_SCHEMES = {
    "ollama": "http",
    "llamacpp": "http",
    "openai_compat": "https",
    "groq": "https",
    "eliza": "http",
    "echo": "http",
}


def normalize_host(host: Optional[str], backend_name: str) -> str:
    """Normalize a host string to a full URL using backend defaults.

    Rules:
    - None -> backend default (scheme + localhost/api.groq.com + port)
    - "myserver" -> http://myserver:<backend_port>
    - "myserver:9999" -> http://myserver:9999
    - "http://myserver" -> http://myserver:<backend_port>
    - "http://myserver:9999" -> http://myserver:9999
    """
    if host is None or not host.strip():
        if backend_name == "groq":
            return "https://api.groq.com/openai"
        scheme = BACKEND_DEFAULT_SCHEMES.get(backend_name, "http")
        port = BACKEND_DEFAULT_PORTS.get(backend_name, 80)
        return f"{scheme}://localhost:{port}"

    h = host.strip()

    if "://" not in h:
        h = f"http://{h}"

    parsed = urlparse(h)
    scheme = parsed.scheme or BACKEND_DEFAULT_SCHEMES.get(backend_name, "http")
    hostname = parsed.hostname or "localhost"
    port = parsed.port

    if port is None:
        port = BACKEND_DEFAULT_PORTS.get(backend_name, 80)

    return urlunparse((scheme, f"{hostname}:{port}", parsed.path or "",
                       parsed.params, parsed.query, parsed.fragment))
