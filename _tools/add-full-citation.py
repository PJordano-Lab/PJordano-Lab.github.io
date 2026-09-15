#!/usr/bin/env python3
"""Insert an Oikos-style "Full citation" section into working-paper pages.

Reference style follows oikos.bst / oikos.csl from
MS_Mywork/MS_Oikos_SI-FSD2024/ms/maintext:

    Family, F. M., Family, F. and Family, F. YEAR. Title. - Venue VOL: PAGES.

  * authors     `{vv~}{ll}{, jj}{, f.}` in oikos.bst -> "Surname, F. M.",
                every author listed, ", " between them and " and " before the
                last one (bbl.and; no et al. truncation in the reference list)
  * title       followed by add.emdash -> ".~-- ", i.e. period, en dash, space
  * volume/pages omitted when absent (preprints), per the CSL branch that
    drops the volume/page group when `page` is empty
  * no DOI - neither style file emits one

Author names come from Crossref, which carries structured family/given fields;
OpenAlex only exposes a single display_name that cannot be split reliably.
The section is written directly under the front matter, so it renders below
the title block's Author / Published / Doi fields.

Usage:
    python _tools/add-full-citation.py [--dry-run] [--dir research/working-papers]
"""

import argparse
import json
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
HEADING = "## Full citation"
START = "<!-- full-citation:start -->"
END = "<!-- full-citation:end -->"

# Preprint servers do not populate container-title; resolve them by DOI prefix.
VENUE_BY_PREFIX = {
    "10.1101": "bioRxiv",
    "10.21203": "Research Square",
    "10.22541": "Authorea",
    "10.32942": "EcoEvoRxiv",
    "10.31234": "PsyArXiv",
    "10.5281": "Zenodo",
}


# Records whose depositor mis-split a compound Spanish surname into
# given/family at Crossref. Keyed "given|family" exactly as Crossref holds it.
NAME_FIXES = {
    "Iago Ferreiro|Arias": "Ferreiro Arias, I.",
    "Ana Benitez|Lopez": "Ben\u00edtez-L\u00f3pez, A.",
}


def front_matter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return m.group(1) if m else ""


def field(fm, key):
    m = re.search(rf"^{key}:\s*(.+)$", fm, re.M)
    return m.group(1).strip().strip("\"'") if m else ""


def initials(given):
    """'Lucas P.' -> 'L. P.'   'Jean-Pierre' -> 'J.-P.'   'María' -> 'M.'"""
    out = []
    for token in re.split(r"[\s.]+", given.strip()):
        if not token:
            continue
        parts = [p for p in token.split("-") if p]
        out.append("-".join(p[0].upper() + "." for p in parts))
    return " ".join(out)


def author_string(authors):
    """oikos.bst format.names: all authors, ', ' separated, ' and ' before last."""
    names = []
    for a in authors:
        family = (a.get("family") or a.get("name") or "").strip()
        given = (a.get("given") or "").strip()
        if not family:
            continue
        fixed = NAME_FIXES.get(f"{given}|{family}")
        if fixed:
            names.append(fixed)
        else:
            names.append(f"{family}, {initials(given)}" if given else family)
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def venue(msg, doi):
    prefix = doi.split("/")[0]
    if prefix in VENUE_BY_PREFIX:
        return VENUE_BY_PREFIX[prefix]
    for inst in msg.get("institution") or []:
        if inst.get("name"):
            return inst["name"]
    ct = msg.get("container-title") or []
    if ct:
        return ct[0]
    return msg.get("publisher") or ""


def crossref(doi, email=None):
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"
    if email:
        url += "?mailto=" + urllib.parse.quote(email)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)["message"]


def citation(page, email=None):
    text = page.read_text(encoding="utf-8")
    fm = front_matter(text)
    doi = field(fm, "doi")
    if not doi:
        return None, "no doi in front matter"
    try:
        msg = crossref(doi, email)
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        return None, f"crossref unavailable ({e})"

    authors = author_string(msg.get("author") or [])
    if not authors:
        return None, "no structured authors at crossref"

    # the page's own title is the curated one (Crossref sometimes holds a
    # differently cased or truncated variant)
    title = field(fm, "title").rstrip(".")
    year = field(fm, "date")[:4] or str(
        (msg.get("posted") or msg.get("issued") or {}).get("date-parts", [[""]])[0][0]
    )

    ref = f"{authors} {year}. {title}."
    place = venue(msg, doi)
    if place:
        ref += f" \u2013 {place}"
    vol = (msg.get("volume") or "").strip()
    pages = (msg.get("page") or "").strip().replace("-", "\u2013")
    if pages:
        ref += f" {vol}: {pages}" if vol else f" {pages}"
    return ref.rstrip(".") + ".", None


def insert(text, ref):
    """Put the section immediately after the front matter; replace if present.

    The block is delimited by sentinel comments rather than located by
    "heading up to the next heading": callout titles on these pages used to be
    written as a '## ' heading INSIDE a fenced div, so a heading-to-heading
    span reached past the div's opening fence and deleted it on re-run.
    """
    block = f"{START}\n{HEADING}\n\n{ref}\n{END}\n"
    existing = re.search(
        rf"{re.escape(START)}.*?{re.escape(END)}\n?", text, re.S
    )
    if existing:
        return text[: existing.start()] + block + text[existing.end():]
    # legacy block written before the sentinels existed: heading + one paragraph
    legacy = re.search(
        rf"^{re.escape(HEADING)}\n\n[^\n]+\n\n", text, re.M
    )
    if legacy:
        return text[: legacy.start()] + block + "\n" + text[legacy.end():]
    m = re.match(r"^---\n.*?\n---\n+", text, re.S)
    cut = m.end() if m else 0
    return text[:cut] + block + "\n" + text[cut:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="research/working-papers")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        email = host.get_user_email()  # noqa: F821  (injected in the kernel)
    except Exception:
        email = None

    pages = sorted((ROOT / args.dir).glob("*/index.qmd"))
    written = failed = 0
    for page in pages:
        ref, err = citation(page, email)
        if err:
            print(f"  SKIP {page.parent.name}: {err}")
            failed += 1
            continue
        print(f"  {page.parent.name[:44]:<44} {ref}")
        if not args.dry_run:
            page.write_text(insert(page.read_text(encoding="utf-8"), ref), encoding="utf-8")
        written += 1
    print(f"\npages: {len(pages)} | citation built: {written} | skipped: {failed}"
          f"{' (dry run, nothing written)' if args.dry_run else ''}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
