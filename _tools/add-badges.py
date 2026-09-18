#!/usr/bin/env python3
"""Append Dimensions + Altmetric badges to the existing publication pages.

`open-alex.py` writes the badge block whenever it regenerates an article page,
but a full sync needs network access and an OpenAlex key. This script patches
the pages that already exist, in place, using the DOI in each page's front
matter.

The markup comes from `badge_block()` in open-alex.py — imported, not copied,
so what this script writes is byte-identical to what a sync writes and the next
sync produces no diff.

Idempotent: an existing badge block is removed and re-appended, so re-runs
change nothing and a block left mid-page (e.g. by add-bib-sections.py, which
inserts the BibTeX section after `## Links`) is moved back to the end.

Usage:
    python _tools/add-badges.py
    python _tools/add-badges.py --dry-run
    python _tools/add-badges.py --dir research/articles
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE_GLOBS = ("research/articles/*/index.qmd", "research/working-papers/*/index.qmd")


def load_generator():
    """Import open-alex.py (hyphenated filename, so not importable directly)."""
    spec = importlib.util.spec_from_file_location("openalex_sync", ROOT / "open-alex.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def page_doi(text: str) -> str:
    """The `doi:` value from the YAML front matter, or '' if absent."""
    front = re.match(r"(?s)\A\s*---\n(.*?)\n---", text)
    if not front:
        return ""
    match = re.search(r"(?m)^doi:\s*(.+?)\s*$", front.group(1))
    return match.group(1).strip().strip("\"'") if match else ""


def apply_block(text: str, block: str, start: str, end: str) -> str:
    """Drop any existing badge block and append the given one at the very end."""
    text = re.sub(rf"(?ms)^{re.escape(start)}.*?^{re.escape(end)}[ \t]*\n?", "", text)
    return text.rstrip("\n") + "\n\n" + block + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report without writing")
    ap.add_argument("--dir", action="append", default=[],
                    help="restrict to this directory (repeatable)")
    args = ap.parse_args()

    gen = load_generator()

    if args.dir:
        globs = [f"{d.rstrip('/')}/*/index.qmd" for d in args.dir]
    else:
        globs = list(PAGE_GLOBS)

    pages = sorted(p for g in globs for p in ROOT.glob(g))
    if not pages:
        print("no publication pages found", file=sys.stderr)
        return 1

    changed = no_doi = 0
    for page in pages:
        text = page.read_text(encoding="utf-8")
        doi = page_doi(text)
        block = gen.badge_block(doi)
        if not block:
            no_doi += 1
            continue
        new = apply_block(text, block, gen.BADGES_START, gen.BADGES_END)
        if new != text:
            changed += 1
            if not args.dry_run:
                page.write_text(new, encoding="utf-8")

    verb = "would update" if args.dry_run else "updated"
    print(f"{len(pages)} pages, {verb} {changed}, {no_doi} without a DOI (skipped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
