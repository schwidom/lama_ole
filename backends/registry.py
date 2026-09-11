BACKEND_REGISTRY = {
    "ollama":        "backends.ollama_backend.OllamaBackend",
    "llamacpp":      "backends.llamacpp_backend.LlamaCppBackend",
    "openai_compat": "backends.openai_compat_backend.OpenAICompatBackend",
    "groq":          "backends.groq_backend.GroqBackend",
    "eliza":         "backends.eliza_backend.ElizaBackend",
    "echo":          "backends.echo_backend.EchoMockBackend",
}

DEFAULT_BACKEND = "ollama"
SUPPORTED_BACKENDS = list(BACKEND_REGISTRY.keys())
