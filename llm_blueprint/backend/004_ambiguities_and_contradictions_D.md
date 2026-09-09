# 004D: Contradictions Introduced by C-Decisions

---

## 1. B-Decision Deprecation of `set_ollama_host()` Overridden

### Contradiction

The B-decision said: "We should deprecate `set_ollama_host()` / `get_ollama_host()` completely."

The C-decision chose: "`LAMA_OLE_VISION_HOST` is kept; `LAMA_OLE_VISION_BACKEND` is removed."

This keeps `LAMA_OLE_VISION_HOST` and the existing `get_ollama_host()` mechanism for media tools. The B-decision's deprecation plan is effectively reversed.

### Resolution

Accept: `set_ollama_host()` / `get_ollama_host()` are NOT deprecated. They remain the mechanism for media tools to find the Ollama endpoint. Update the architecture doc to reflect this.

---

## 2. `--host` Generalization vs. `set_ollama_host()` Conflict

### Contradiction

The B-decision says `--host` defaults to `None` and is the universal endpoint for the main backend.

Current code in `lama_ole.py`:
```python
host_url = args.host          # Could be OpenAI URL now
set_ollama_host(host_url)     # Sets media tools' Ollama host — WRONG
```

If `--host https://api.openai.com --backend openai_compat`, then `set_ollama_host("https://api.openai.com")` makes media tools send image requests to OpenAI — which doesn't support Ollama's `/api/generate` image endpoint.

### Resolution Needed

`set_ollama_host()` must receive the **Ollama** host, not the main backend host. Options:

- (a) `set_ollama_host()` uses `LAMA_OLE_VISION_HOST` if set, otherwise `http://localhost:11434` (hardcoded Ollama default) — independent of `--host`? 
- (b) Add a dedicated `--vision-host` CLI flag (separate from `--host`)?
- (c) `set_ollama_host()` uses the default Ollama URL unless `LAMA_OLE_VISION_HOST` overrides it; `--host` only affects the main backend? 
- (d) The media Tools prefer `LAMA_OLE_VISION_HOST` over get_ollama_host(), that means get_ollama_host() can return `http://localhost:11434` and set_ollama_host is no longer needed. # this one

### I made some comments. If further ambiguities and contradictions come up though my decisions or if I missed smoething comment it in 004_ambiguities_and_contradictions_E.md

