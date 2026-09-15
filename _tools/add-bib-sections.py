#!/usr/bin/env python3
"""Insert a BibTeX code block into each research/articles/*/index.qmd.

Each article page gets a "## BibTeX" section holding its entry from
_archive/_jekyll/_bibliography/papers.bib as a fenced ```bibtex block,
placed immediately after the "## Links" section.

Matching is by DOI first (case-insensitive, prefix-stripped), then by
normalised title. Pages with no match are left untouched and reported.
Re-running is safe: an existing BibTeX section is replaced, not duplicated.

Usage:
  python _tools/add-bib-sections.py --dry-run          # report only
  python _tools/add-bib-sections.py --limit 5          # write 5 matched pages
  python _tools/add-bib-sections.py --slug angiosperm  # target pages by slug
  python _tools/add-bib-sections.py --no-abstract      # drop abstract/keywords
  python _tools/add-bib-sections.py                    # write all pages
"""

import argparse
import difflib
import re
import sys
import unicodedata
from pathlib import Path

BIB = Path("_archive/_jekyll/_bibliography/papers.bib")
ARTICLES = Path("research/articles")
HEADING = "## BibTeX"
FUZZY_CUTOFF = 0.93


def norm_doi(doi):
    if not doi:
        return None
    doi = doi.strip().strip("{}").lower()
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", doi)
    return doi.rstrip(".") or None


def norm_title(title):
    if not title:
        return None
    # LaTeX accent commands ({\'o}, \~n, \"u) must collapse onto the bare
    # letter, not leave a gap: strip the command, then the braces.
    t = re.sub(r"\\[`'\"^~=.c]\s*", "", title)
    t = re.sub(r"\\[a-zA-Z]+\s*", " ", t)
    t = t.replace("{", "").replace("}", "")
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9]+", " ", t.lower())
    return " ".join(t.split()) or None


def parse_bib(path):
    """Split the .bib into raw entries, keyed by DOI and normalised title."""
    text = path.read_text(encoding="utf-8", errors="replace")
    entries, by_doi, by_title = [], {}, {}
    starts = [m.start() for m in re.finditer(r"(?m)^@\w+\s*\{", text)]
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        raw = text[start:end].strip()
        f = lambda name: (m.group(1).strip() if (m := re.search(
            rf"(?mi)^\s*{name}\s*=\s*\{{(.*?)\}},?\s*$", raw, re.S)) else None)
        entry = {"raw": raw, "doi": norm_doi(f("DOI")),
                 "title": norm_title(f("title")), "year": (f("year") or "").strip()}
        entries.append(entry)
        # first entry wins: the .bib holds duplicate preprint/published pairs
        if entry["doi"]:
            by_doi.setdefault(entry["doi"], entry)
        if entry["title"]:
            by_title.setdefault(entry["title"], entry)
    return entries, by_doi, by_title


def front_matter(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    return m.group(1) if m else ""


def field(fm, name):
    m = re.search(rf"(?m)^{name}:\s*(.+?)\s*$", fm)
    if not m:
        return None
    return m.group(1).strip().strip("'\"")


def trim_fields(raw, names=("abstract", "keywords")):
    """Drop verbose fields, keeping the entry valid BibTeX."""
    for name in names:
        raw = re.sub(rf"(?mis)^\s*{name}\s*=\s*\{{.*?\}},?[ \t]*\n", "", raw)
    return raw


def bib_block(raw):
    return f"{HEADING}\n\n```bibtex\n{raw.strip()}\n```\n"


def insert_block(text, raw):
    """Put the BibTeX section right after the Links section."""
    block = bib_block(raw)
    # replace an existing BibTeX section (idempotent re-runs)
    existing = re.search(rf"(?ms)^{HEADING}\s*\n.*?(?=^## |\Z)", text)
    if existing:
        return text[:existing.start()] + block + text[existing.end():]

    links = re.search(r"(?ms)^## Links\s*\n(.*?)(?=^## |\Z)", text)
    if not links:
        return text.rstrip("\n") + "\n\n" + block
    head = text[:links.end()].rstrip("\n")
    tail = text[links.end():].lstrip("\n")
    return f"{head}\n\n{block}" + (f"\n{tail}" if tail else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after this many pages have been written")
    ap.add_argument("--fuzzy", action="store_true",
                    help="also accept high-similarity title matches in the same year")
    ap.add_argument("--no-abstract", action="store_true",
                    help="drop the abstract and keywords fields from the entry")
    ap.add_argument("--slug", action="append", default=[],
                    help="substring of a slug to process first (repeatable)")
    args = ap.parse_args()

    if not BIB.exists() or not ARTICLES.is_dir():
        sys.exit("run this from the site root")

    entries, by_doi, by_title = parse_bib(BIB)
    pages = sorted(ARTICLES.glob("*/index.qmd"))
    if args.slug:
        wanted = [p for p in pages
                  if any(s.lower() in p.parent.name.lower() for s in args.slug)]
        pages = wanted + [p for p in pages if p not in wanted]

    hits_doi = hits_title = hits_fuzzy = misses = written = 0
    unmatched = []
    for page in pages:
        text = page.read_text(encoding="utf-8")
        fm = front_matter(text)
        doi, title = norm_doi(field(fm, "doi")), norm_title(field(fm, "title"))
        entry = by_doi.get(doi) if doi else None
        how = "doi"
        if entry is None and title:
            entry, how = by_title.get(title), "title"
        if entry is None and title and args.fuzzy:
            # typography-only differences (all-caps, en-dashes, LaTeX accents)
            year = (field(fm, "date") or "")[:4]
            near = difflib.get_close_matches(title, list(by_title), n=1, cutoff=FUZZY_CUTOFF)
            cand = by_title[near[0]] if near else None
            if cand and (not year or not cand["year"] or year == cand["year"]):
                entry, how = cand, "fuzzy"
        if entry is None:
            misses += 1
            unmatched.append(page.parent.name)
            continue
        hits_doi += how == "doi"
        hits_title += how == "title"
        hits_fuzzy += how == "fuzzy"
        raw = trim_fields(entry["raw"]) if args.no_abstract else entry["raw"]
        if not args.dry_run:
            page.write_text(insert_block(text, raw), encoding="utf-8")
        written += 1
        print(f"  [{how}] {page.parent.name}")
        if args.limit and written >= args.limit:
            break

    print(f"bib entries: {len(entries)} ({len(by_doi)} DOIs, {len(by_title)} titles)")
    print(f"pages processed: {written + misses} | by DOI: {hits_doi} | by title: {hits_title} "
          f"| fuzzy: {hits_fuzzy} | unmatched: {misses}")
    for name in unmatched[:15]:
        print("  no bib entry:", name)
    if len(unmatched) > 15:
        print(f"  ... and {len(unmatched) - 15} more")
    print("dry run, nothing written" if args.dry_run else "written")


if __name__ == "__main__":
    main()
