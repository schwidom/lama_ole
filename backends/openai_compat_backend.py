"""OpenAI-compatible backend adapter.

Speaks the OpenAI ``/v1/chat/completions`` protocol (streaming SSE). Covers
OpenAI itself — where o1/o3 models surface reasoning through the
``reasoning_content`` delta, mapped to ``ChatChunk.thinking`` — as well as any
server exposing the same endpoint (vLLM, LM Studio, text-generation-webui,
...). Prompts are sent in the OpenAI message format and tools use the OpenAI
function-calling schema.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from backends._compat import normalize_host
from backends._tools import convert_tools_to_openai
from backends.base import ChatChunk, LlmBackend, ModelInfo, RunningModel

_HTTP_TIMEOUT = 120.0

# lama_ole option names (Ollama-style) -> OpenAI request body names.
_OPTION_MAP = {
    "temperature": "temperature",
    "top_p": "top_p",
    "top_k": "top_k",
    "num_predict": "max_tokens",
    "max_tokens": "max_tokens",
    "stop": "stop",
    "seed": "seed",
    "frequency_penalty": "frequency_penalty",
    "presence_penalty": "presence_penalty",
}

_EXTRA_MESSAGE_KEYS = (
    "thinking",
    "tool_name",
    "mode",
    "timestamp",
    "compacted",
    "summary_at",
    "diff",
    "file",
)


def _read_sse_events(resp) -> Iterator[str]:
    """Yield the ``data:`` payloads of an SSE response body.

    Handles payloads split across transport reads and multi-line ``data:``
    blocks; stops at the ``[DONE]`` sentinel.
    """
    buff = ""
    for raw in resp:
        if isinstance(raw, bytes):
            buff += raw.decode("utf-8", "replace")
        else:
            buff += raw
        while "\n" in buff:
            line, buff = buff.split("\n", 1)
            line = line.rstrip("\r")
            if not line.strip():
                continue
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                return
            yield payload
    rest = buff.strip()
    if rest.startswith("data:"):
        rest = rest[5:].strip()
    if rest and rest != "[DONE]":
        yield rest


class OpenAICompatBackend(LlmBackend):
    """Adapter for any OpenAI-compatible ``/v1/chat/completions`` server."""

    _default_backend_name = "openai_compat"

    def __init__(
        self,
        host: Optional[str] = None,
        api_key: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        self._base_url = normalize_host(host, self._default_backend_name).rstrip("/")
        self._api_key = api_key

    @property
    def name(self) -> str:
        return self._default_backend_name

    @property
    def supports_keep_alive(self) -> bool:
        return False

    # ------------------------------------------------------------------
    # HTTP plumbing
    # ------------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _get_json(self, path: str) -> Dict[str, Any]:
        req = Request(self._base_url + path, headers=self._headers())
        with urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # ------------------------------------------------------------------
    # Message / tool conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_messages(messages: List[Dict]) -> List[Dict]:
        """Convert internal messages to the OpenAI wire format.

        Drops lama_ole-specific keys, merges multiple system messages into a
        single leading system message (strict servers reject several), and
        pairs ``tool`` results with the ``tool_call_id`` of the assistant
        tool calls that produced them.
        """
        clean: List[Dict] = []
        pending_ids: List[str] = []
        system_parts: List[str] = []

        for m in messages:
            role = m.get("role")
            msg: Dict[str, Any] = {"role": role}

            if role == "assistant":
                msg["content"] = m.get("content")
                raw_tcs = m.get("tool_calls")
                if raw_tcs:
                    calls = []
                    for t in raw_tcs:
                        fn = (
                            t.get("function", {})
                            if isinstance(t, dict)
                            else getattr(t, "function", {})
                        )
                        fn_name = (
                            fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", None)
                        )
                        fn_args = (
                            fn.get("arguments")
                            if isinstance(fn, dict)
                            else getattr(fn, "arguments", {})
                        )
                        if isinstance(fn_args, dict):
                            fn_args = json.dumps(fn_args)
                        existing_id = (
                            t.get("id") if isinstance(t, dict) else getattr(t, "id", None)
                        )
                        cid = existing_id or f"call_{len(pending_ids)}"
                        pending_ids.append(cid)
                        calls.append(
                            {
                                "id": cid,
                                "type": "function",
                                "function": {"name": fn_name, "arguments": fn_args},
                            }
                        )
                    msg["tool_calls"] = calls
            elif role == "tool":
                if pending_ids:
                    msg["tool_call_id"] = m.get("tool_call_id") or pending_ids.pop(0)
                else:
                    msg["tool_call_id"] = m.get("tool_call_id", "call_unknown")
                msg["content"] = m.get("content", "")
            elif role == "system":
                system_parts.append(m.get("content", ""))
                continue
            elif role == "user":
                msg["content"] = m.get("content")
            clean.append(msg)

        if system_parts:
            clean.insert(0, {"role": "system", "content": "\n\n".join(system_parts)})
        return clean

    # ------------------------------------------------------------------
    # LlmBackend interface
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
        payload: Dict[str, Any] = {
            "model": model,
            "messages": self._sanitize_messages(messages),
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        mapped: Dict[str, Any] = {}
        for key, value in (options or {}).items():
            target = _OPTION_MAP.get(key)
            if target and value is not None:
                mapped[target] = value
        if mapped:
            payload.update(mapped)

        req = Request(
            self._base_url + "/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
        )
        try:
            resp = urlopen(req, timeout=_HTTP_TIMEOUT)
        except HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:1000]
            raise RuntimeError(
                f"openai_compat chat failed ({e.code}): {body}"
            ) from None
        except URLError as e:
            raise RuntimeError(f"openai_compat chat failed: {e.reason}") from None

        tool_acc: Dict[int, Dict[str, Any]] = {}
        done = False
        with resp:
            for event in _read_sse_events(resp):
                try:
                    data = json.loads(event)
                except json.JSONDecodeError:
                    continue
                choices = data.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get("delta") or choice.get("message") or {}

                content = delta.get("content")
                reasoning = delta.get("reasoning_content")
                if content:
                    yield ChatChunk(content=content, done=False)
                if reasoning:
                    yield ChatChunk(thinking=reasoning, done=False)

                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    acc = tool_acc.setdefault(idx, {"id": None, "name": "", "arguments": ""})
                    if tc.get("id"):
                        acc["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        acc["name"] += fn["name"]
                    if fn.get("arguments"):
                        acc["arguments"] += fn["arguments"]

                usage = data.get("usage") or {}
                pc = usage.get("prompt_tokens") if usage else None
                ec = usage.get("completion_tokens") if usage else None

                if choice.get("finish_reason"):
                    done = True
                    if tool_acc:
                        calls = [
                            {
                                "id": acc["id"],
                                "type": "function",
                                "function": {
                                    "name": acc["name"],
                                    "arguments": acc["arguments"],
                                },
                            }
                            for acc in (tool_acc[i] for i in sorted(tool_acc))
                        ]
                        yield ChatChunk(tool_calls=calls, done=True,
                                        prompt_eval_count=pc, eval_count=ec)
                    else:
                        yield ChatChunk(content=None, done=True,
                                        prompt_eval_count=pc, eval_count=ec)
        if not done:
            yield ChatChunk(done=True)

    def convert_tools(self, tools: List[Any]) -> Optional[List[Dict]]:
        return convert_tools_to_openai(tools)

    def list_models(self) -> List[ModelInfo]:
        resp = self._get_json("/v1/models")
        return [
            ModelInfo(name=entry.get("id", ""))
            for entry in (resp.get("data") or [])
            if entry.get("id")
        ]

    def list_running(self) -> List[RunningModel]:
        return []

    def show_model(self, model: str) -> Optional[ModelInfo]:
        try:
            resp = self._get_json(f"/v1/models/{quote(model, safe='')}")
            if resp.get("id"):
                return ModelInfo(name=model)
        except (HTTPError, URLError, RuntimeError):
            pass
        for info in self.list_models():
            if info.name == model:
                return info
        return None

    def stop_model(self, model: str) -> bool:
        return True

    def close(self) -> None:
        pass