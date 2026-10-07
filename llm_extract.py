#!/usr/bin/env python3
"""llm_extract.py - Extract code snippets from files (argparse version).

Code snippets are delimited by lines beginning with triple backticks (```).
Snippets are numbered sequentially across ALL files, in the order given.

Precedence of actions: --help > --count > --list > --select

Usage examples:
    llm_extract.py --count file1.md file2.md
    llm_extract.py --list file1.md
    llm_extract.py --select 1,3 -v file1.md
    llm_extract.py --select all --quote --indent 4 file1.md
"""

import argparse
import re
import sys

# A code fence is any line that *starts* with triple backticks (```, ```python ...).
FENCE_RE = re.compile(r'^```')

HELP_TEXT = """\
llm_extract.py - Extract code snippets from files.

USAGE:
    llm_extract.py [options] <files>...

OPTIONS:
  --help              Show this help and exit (highest priority).
  --count             Print the number of code snippets found, then exit.
  --list              List every code snippet with up to 5 lines of context
                      before and after each '```' fence, numbered for selection.
  --select <nr>       Print selected snippet(s) by number (comma separated),
                      or the word 'all'. Example: --select 1,3   or   --select all
  --quote           Wrap selected snippets in ``` fences when using --select.
  -v                  Verbose: print filename and snippet number before each
                      output block (--list or --select).
  --indent <nr>       Indent/dedent code content: add |nr| spaces if positive,
                      remove up to |nr| leading spaces if negative.

FILES:
    The trailing arguments are the input files. Snippets are numbered through
    all files in the order given (2 files x 2 snippets => snippets 1..4).

BEHAVIOUR:
    Precedence: --help > --count > --list > --select
    A warning is printed when a code block is opened but never closed.
"""


def find_code_blocks(lines):
    """Return (blocks, unclosed).

    blocks   -> list of (open_idx, close_idx) for well-formed snippets.
    unclosed -> list of open indices that were never closed.
    """
    blocks = []
    unclosed = []
    i, n = 0, len(lines)
    while i < n:
        if FENCE_RE.match(lines[i]):
            j = i + 1
            found = False
            while j < n:
                if FENCE_RE.match(lines[j]):
                    blocks.append((i, j))
                    found = True
                    break
                j += 1
            if found:
                i = j + 1          # continue after the closing fence
            else:
                unclosed.append(i)  # no closing fence to EOF -> stop scanning
                i = n
        else:
            i += 1
    return blocks, unclosed


def apply_indent(content, indent):
    """Indent/dedent content lines.

    indent > 0 : prepend |indent| spaces to every line.
    indent < 0 : strip up to |indent| leading spaces from every line.
    indent == 0: return unchanged copy.
    """
    if indent == 0 or not content:
        return list(content)
    out = []
    if indent > 0:
        pad = ' ' * indent
        for line in content:
            out.append(pad + line)
    else:
        n = -indent
        for line in content:
            stripped = line.lstrip(' ')
            removed = len(line) - len(stripped)
            out.append(line[n:] if removed >= n else stripped)
    return out


def parse_select(spec, total):
    """Parse a --select spec into a list of 1-based snippet numbers.

    'all' -> every snippet. Otherwise comma separated integers (order kept).
    Invalid / out-of-range numbers produce a warning and are skipped.
    """
    spec = spec.strip()
    if not spec:
        return []
    if spec.lower() == 'all':
        return list(range(1, total + 1))

    indices = []
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            num = int(part)
        except ValueError:
            print(f"Warning: invalid snippet number '{part}'.", file=sys.stderr)
            continue
        if 1 <= num <= total:
            indices.append(num)
        else:
            print(f"Warning: snippet number {num} out of range (1..{total}).",
                  file=sys.stderr)
    return indices


def load_files(files):
    """Read files and build the globally-numbered list of snippets."""
    snippets = []          # each: dict with file, fidx, num, start, end, content
    warnings = []
    files_lines = {}       # filepath -> list[str] (for --list context)

    for fidx, filepath in enumerate(files):
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
                raw = fh.read()
        except OSError as e:
            print(f"Error: cannot read file '{filepath}': {e}", file=sys.stderr)
            return None
        raw = raw.replace('\r\n', '\n').replace('\r', '\n')
        lines = raw.split('\n')
        files_lines[filepath] = lines

        blocks, unclosed = find_code_blocks(lines)
        for open_idx, close_idx in blocks:
            snippets.append({
                'file': filepath,
                'fidx': fidx,
                'num': len(snippets) + 1,
                'start': open_idx,
                'end': close_idx,
                'content': lines[open_idx + 1:close_idx],
            })
        for u in unclosed:
            warnings.append(
                f"Warning: code block opened but not closed "
                f"in '{filepath}' (line {u + 1})."
            )

    return {'snippets': snippets, 'warnings': warnings, 'files_lines': files_lines}


