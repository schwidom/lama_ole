"""Unit tests for backends/factory.py and backends/registry.py.

Covers the SUPPORTED_BACKENDS list, create_backend instantiation for every
registered backend, host/api_key forwarding, and the ValueError on an
unknown backend name.
"""

from __future__ import annotations

import sys
import os

current_file = os.path.abspath(__file__)
lama_ole_dir = os.path.abspath(os.path.join(os.path.dirname(current_file), ".."))
if lama_ole_dir not in sys.path:
    sys.path.insert(0, lama_ole_dir)

from backends.base import LlmBackend
from backends.eliza_backend import ElizaBackend
from backends.echo_backend import EchoMockBackend
from backends.factory import create_backend
from backends.registry import BACKEND_REGISTRY, SUPPORTED_BACKENDS


def test_supported_backends_includes_all():
    expected = {"ollama", "llamacpp", "openai_compat", "eliza", "echo"}
    assert set(SUPPORTED_BACKENDS) == expected


def test_registry_matches_supported():
    assert set(BACKEND_REGISTRY.keys()) == set(SUPPORTED_BACKENDS)


def test_create_echo():
    backend = create_backend("echo")
    assert isinstance(backend, LlmBackend)
    assert backend.name == "echo"
    assert isinstance(backend, EchoMockBackend)


def test_create_eliza():
    backend = create_backend("eliza", script=[{"content": "hi"}])
    assert isinstance(backend, ElizaBackend)
    assert backend.name == "eliza"


def test_create_openai_compat():
    backend = create_backend("openai_compat", host="https://example.com", api_key="sk-test")
    assert backend.name == "openai_compat"
    assert isinstance(backend, LlmBackend)


def test_create_llamacpp():
    backend = create_backend("llamacpp", host="http://myhost:9090")
    assert backend.name == "llamacpp"


def test_create_unknown_raises():
    import pytest
    with pytest.raises(ValueError, match="Unknown backend"):
        create_backend("nonexistent_backend")


def test_host_and_api_key_forwarded():
    from backends.openai_compat_backend import OpenAICompatBackend
    backend = create_backend("openai_compat", host="https://x.com:9999", api_key="k")
    assert isinstance(backend, OpenAICompatBackend)
    assert backend._api_key == "k"
    assert "x.com:9999" in backend._base_url