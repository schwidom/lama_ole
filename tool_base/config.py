# Configuration for Ollama and Vision Models
import os

# Vision models configured via CLI --vision_model (populated at startup)
_VISION_MODELS: list[str] = []


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
