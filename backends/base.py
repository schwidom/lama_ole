from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional


@dataclass
class ChatChunk:
    """One streamed chunk from a backend, normalized to a common shape."""
    content: Optional[str] = None
    thinking: Optional[str] = None
    tool_calls: Optional[List[Dict]] = None
    done: bool = False

    prompt_eval_count: Optional[int] = None
    eval_count: Optional[int] = None
    eval_duration_ns: Optional[int] = None
    prompt_eval_duration_ns: Optional[int] = None


@dataclass
class ModelInfo:
    """Normalized model metadata."""
    name: str
    size: Optional[int] = None
    context_length: Optional[int] = None
    parameter_size: Optional[str] = None
    quantization: Optional[str] = None
    backend_specific: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RunningModel:
    """Normalized running model info."""
    name: str
    context_length: Optional[int] = None
    backend_specific: Dict[str, Any] = field(default_factory=dict)


class LlmBackend(ABC):
    """Abstract base class for all LLM backends."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    def supports_keep_alive(self) -> bool:
        return False

    @abstractmethod
    def chat(
        self,
        model: str,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        stream: bool = True,
        options: Optional[Dict] = None,
        keep_alive: Optional[Any] = None,
    ) -> Iterator[ChatChunk]:
        ...

    @abstractmethod
    def list_models(self) -> List[ModelInfo]:
        ...

    @abstractmethod
    def list_running(self) -> List[RunningModel]:
        ...

    @abstractmethod
    def show_model(self, model: str) -> Optional[ModelInfo]:
        ...

    @abstractmethod
    def stop_model(self, model: str) -> bool:
        ...

    @abstractmethod
    def convert_tools(self, tools: List[Any]) -> Optional[List[Dict]]:
        ...

    def transfer_model(self, model: str, source: Any, dest: Any) -> bool:
        raise NotImplementedError(
            f"Model transfer is not supported by the {self.name} backend."
        )

    def close(self) -> None:
        pass
