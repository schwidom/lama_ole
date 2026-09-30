# 006 — Documentation updates (`README.md`)

Three spots in `README.md` document parameters/env vars and need the new entries.

## 1. Feature list — "Ollama Options" bullet

Currently:

```
- **Ollama Options** — Pass through `temperature`, `num_ctx`, `num_gpu`,
  `keep_alive`.
```

Add the two sampling knobs:

```
- **Sampling Options** — Pass through `temperature`, `top_p`, `top_k` to control
  decoding.
- **Ollama Options** — Pass through `num_ctx`, `num_gpu`, `keep_alive`.
```

## 2. Configuration Options table (near line ~631)

Currently:

| `--temperature FLOAT` | Sampling temperature | `0.0` |

Add two rows after it:

| `--top_p FLOAT` | Constrained-sampling threshold (cumulative probability) | (backend default) |
| `--top_k INT` | Constrained-sampling threshold (token count) | (backend default) |

## 3. Environment Variables table (near line ~868)

Currently:

| `LAMA_OLE_TEMPERATURE` | number | `--temperature` |

Add two rows after it:

| `LAMA_OLE_TOP_P` | number | `--top_p` |
| `LAMA_OLE_TOP_K` | integer | `--top_k` |

## Consistency notes

- The Configuration Options table already documents backend defaults for the other
  sampling-relevant knobs (`num_ctx`, `num_gpu`) as `(Ollama default)`; we use the
  analogous `(backend default)` phrasing since top_p/top_k are backend-specific.
- No changes to any other README section: precedence, env-file, and inspection docs
  describe these mechanisms generically and already apply.
