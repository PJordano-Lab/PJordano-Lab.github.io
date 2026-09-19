#!/usr/bin/env python3
"""Merge the standalone "Open Access" line into the "Published in" line.

Pages written before the change carried the two fields as separate paragraphs,
with the open-access one below the badges:

    **Published in:** Nature

    <!-- badges ... -->

    **Open Access:** Yes

which is two stacked one-word paragraphs on the page. Both now share one line,
separated by the same spacer open-alex.py writes:

    **Published in:** Nature&emsp;&emsp;**Open Access:** Yes

An absent line means the work is not open access (the old generator emitted
the field only when `is_oa` was true), so those pages get an explicit "No".
Idempotent: a page already carrying the merged line is left untouched.

Usage:
    python _tools/compact-open-access.py --dry-run
    python _tools/compact-open-access.py
"""

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIRS = [ROOT / "research" / "articles", ROOT / "research" / "working-papers"]

PUBLISHED = re.compile(r"^\*\*Published in:\*\*[^\n]*$", re.M)
# the standalone field, with the blank line that separated it as a paragraph
OA_BLOCK = re.compile(r"\n*^\*\*Open Access:\*\*\s*(Yes|No)\s*$\n?", re.M)


def field_gap():
    """The spacer open-alex.py uses, read from the generator itself."""
    src = (ROOT / "open-alex.py").read_text(encoding="utf-8")
    m = re.search(r'^FIELD_GAP\s*=\s*"([^"]*)"', src, re.M)
    return m.group(1) if m else "&emsp;&emsp;"


def fix_heading_spacing(text):
    """Guarantee a blank line before every ATX heading.

    Removing the open-access paragraph can leave the next heading welded to
    the line above it ("<!-- badges:end -->" then "## Links"), which Pandoc
    reads as body text rather than a heading.
    """
    return re.sub(r"([^\n])\n(#{2,6} )", r"\1\n\n\2", text)


def compact(text, gap):
    """Return (new_text, status) with the two fields on one line."""
    text = fix_heading_spacing(text)
    published = PUBLISHED.search(text)
    if published and "**Open Access:**" in published.group(0):
        return text, "already merged"

    standalone = OA_BLOCK.search(text)
    status = standalone.group(1) if standalone else "No"
    if standalone:
        # drop the paragraph, keeping a blank line between its neighbours
        text = text[: standalone.start()] + "\n\n" + text[standalone.end():]
        text = re.sub(r"\n{3,}", "\n\n", text)

    published = PUBLISHED.search(text)
    if not published:
        return text, "no 'Published in' line"

    line = published.group(0).rstrip()
    merged = f"{line}{gap}**Open Access:** {status}"
    return text[: published.start()] + merged + text[published.end():], status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    gap = field_gap()
    counts = {}
    changed = 0
    pages = [p for d in DIRS for p in sorted(d.glob("*/index.qmd"))]
    for page in pages:
        text = page.read_text(encoding="utf-8")
        new, status = compact(text, gap)
        counts[status] = counts.get(status, 0) + 1
        if new != text:
            changed += 1
            if not args.dry_run:
                page.write_text(new, encoding="utf-8")

    print(f"pages: {len(pages)} | rewritten: {changed}"
          f"{' (dry run, nothing written)' if args.dry_run else ''}")
    for status, n in sorted(counts.items()):
        print(f"  {status}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
