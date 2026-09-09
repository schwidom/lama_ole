from __future__ import annotations

import re
from typing import Any, Dict, Iterator, List, Optional

from backends._compat import normalize_host
from backends.base import ChatChunk, LlmBackend, ModelInfo, RunningModel


class OllamaBackend(LlmBackend):
    """Ollama backend adapter — wraps ollama.Client behind the LlmBackend ABC.

    The interface tools are normalised to the OpenAI function-calling format
    (List[Dict]); conversion to Ollama's native ``OllamaTool`` objects happens
    solely inside ``chat`` — Ollama never sees raw JSON-schema dicts.
    """

    def __init__(self, host: Optional[str] = None, api_key: Optional[str] = None, **kwargs: Any) -> None:
        from ollama import Client  # lazy import

        self._client = Client(host=normalize_host(host, "ollama"))

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def supports_keep_alive(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # chat
    # ------------------------------------------------------------------

    def chat(
        self,
        model: str,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        stream: bool = True,
        options: Optional[Dict] = None,
        keep_alive: Optional[Any] = None,
    ) -> Iterator[ChatChunk]:
        native_tools = self._dicts_to_ollama_tools(tools) if tools else None
        filtered = [{k: v for k, v in m.items() if k != "thinking"} for m in messages]

        kwargs: Dict[str, Any] = dict(model=model, messages=filtered, stream=stream)
        if native_tools is not None:
            kwargs["tools"] = native_tools
        if options is not None:
            kwargs["options"] = options
        if keep_alive is not None:
            kwargs["keep_alive"] = keep_alive

        response = self._client.chat(**kwargs)

        try:
            for chunk in response:
                msg = chunk.message
                yield ChatChunk(
                    content=msg.content,
                    thinking=getattr(msg, "thinking", None),
                    tool_calls=self._normalize_tool_calls(msg.tool_calls) if msg.tool_calls else None,
                    prompt_eval_count=getattr(chunk, "prompt_eval_count", None),
                    eval_count=getattr(chunk, "eval_count", None),
                    eval_duration_ns=getattr(chunk, "eval_duration", None),
                    prompt_eval_duration_ns=getattr(chunk, "prompt_eval_duration", None),
                )
        finally:
            if hasattr(response, "close"):
                response.close()

        yield ChatChunk(done=True)

    # ------------------------------------------------------------------
    # Tool conversion
    # ------------------------------------------------------------------

    def convert_tools(self, tools: List[Any]) -> Optional[List[Dict]]:
        """Convert internal Tool objects to the OpenAI function-calling format."""
        result = []
        for t in tools:
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
            )
        return result if result else None

    def _dicts_to_ollama_tools(self, tools: List[Dict]) -> List[Any]:
        """Convert OpenAI-format tool dicts to Ollama's native OllamaTool objects.

        The engine always passes tools in the OpenAI function-calling shape:
            {"type": "function",
             "function": {"name": ..., "description": ..., "parameters": {...}}}
        Ollama's client wants its own typed structure, so we translate here --
        Ollama never does the conversion itself.
        """
        from ollama import Tool as OllamaTool  # lazy import

        result = []
        for tool in tools:
            fn = tool.get("function", {})
            params = fn.get("parameters", {})
            properties: Dict[str, Any] = {}
            required = params.get("required", []) or []

            for pname, pinfo in (params.get("properties", {}) or {}).items():
                prop = OllamaTool.Function.Parameters.Property(
                    type=pinfo.get("type", "string"),
                    description=pinfo.get("description", ""),
                )
                if "enum" in pinfo:
                    prop.enum = pinfo["enum"]
                properties[pname] = prop

            ot = OllamaTool(
                type="function",
                function=OllamaTool.Function(
                    name=fn.get("name", ""),
                    description=fn.get("description", ""),
                    parameters=OllamaTool.Function.Parameters(
                        type="object",
                        properties=properties,
                        required=required if required else None,
                    ),
                ),
            )
            result.append(ot)
        return result

    def _normalize_tool_calls(self, tool_calls: Any) -> List[Dict]:
        return [
            {
                "function": {
                    "name": tc.function.name,
                    "arguments": dict(tc.function.arguments),
                }
            }
            for tc in tool_calls
        ]

    # ------------------------------------------------------------------
    # Model management
    # ------------------------------------------------------------------

    def list_models(self) -> List[ModelInfo]:
        resp = self._client.list()
        return [
            ModelInfo(name=m.name, size=getattr(m, "size", None))
            for m in resp.models
        ]

    def list_running(self) -> List[RunningModel]:
        resp = self._client.ps()
        return [
            RunningModel(name=m.model, context_length=getattr(m, "context_length", None))
            for m in resp.models
        ]

    def show_model(self, model: str) -> Optional[ModelInfo]:
        resp = self._client.show(model=model)
        num_ctx = None
        raw_params = getattr(resp, "parameters", "") or ""
        m = re.search(r"\bnum_ctx\s+(\d+)", raw_params)
        if m:
            num_ctx = int(m.group(1))
        return ModelInfo(
            name=model,
            context_length=num_ctx,
            backend_specific={
                "modelfile": getattr(resp, "modelfile", ""),
                "template": getattr(resp, "template", ""),
                "details": getattr(resp, "details", {}),
                "modelinfo": getattr(resp, "modelinfo", {}) or {},
            },
        )

    def stop_model(self, model: str) -> bool:
        self._client.generate(model=model, keep_alive=0)
        return True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        pass