#!/usr/bin/env python3
"""Convert the pipe-separated `## Links` line on paper pages into buttons.

Rewrites

    ## Links

    [DOI Link](...) | [PDF](...) | [OpenAlex](...)

as

    ## Links

    ::: {.paper-links}
    [DOI Link](...){.paper-link-primary}
    [PDF](...)
    [OpenAlex](...)
    :::

which html/pedroj.scss renders as grey buttons in both light and dark mode.
open-alex.py now writes pages in this form directly, so this tool only exists
to migrate pages generated before that change; it is idempotent, so a page
already converted is left untouched.

Usage:
    python _tools/linkify-paper-links.py --dry-run
    python _tools/linkify-paper-links.py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE_GLOBS = ("research/articles/*/index.qmd", "research/working-papers/*/index.qmd")

# The link that gets the darker fill (primary action on the page).
PRIMARY_LABEL = "DOI Link"

LINKS_SECTION = re.compile(
    r"(?ms)^## Links[ \t]*\n\n(?P<body>.+?)\n(?=\n|\Z)")
# One level of nested parentheses: several DOIs contain them, e.g.
# 10.1890/0012-9658(2002)083[2416:gpippm]2.0.co;2
MD_LINK = re.compile(r"^\[[^\]]*\]\((?:[^()\s]|\([^()]*\))*\)(\{[^}]*\})?$")
# Separator between links: "|" or the escaped "\|", optionally across a newline.
SEPARATOR = re.compile(r"\s*\\?\|\s*")


def convert(text: str) -> str | None:
    """Return the rewritten page, or None when there is nothing to do."""
    if "::: {.paper-links}" in text:
        return None  # already converted
    m = LINKS_SECTION.search(text)
    if not m:
        return None

    parts = [p.strip() for p in SEPARATOR.split(m.group("body").strip())]
    # Bail out rather than mangle anything that is not a plain link list.
    if not parts or not all(MD_LINK.match(p) for p in parts):
        return None

    out = []
    for part in parts:
        label = part[1:part.index("]")]
        if label == PRIMARY_LABEL and not part.endswith("}"):
            part += "{.paper-link-primary}"
        out.append(part)

    block = "::: {.paper-links}\n" + "\n".join(out) + "\n:::"
    return text[:m.start("body")] + block + text[m.end("body"):]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report without writing")
    args = ap.parse_args()

    converted = skipped = 0
    for pattern in PAGE_GLOBS:
        for qmd in sorted(ROOT.glob(pattern)):
            text = qmd.read_text(encoding="utf-8")
            new = convert(text)
            if new is None:
                skipped += 1
                continue
            if not args.dry_run:
                qmd.write_text(new, encoding="utf-8")
            converted += 1

    verb = "would convert" if args.dry_run else "converted"
    print(f"{verb} {converted}, left alone {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
