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


def load_formatter(name="format_volume_pages"):
    """Import a formatter from open-alex.py without pulling in its dependencies.

    The module imports `requests` at top level, which need not be installed to
    run this script, so the single function is exec'd out of the source.
    """
    src = (ROOT / "open-alex.py").read_text(encoding="utf-8")
    start = src.index("def format_citation_detail")
    end = src.index("class OpenAlexArticleSync")
    ns = {"re": re}
    exec(src[start:end], ns)
    return ns[name]


def bibtex_fields(text, names=("volume", "pages", "year", "journal", "doi")):
    """Requested fields from a page's ```bibtex block; '' for any that's absent."""
    m = re.search(r"```bibtex\n(.*?)\n```", text, re.S)
    if not m:
        return {n: "" for n in names}
    entry = m.group(1)

    def field(name):
        f = re.search(rf"^\s*{name}\s*=\s*[{{\"]?(.*?)[}}\"]?,?\s*$",
                      entry, re.M | re.I)
        if not f:
            return ""
        return f.group(1).strip().strip("{}\"").strip()

    return {n: field(n) for n in names}


def apply(text, key, value):
    """Insert or replace one front-matter key. Idempotent."""
    line = f'{key}: "{value}"'
    existing = re.search(rf"^{re.escape(key)}:.*$", text, re.M)
    if existing:
        return text[: existing.start()] + line + text[existing.end():]
    # keep the reference fields together, in citation order
    for anchor_key in ("volume-pages", "pub-journal", "date", "title"):
        anchor = re.search(rf"^{anchor_key}:.*$", text, re.M)
        if anchor:
            return text[: anchor.end()] + "\n" + line + text[anchor.end():]
    return text


def full_reference(fm, build):
    """Rendered reference from a page's own front-matter values.

    Formatting is `format_full_reference` in open-alex.py, so a backfill run
    and an OpenAlex sync produce byte-identical blocks. `authors-full` (every
    author, surname-first) is preferred over the truncated `authors` field
    that the title block shows; book and chapter pages additionally carry
    booktitle / editors / publisher / place.
    """
    entry_type = fm.get("pub-type") or "article"
    return build(
        entry_type=entry_type,
        authors=fm.get("authors-full") or fm.get("authors", ""),
        year=fm.get("year") or (fm.get("date") or "")[:4],
        title=fm.get("title", ""),
        journal=fm.get("pub-journal", "") if entry_type in ("article", "misc") else "",
        volume=fm.get("volume", ""),
        pages=fm.get("pages", ""),
        booktitle=fm.get("booktitle", ""),
        editors=fm.get("editors", ""),
        publisher=fm.get("publisher", ""),
        place=fm.get("place", ""),
        doi=fm.get("doi", ""),
        url=fm.get("citation-url", ""),
        note="Preprint" if entry_type == "misc" else "",
    )


def read_front_matter(text):
    """Flat dict of top-level scalar keys in the YAML front matter."""
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    fm = {}
    if not m:
        return fm
    for line in m.group(1).split("\n"):
        k = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if k:
            fm[k.group(1)] = k.group(2).strip().strip('"').strip("'")
    return fm


REF_START = "<!-- full-reference:start -->"
REF_END = "<!-- full-reference:end -->"


def apply_reference(text, ref):
    """Put the rendered reference right after the front matter, between
    sentinels so a re-run replaces it instead of stacking copies."""
    block = f"{REF_START}\n::: {{.full-reference}}\n{ref}\n:::\n{REF_END}\n"
    existing = re.search(re.escape(REF_START) + r".*?" + re.escape(REF_END) + r"\n?", text, re.S)
    if existing:
        return text[: existing.start()] + block + text[existing.end():]
    fm_end = re.search(r"^---\n.*?\n---\n", text, re.S)
    if not fm_end:
        return text
    return text[: fm_end.end()] + "\n" + block + text[fm_end.end():]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-reference", action="store_true",
                    help="write the front-matter fields only, skip the rendered "
                         "reference block on the page")
    args = ap.parse_args()

    fmt = load_formatter()
    detail_fmt = load_formatter("format_citation_detail")
    ref_fmt = load_formatter("format_full_reference")
    counts = {"year": 0, "volume": 0, "pages": 0, "reference": 0, "detail": 0}
    no_bib = 0
    samples = []

    for d in DIRS:
        for page in sorted(d.glob("*/index.qmd")):
            text = page.read_text(encoding="utf-8")
            has_bib = "```bibtex" in text
            if not has_bib:
                # working papers carry an Oikos-style "## Full citation" instead
                # of a BibTeX block; they still get year from their own date
                no_bib += 1
            bib = bibtex_fields(text) if has_bib else {
                k: "" for k in ("volume", "pages", "year", "journal", "doi")}
            if not bib.get("year"):
                # several entries omit year; the page's own date always has it
                fm0 = read_front_matter(text)
                bib["year"] = (fm0.get("date") or "")[:4]
            new = text
            for key in ("year", "volume", "pages"):
                value = bib.get(key, "")
                if key == "pages" and value:
                    # normalise BibTeX's 1021--1035 to an en dash, as the
                    # combined field already does
                    value = re.sub(r"\s*(?:--|-|\u2010|\u2012|\u2014)\s*",
                                   "\u2013", value)
                if not value:
                    continue
                new = apply(new, key, value)
                counts[key] += 1
            # combined field stays in step with the parts
            combined = fmt(bib.get("volume"), pages=bib.get("pages"))
            if combined:
                new = apply(new, "volume-pages", combined)
            # one compact column for the listing: year, volume and pages
            pages_norm = re.sub(r"\s*(?:--|-|\u2010|\u2012|\u2014)\s*", "\u2013",
                                bib.get("pages", "") or "")
            detail = detail_fmt(bib.get("year"), bib.get("volume"), pages_norm)
            if detail:
                new = apply(new, "citation-detail", detail)
                counts["detail"] = counts.get("detail", 0) + 1

            # a page that already shows an Oikos-style citation does not need a
            # second rendered reference
            if not args.no_reference and "## Full citation" not in new:
                fm = read_front_matter(new)
                ref = full_reference(fm, ref_fmt)
                if ref and fm.get("title"):
                    new = apply_reference(new, ref)
                    counts["reference"] += 1
                    if len(samples) < 3:
                        samples.append(ref)

            if new != text and not args.dry_run:
                page.write_text(new, encoding="utf-8")

    for s_ in samples:
        print("  " + s_[:150])
    print(f"\nyear: {counts['year']} | volume: {counts['volume']} | "
          f"pages: {counts['pages']} | citation-detail: {counts['detail']} | "
          f"reference blocks: {counts['reference']} | "
          f"no BibTeX block: {no_bib}"
          f"{' (dry run, nothing written)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