def list_snippets(snippets, files_lines, verbose):
    """Print each snippet with 5 lines of context before/after and its number."""
    if not snippets:
        print("No code snippets found.", file=sys.stderr)
        return
    for s in snippets:
        lines = files_lines[s['file']]
        # header (always shows the selection number; filename only when -v)
        if verbose:
            print(f"{s['file']}  [snippet {s['num']}]")
        else:
            print(f"[snippet {s['num']}]")

        # context before the opening fence (up to 5 lines)
        for idx in range(max(0, s['start'] - 5), s['start']):
            print(lines[idx])

        # # the fence + code content + closing fence
        # print(lines[s['start']])
        # for cline in s['content']:
        #     print(cline)
        # print(lines[s['end']])

        # the fence
        print(lines[s['start']])

        if s['end'] - s['start'] -1 <= 5 + 5 : # space between the fences
            for cline in s['content']:
                print(cline)
        else :
            for cline in s['content'][0:5]:
                print(cline)
            print( '.....')
            for cline in s['content'][-5:]:
                print(cline)

        # closing fence
        print(lines[s['end']])

        # context after the closing fence (up to 5 lines)
        for idx in range(s['end'] + 1, min(len(lines), s['end'] + 1 + 5)):
            print(lines[idx])

        print()  # blank separator between snippets


def select_snippets(snippets, indices, verbose, quote, indent):
    """Print selected snippets (optionally quoted and indented)."""
    for pos, idx in enumerate(indices):
        s = snippets[idx - 1]
        if verbose:
            print(f"{s['file']}  [snippet {s['num']}]")

        content = apply_indent(s['content'], indent)
        if quote:
            print("```")
            for cline in content:
                print(cline)
            print("```")
        else:
            for cline in content:
                print(cline)
            # keep multiple non-quoted snippets visually separated
            if pos != len(indices) - 1:
                print()


def build_parser():
    """Construct the argparse parser."""
    parser = argparse.ArgumentParser(
        prog='llm_extract.py',
        description='Extract code snippets delimited by ``` fences from files. '
                    'Precedence: --help > --count > --list > --select.',
        add_help=False,                       # we keep -h/--help available but
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--help', action='help', default=argparse.SUPPRESS,
                        help='show this help message and exit')

    parser.add_argument('--count', action='store_true',
                        help='print the number of code snippets found, then exit')
    parser.add_argument('--list', action='store_true',
                        help='list every snippet with 5 lines of context, numbered')
    parser.add_argument('--select', metavar='NR',
                        help="selected snippet(s): comma-separated numbers or 'all'")
    parser.add_argument('--quote', action='store_true',
                        help='wrap selected snippets in ``` fences (with --select)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='print filename and snippet number before each block')
    parser.add_argument('--indent', type=int, default=0, metavar='NR',
                        help='add NR spaces if positive, remove up to |NR| '
                             'leading spaces if negative')

    parser.add_argument('files', nargs='*', metavar='FILE',
                        help='input files; snippets are numbered across all of them')
    return parser


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    parser = build_parser()
    args = parser.parse_args(argv)   # handles --help early exit automatically

    # --- Precedence: help > count > list > select -------------------------
    # (argparse already exits on --help; here we enforce the rest.)
    if args.count:
        loaded = load_files(args.files)
        if loaded is None:
            return 2
        print(len(loaded['snippets']))
        for w in loaded['warnings']:
            print(w, file=sys.stderr)
        return 0

    if args.list:
        loaded = load_files(args.files)
        if loaded is None:
            return 2
        list_snippets(loaded['snippets'], loaded['files_lines'], args.verbose)
        for w in loaded['warnings']:
            print(w, file=sys.stderr)
        return 0

    if args.select is not None:
        if not args.files:
            print("Error: no input files given.", file=sys.stderr)
            return 2
        loaded = load_files(args.files)
        if loaded is None:
            return 2
        snippets = loaded['snippets']
        for w in loaded['warnings']:
            print(w, file=sys.stderr)
        if not snippets:
            print("Error: no code snippets found in the given files.",
                  file=sys.stderr)
            return 2
        indices = parse_select(args.select, len(snippets))
        if not indices:
            print("Warning: no valid snippet numbers selected.",
                  file=sys.stderr)
            return 0
        select_snippets(snippets, indices, args.verbose,
                        args.quote, args.indent)
        return 0

    # No recognised action.
    if not args.files:
        parser.error("no input files given")   # argparse exits with code 2
    print("Error: no action specified (use --count, --list or --select).",
          file=sys.stderr)
    print("Try '--help' for more information.", file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
