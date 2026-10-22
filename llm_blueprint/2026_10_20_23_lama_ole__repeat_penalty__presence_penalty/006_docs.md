# 006 — Documentation updates (`README.md`)

Three spots in `README.md` document parameters/env vars and need the new entries.

## 1. Feature list — "Sampling Options" bullet

Currently:

```
- **Sampling Options** — Pass through `temperature`, `top_p`, `top_k` to control decoding.
```

Updated to:

```
- **Sampling Options** — Pass through `temperature`, `top_p`, `top_k`, `repeat_penalty`, `presence_penalty` to control decoding.
```

## 2. Configuration Options table (near line ~631)

Currently:

| `--top_k INT` | Constrained-sampling threshold (token count) | (backend default) |
| `--num_ctx INT` | Context window size | (Ollama default) |

Added two rows after `--top_k`:

| `--repeat_penalty FLOAT` | Penalize repeat sequence of tokens | (backend default) |
| `--presence_penalty FLOAT` | Penalize tokens based on their presence in the text so far | (backend default) |

## 3. Environment Variables table (near line ~868)

Currently:

| `LAMA_OLE_TOP_K` | integer | `--top_k` |
| `LAMA_OLE_NUM_CTX` | integer | `--num_ctx` |

Added two rows after `LAMA_OLE_TOP_K`:

| `LAMA_OLE_REPEAT_PENALTY` | number | `--repeat_penalty` |
| `LAMA_OLE_PRESENCE_PENALTY` | number | `--presence_penalty` |

## Consistency notes

- The Configuration Options table uses `(backend default)` for both new parameters,
  consistent with `top_p`/`top_k` phrasing since they have no built-in default.
- No changes to any other README section: precedence, env-file, and inspection docs
  describe these mechanisms generically and already apply.
