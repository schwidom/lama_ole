"""Groq cloud LLM backend adapter.

Speaks the Groq API (OpenAI-compatible /v1/chat/completions endpoint with
Groq-specific constraints, options, reasoning formats, and parameter mappings).

Key differences from generic openai_compat:
- Base URL defaults to https://api.groq.com/openai (endpoint: /v1/chat/completions).
- Automatically sources API key from GROQ_API_KEY env var if not explicitly provided.
- Avoids sending unsupported parameters that trigger HTTP 400 errors (logprobs,
  logit_bias, messages[].name, frequency_penalty, presence_penalty).
- Clamps temperature <= 0 to 1e-5 (Groq rejects 0 or converts to 1e-8).
- Maps max_tokens / num_predict to max_completion_tokens.
- Handles Groq reasoning streams:
  - Injects reasoning_format="parsed" (or include_reasoning=True for GPT-OSS models)
    when tools are active, as Groq rejects raw reasoning with tool use with a 400.
  - Extracts reasoning from delta.reasoning or delta.reasoning_content and yields ChatChunk(thinking=...).
  - Handles inline <think>...</think> blocks in streaming delta.content if present.
- show_model() inspects Groq's context_window and max_completion_tokens from /v1/models/{model}.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Iterator, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from backends._compat import normalize_host
from backends._tools import convert_tools_to_openai
from backends.base import ChatChunk, LlmBackend, ModelInfo, RunningModel
from backends.openai_compat_backend import _read_sse_events

_HTTP_TIMEOUT = 120.0

# Groq option mapping: lama_ole option name -> Groq API request body name
_OPTION_MAP = {
    "temperature": "temperature",
    "top_p": "top_p",
    "num_predict": "max_completion_tokens",
    "max_tokens": "max_completion_tokens",
    "max_completion_tokens": "max_completion_tokens",
    "stop": "stop",
    "seed": "seed",
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


class GroqBackend(LlmBackend):
    """Adapter for the Groq Cloud API."""

    _default_backend_name = "groq"

    def __init__(
        self,
        host: Optional[str] = None,
        api_key: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        self._base_url = normalize_host(host, self._default_backend_name).rstrip("/")
        # If host was given as just https://api.groq.com without /openai, ensure /openai is present
        # but if full path is specified (/v1 etc), normalize_host handles it.
        if self._base_url == "https://api.groq.com":
            self._base_url = "https://api.groq.com/openai"
        self._api_key = api_key or os.environ.get("GROQ_API_KEY") or os.environ.get("LAMA_OLE_API_KEY")

    @property
    def name(self) -> str:
        return self._default_backend_name

    @property
    def supports_keep_alive(self) -> bool:
        return False

    @property
    def supports_thinking(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # HTTP plumbing
    # ------------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "lama_ole/groq-backend",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _get_json(self, path: str) -> Dict[str, Any]:
        req = Request(self._base_url + path, headers=self._headers())
        with urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # ------------------------------------------------------------------
    # Message / tool conversion & sanitization
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_messages(messages: List[Dict]) -> List[Dict]:
        """Convert internal messages to Groq wire format.

        - Strips lama_ole-specific keys and the 'name' field on user/assistant messages (rejected by Groq).
        - Merges multiple system messages into a single leading system message.
        - Pairs 'tool' results with the tool_call_id from preceding assistant tool calls.
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
        if not self._api_key:
            raise RuntimeError(
                "Groq API key not configured. Set GROQ_API_KEY environment variable "
                "or pass --api-key <key>."
            )

        payload: Dict[str, Any] = {
            "model": model,
            "messages": self._sanitize_messages(messages),
            "stream": True,
        }

        # Apply mapped options
        for key, value in (options or {}).items():
            target = _OPTION_MAP.get(key)
            if target and value is not None:
                if target == "temperature":
                    # Groq converts 0 to 1e-8 or rejects <= 0
                    if float(value) <= 0.0:
                        value = 1e-5
                    else:
                        value = float(value)
                payload[target] = value

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
            # Groq rejects raw reasoning format when tool use is enabled (HTTP 400)
            if "gpt-oss" in model.lower():
                payload["include_reasoning"] = True
            else:
                payload["reasoning_format"] = "parsed"
        else:
            # Default to parsed reasoning format if supported, or include_reasoning
            if "gpt-oss" in model.lower():
                payload["include_reasoning"] = True
            else:
                payload["reasoning_format"] = "parsed"

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
                f"groq chat failed ({e.code}): {body}"
            ) from None
        except URLError as e:
            raise RuntimeError(f"groq chat failed: {e.reason}") from None

        tool_acc: Dict[int, Dict[str, Any]] = {}
        done = False
        in_think_tag = False

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
                # Groq returns reasoning in delta.reasoning or delta.reasoning_content
                reasoning = delta.get("reasoning") or delta.get("reasoning_content")

                if reasoning:
                    yield ChatChunk(thinking=reasoning, done=False)

                if content:
                    # If the stream contains raw <think> tags, parse them
                    if "<think>" in content:
                        in_think_tag = True
                        before, _, after = content.partition("<think>")
                        if before:
                            yield ChatChunk(content=before, done=False)
                        content = after

                    if in_think_tag:
                        if "</think>" in content:
                            think_part, _, normal_part = content.partition("</think>")
                            in_think_tag = False
                            if think_part:
                                yield ChatChunk(thinking=think_part, done=False)
                            if normal_part:
                                yield ChatChunk(content=normal_part, done=False)
                        else:
                            yield ChatChunk(thinking=content, done=False)
                    else:
                        yield ChatChunk(content=content, done=False)

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
                        yield ChatChunk(
                            tool_calls=calls,
                            done=True,
                            prompt_eval_count=pc,
                            eval_count=ec,
                        )
                    else:
                        yield ChatChunk(
                            content=None,
                            done=True,
                            prompt_eval_count=pc,
                            eval_count=ec,
                        )

        if not done:
            yield ChatChunk(done=True)

    def convert_tools(self, tools: List[Any]) -> Optional[List[Dict]]:
        return convert_tools_to_openai(tools)

    def list_models(self) -> List[ModelInfo]:
        resp = self._get_json("/v1/models")
        models: List[ModelInfo] = []
        for entry in (resp.get("data") or []):
            mid = entry.get("id", "")
            if mid:
                ctx = entry.get("context_window")
                models.append(ModelInfo(name=mid, context_length=ctx))
        return models

    def list_running(self) -> List[RunningModel]:
        return []

    def show_model(self, model: str) -> Optional[ModelInfo]:
        try:
            resp = self._get_json(f"/v1/models/{quote(model, safe='')}")
            if resp.get("id"):
                ctx = resp.get("context_window")
                return ModelInfo(name=resp.get("id"), context_length=ctx)
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
