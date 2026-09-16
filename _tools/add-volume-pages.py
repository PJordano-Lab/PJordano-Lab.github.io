#!/usr/bin/env python3
"""Backfill `volume-pages:` into paper pages from their own BibTeX block.

Each page under research/{articles,working-papers} carries a ```bibtex block
(inserted by _tools/add-bib-sections.py). Most of those entries already hold
`volume` and `pages`, so the combined citation-detail field can be written
without any network call. Formatting is delegated to `format_volume_pages` in
open-alex.py, so the backfilled pages and future OpenAlex syncs agree.

The field feeds the `volume-pages` column of the listings in research.qmd:

    volume-pages: "Vol. 64: 1021-1035"      (en dash in the file)

Idempotent: an existing `volume-pages:` line is replaced, never duplicated.

Usage:
    python _tools/add-volume-pages.py --dry-run
    python _tools/add-volume-pages.py
"""

import argparse
import importlib.util
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIRS = [ROOT / "research" / "articles", ROOT / "research" / "working-papers"]


def load_formatter():
    """Import format_volume_pages from open-alex.py without its dependencies.

    The module imports `requests` at top level, which need not be installed to
    run this script, so the single function is exec'd out of the source.
    """
    src = (ROOT / "open-alex.py").read_text(encoding="utf-8")
    start = src.index("def format_volume_pages")
    end = src.index("class OpenAlexArticleSync")
    ns = {"re": re}
    exec(src[start:end], ns)
    return ns["format_volume_pages"]


def bibtex_fields(text):
    """(volume, pages) from a page's ```bibtex block; '' when absent."""
    m = re.search(r"```bibtex\n(.*?)\n```", text, re.S)
    if not m:
        return "", ""
    entry = m.group(1)

    def field(name):
        f = re.search(rf"^\s*{name}\s*=\s*[{{\"]?(.*?)[}}\"]?,?\s*$",
                      entry, re.M | re.I)
        if not f:
            return ""
        return f.group(1).strip().strip("{}\"").strip()

    return field("volume"), field("pages")


def apply(text, value):
    """Insert or replace the volume-pages line inside the front matter."""
    line = f'volume-pages: "{value}"'
    existing = re.search(r"^volume-pages:.*$", text, re.M)
    if existing:
        return text[: existing.start()] + line + text[existing.end():]
    # place it directly after pub-journal, else after date, else after title
    for key in ("pub-journal", "date", "title"):
        anchor = re.search(rf"^{key}:.*$", text, re.M)
        if anchor:
            return text[: anchor.end()] + "\n" + line + text[anchor.end():]
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    fmt = load_formatter()
    written = no_data = no_bib = 0
    samples = []

    for d in DIRS:
        for page in sorted(d.glob("*/index.qmd")):
            text = page.read_text(encoding="utf-8")
            if "```bibtex" not in text:
                no_bib += 1
                continue
            volume, pages = bibtex_fields(text)
            value = fmt(volume, pages=pages) if (volume or pages) else ""
            if not value:
                no_data += 1
                continue
            new = apply(text, value)
            if new != text and not args.dry_run:
                page.write_text(new, encoding="utf-8")
            written += 1
            if len(samples) < 5:
                samples.append(f"{page.parent.name[:44]:<44} {value}")

    for s in samples:
        print("  " + s)
    print(f"\npages with volume-pages written: {written} | "
          f"BibTeX present but no volume/pages: {no_data} | no BibTeX block: {no_bib}"
          f"{' (dry run, nothing written)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
