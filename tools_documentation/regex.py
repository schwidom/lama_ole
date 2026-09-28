def regex_help():
    return r"""

regex escape sequences
| Pattern | Meaning |
|---|---|
| `\.`, `\*`, `\+`, `\(`, `\)`, `\[`, `\]`, `\{`, `\}`, `\|`, `\^`, `\$`, `\\` | The literal following character (turns off metacharacter meaning). |
| `\d` | A digit `[0-9]` (Unicode digits when not ASCII‑flagged). |
| `\D` | Non‑digit. |
| `\w` | Word char `[A-Za-z0-9_]` (Unicode word chars). |
| `\W` | Non‑word char. |
| `\s` | Whitespace (`\t\n\r\f\v \u00a0`, etc.). |
| `\S` | Non‑whitespace. |
| `\b` | Word boundary (between `\w` and `\W`). |
| `\B` | Not a word boundary. |
| `\n`, `\t`, `\r`, `\f`, `\v` | The matching control character. |
| `\x1f`, `\u1234`, `\U0001F600` | Hex/Unicode byte escapes. |
"""
