#!/usr/bin/env python3
"""Print an annotated directory tree, the kind that goes in a README.

`tree` gives you the box-drawing characters but no comments, and retyping the
comments each time the layout changes is how they go stale. This reads the
notes from a sidecar file (`_tools/tree-notes.yml` by default, one
`path: comment` per line) and aligns them in a trailing column.

    python _tools/tree-schema.py                  # whole project, depth 2
    python _tools/tree-schema.py -L 3 photos      # deeper, one subtree
    python _tools/tree-schema.py --dirs-only

Nothing is written; redirect stdout into your README.
"""

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
NOTES = ROOT / "_tools" / "tree-notes.yml"

# noise that should never appear in a published schema
SKIP = {".git", ".quarto", "_freeze", "__pycache__", ".DS_Store", "docs",
        "site_libs", "thumbs", ".venv", ".Rproj.user"}


def load_notes(path):
    """{relative path: comment}; a trivial 'key: value' reader, no YAML dep."""
    notes = {}
    if not path.exists():
        return notes
    for line in path.read_text(encoding="utf-8").split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r'^"?([^"]+?)"?\s*:\s*(.*)$', line)
        if m:
            notes[m.group(1).rstrip("/")] = m.group(2).strip().strip('"')
    return notes


def entries(d, dirs_only):
    out = [p for p in d.iterdir()
           if p.name not in SKIP and not p.name.startswith(".")
           and (p.is_dir() or not dirs_only)]
    # directories first, then files, each alphabetical - matches `tree --dirsfirst`
    return sorted(out, key=lambda p: (not p.is_dir(), p.name.lower()))


def walk(d, notes, depth, dirs_only, prefix="", rows=None, base=None):
    rows = [] if rows is None else rows
    base = base or d
    kids = entries(d, dirs_only)
    for i, p in enumerate(kids):
        last = i == len(kids) - 1
        stem = "└── " if last else "├── "
        label = p.name + ("/" if p.is_dir() else "")
        rel = str(p.relative_to(base))
        # match on the relative path only: a bare-name fallback would annotate
        # _archive/_extensions with the note written for _extensions
        note = notes.get(rel) or notes.get(rel + "/") or ""
        if p.is_dir() and not note:
            n = sum(1 for f in p.rglob("*")
                    if f.is_file() and not SKIP.intersection(f.relative_to(p).parts)
                    and f.name not in SKIP)
            note = f"{n} file{'s' if n != 1 else ''}" if n else ""
        rows.append((prefix + stem + label, note))
        if p.is_dir() and depth > 1:
            walk(p, notes, depth - 1, dirs_only,
                 prefix + ("    " if last else "│   "), rows, base)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=str(ROOT))
    ap.add_argument("-L", "--depth", type=int, default=2)
    ap.add_argument("--dirs-only", action="store_true")
    ap.add_argument("--notes", default=str(NOTES))
    ap.add_argument("--no-counts", action="store_true",
                    help="omit the automatic 'N files' note on uncommented folders")
    args = ap.parse_args()

    root = pathlib.Path(args.path).resolve()
    notes = load_notes(pathlib.Path(args.notes))
    rows = walk(root, notes, args.depth, args.dirs_only)
    if args.no_counts:
        rows = [(t, "" if re.fullmatch(r"\d+ files?", n) else n) for t, n in rows]

    width = max((len(t) for t, n in rows if n), default=0)
    print("```")
    print(f"{root.name}/")
    for tree, note in rows:
        print(f"{tree:<{width}}  # {note}" if note else tree)
    print("```")
    return 0


if __name__ == "__main__":
    sys.exit(main())
