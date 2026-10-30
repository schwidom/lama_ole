# 003: Plan — using the Beam API properly (openai_compat improvements)

Date: 2026-10-30
Companion to `001_report.md` and `002_proposals.md`.

## 0. Decision: improve `openai_compat`, do NOT add a `beam` backend

Keep a single `openai_compat` backend and extend it. Do not create a `beam`
backend. Beam is served only through OpenAI-compatible endpoints (vLLM, SGLang,
HF Inference Providers); the chat template is applied server-side, so the client
never renders Jinja. The defects are classification/replay defects, not protocol
defects. `backends/base.py` already exposes the `extract_text_tool_calls` hook,
so Beam-specific XML tool-call parsing can live in openai_compat without a new
backend class.

## 1. New findings from chat_template.jinja

1. Channels: Beam emits `analysis` (reasoning) and `final` (answer). Server
   parser splits into `reasoning_content` and `content`. Backend already maps
   both; only correct classification matters (done in current code).
2. `reasoning_effort` is a template kwarg, not only an OpenAI param. Template
   accepts int (8/32/64/128/256/512) or labels
   `minimal`/`low`/`medium`/`high`/`xhigh`/`max`. Report omits `minimal`;
   template supports it. Some servers only honour it via `chat_template_kwargs`.
   Support both delivery paths.
3. `allow_missing_thinking` (default true). When false, generation prompt
   raises if any assistant turn has empty/missing reasoning. Template error
   says: "Send it back in 'reasoning_content'". This makes prior-reasoning
   replay MANDATORY for multi-turn Beam agent runs with
   `allow_missing_thinking=false` (recommended serving setting). Upgrades
   Proposal D from optional to required for Beam agentic use.
4. Tool messages need a resolvable tool name. Template resolves recipient via
   `message.name` or registry keyed by `tool_call_id`. Our `_sanitize_messages`
   pairs ids (registry path works), but also emit `name` when available.
5. `function.arguments` must be a dict. Template raises otherwise. Backend
   already stringifies dict args to JSON on send; server parses JSON strings
   before applying template. Defensive XML parser must produce dict arguments.
6. System/developer roles are equivalent; consecutive leading ones join into
   one `# Instructions` block. Backend merges `system` but not `developer`.
7. `preserve_thinking` is client-side (replay reasoning across turns). Confirmed:
   implement via structured `reasoning_content`, never text tags.

## 2. Status of the code (already done)

- A.1 reasoning from reasoning/reasoning_content/reasoning_text/thinking
- A.2 thinking yielded before content
- A.3 inline think/thought/begin_of_thought parsing in content
- A.4 supports_thinking = True
- A.5 reasoning_effort and preserve_thinking in _OPTION_MAP
- B reasoning_format="parsed" / include_reasoning negotiation when tools
- base.py already has extract_text_tool_calls hook

Still missing:

- C.2 Beam XML tool-call defensive parser (hook not overridden)
- D thinking replay (preserve_thinking)
- chat_template_kwargs support
- tool-message name emission
- developer-message merging in _sanitize_messages
- tests for the above

## 3. Required changes

### 3.1 Backend (backends/openai_compat_backend.py)

3.1.1 chat_template_kwargs forwarding:
- Add "chat_template_kwargs" to _OPTION_MAP (verbatim).
- When reasoning_effort present in options and model name contains "beam"
  (case-insensitive), also populate chat_template_kwargs.reasoning_effort with
  the same value, merging into any user-supplied chat_template_kwargs. Ensures
  effort reaches apply_chat_template on servers honouring only the kwarg form,
  while top-level field keeps OpenAI-o1-style servers working. Gate on model
  name to avoid sending unsupported fields to strict non-Beam servers.

3.1.2 Thinking replay (preserve_thinking):
- In _sanitize_messages, when an assistant message carries a thinking key (or
  reasoning_content/reasoning), emit it as reasoning_content on the wire
  message (only if not already present). Never re-inject as text tags.
- Requires engine to stop stripping thinking unconditionally (see 3.2). Backend
  becomes single place deciding whether to send it: send when preserve_thinking
  requested (or always for thinking-capable families when option on); otherwise
  drop it (current behaviour) so allow_missing_thinking=true servers still work.

3.1.3 Tool-message name:
- In _sanitize_messages, for role == "tool", set msg["name"] =
  m.get("tool_name") or m.get("name") when present.

3.1.4 Developer-message merging:
- Treat role == "developer" like system for the leading run: merge consecutive
  leading system/developer messages into the single leading system message
  (blank line apart), matching template join rule. Keep non-leading developer
  messages passed through.

3.1.5 Beam XML tool-call parser (override extract_text_tool_calls):
- Implement extract_text_tool_calls(self, text) on OpenAICompatBackend that
  first runs Qwen3 call: parser (fallback), then a Beam-XML pass.
- Beam XML grammar (from chat_template.jinja): calls appear as
    `