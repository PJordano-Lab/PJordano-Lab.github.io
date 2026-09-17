#!/usr/bin/env python3
"""Propose code/data links for publication pages, for review before use.

Your OpenAlex records already contain the deposits: Zenodo archives, figshare
appendices, R packages. They currently appear as separate rows in
data/publications.csv rather than as links on the paper they belong to. This
script pairs each deposit with its parent paper and writes two files:

  data/paper_links.proposed.yml  - ready to review, then merge into
                                   data/paper_links.yml (read by open-alex.py)
  data/paper_links_review.csv    - one row per deposit, including the ones that
                                   could NOT be paired, with the evidence

Nothing is written to data/paper_links.yml: that file stays hand-curated.

Two sources of evidence, in order of trust:

  1. DataCite relation metadata (IsSupplementTo / IsPartOf / ...). Registered
     by the repository, so it is authoritative - this is what resolves the
     "Appendix A/B/C" figshare items, whose titles never name the paper.
  2. Title matching, after stripping the boilerplate that repositories add
     ("Data from:", "Code and data to reproduce the analyses in", filename-style
     titles like Ecol-Lett_Fuzessy-et-al-2021_...). Reported with a similarity
     score so low-confidence guesses are visible.

Usage:
    python _tools/propose-paper-links.py
    python _tools/propose-paper-links.py --min-score 0.75   # stricter matching
    python _tools/propose-paper-links.py --no-datacite      # offline, titles only
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBS_CSV = ROOT / "data" / "publications.csv"
PROPOSED = ROOT / "data" / "paper_links.proposed.yml"
REVIEW_CSV = ROOT / "data" / "paper_links_review.csv"
CACHE = ROOT / "data" / ".datacite_cache.json"

# Record types that are deposits rather than papers.
DEPOSIT_TYPES = {"dataset", "software", "supplementary-material",
                 "supplementary-materials"}
# Repository hosts whose records are deposits whatever OpenAlex calls them.
DEPOSIT_DOI_PREFIXES = ("10.5281/",      # Zenodo
                        "10.6084/",      # figshare
                        "10.5061/",      # Dryad
                        "10.15468/")     # GBIF

# Relations that point from a deposit to the paper it belongs to.
PARENT_RELATIONS = {"issupplementto", "ispartof", "isdocumentedby",
                    "isdescribedby", "iscitedby", "isreferencedby",
                    "issourceof", "iscompiledby"}

# Boilerplate repositories prepend to a deposit title.
TITLE_PREFIXES = [
    r"^data\s+from[:\s]+", r"^dataset[:\s]+", r"^data\s+for[:\s]+",
    r"^code\s+and\s+dataset\s+from[:\s]+", r"^code\s+and\s+data\s+from[:\s]+",
    r"^code\s+and\s+data\s+to\s+reproduce\s+the\s+analyses\s+in[:\s]+",
    r"^code\s+to\s+reproduce[^:]*[:\s]+",
    r"^supplementary\s+material\s+from[:\s]+",
    r"^supplemental(?:ary)?\s+(?:information|materials?)[^:]*(?:for\s+the\s+ms)?[:\s]+",
    r"^appendix\s+[a-z][:.\s]+", r"^supplement\s+\d+[:.\s]+",
    r"^replication\s+(?:data|package)\s+for[:\s]+",
]

# Word-boundary patterns, not substrings: "Appendix A. Species codes and
# identities" is a data table, not source code.
CODE_RE = re.compile(r"\b(code|codes|scripts?|notebooks?|matlab|software|"
                     r"r\s*package|package)\b")
CODE_FALSE_POSITIVE_RE = re.compile(r"\b(species|taxon|taxa|identit\w*|sample|"
                                    r"site|plot|colour|color)\s+codes?\b")
DATA_RE = re.compile(r"\b(data|dataset|datasets|appendix|appendices|"
                     r"supplement\w*|table s?\d+)\b")

# Preference when several deposits pair to the same paper and kind: a figshare
# collection ("figshare.c.NNN") covers a whole supplement set, and a deposit
# whose title names both code and data beats a single appendix file.
def deposit_rank(title: str, doi: str) -> tuple:
    t = (title or "").lower()
    return (
        0 if "figshare.c." in doi else 1,
        0 if (CODE_RE.search(t) and DATA_RE.search(t)) else 1,
        0 if not re.match(r"^(appendix|supplement)\b", t) else 1,
        title or "",
    )


# --------------------------------------------------------------------------- #
def norm_doi(value: str) -> str:
    """Bare lowercase DOI from a DOI or a doi.org URL."""
    v = (value or "").strip().lower()
    v = re.sub(r"^https?://(dx\.)?doi\.org/", "", v)
    return v.strip()


def norm_title(title: str) -> str:
    """Comparable form of a title: boilerplate stripped, punctuation flattened."""
    t = (title or "").lower()
    t = t.replace("\u2013", "-").replace("\u2014", "-").replace("\u2019", "'")
    for pat in TITLE_PREFIXES:
        t = re.sub(pat, "", t, count=1)
    # filename-style titles: Ecol-Lett_Fuzessy-et-al-2021_Phylogenetic_congruence
    t = t.replace("_", " ")
    t = re.sub(r"\bet al\b\.?", " ", t)
    t = re.sub(r"\b(19|20)\d{2}\b", " ", t)          # years
    t = re.sub(r"\bv?\d+(\.\d+)+\b", " ", t)          # version numbers
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def classify(title: str, rec_type: str) -> list[str]:
    """Which link kinds a deposit provides: ['code'], ['data'], or both."""
    t = (title or "").lower()
    is_code = rec_type == "software" or bool(
        CODE_RE.search(t) and not CODE_FALSE_POSITIVE_RE.search(t))
    is_data = bool(DATA_RE.search(t)) or rec_type in {
        "dataset", "supplementary-material", "supplementary-materials"}
    if rec_type == "software" and not re.search(r"\bdata(set)?s?\b", t):
        is_data = False          # an R package release is code, not data
    kinds = (["code"] if is_code else []) + (["data"] if is_data else [])
    return kinds or ["data"]


# --------------------------------------------------------------------------- #
def load_cache() -> dict:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def datacite_relations(doi: str, cache: dict) -> list[tuple[str, str]]:
    """[(relationType, relatedDOI)] for a deposit DOI, via DataCite."""
    key = norm_doi(doi)
    if key in cache:
        return [tuple(x) for x in cache[key]]
    url = "https://api.datacite.org/dois/" + urllib.parse.quote(key, safe="")
    req = urllib.request.Request(
        url, headers={"User-Agent": "pjordano-lab-paper-links",
                      "Accept": "application/vnd.api+json"})
    rels: list[tuple[str, str]] = []
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            attrs = json.load(r)["data"]["attributes"]
        for item in attrs.get("relatedIdentifiers") or []:
            if (item.get("relatedIdentifierType") or "").upper() == "DOI":
                rels.append(((item.get("relationType") or ""),
                             norm_doi(item.get("relatedIdentifier") or "")))
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, ValueError) as exc:
        print(f"    ! DataCite lookup failed for {key}: {exc}", file=sys.stderr)
        return []
    cache[key] = [list(x) for x in rels]
    time.sleep(0.2)          # courtesy rate limit
    return rels


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-score", type=float, default=0.62,
                    help="minimum title similarity to propose a pairing (0-1)")
    ap.add_argument("--no-datacite", action="store_true",
                    help="skip DataCite lookups; use title matching only")
    args = ap.parse_args()

    rows = list(csv.DictReader(PUBS_CSV.open(encoding="utf-8")))
    papers, deposits = [], []
    for r in rows:
        doi = norm_doi(r.get("doi", ""))
        is_deposit = (r.get("type") in DEPOSIT_TYPES
                      or doi.startswith(DEPOSIT_DOI_PREFIXES))
        (deposits if is_deposit else papers).append(r)

    by_doi = {norm_doi(p.get("doi", "")): p for p in papers if norm_doi(p.get("doi", ""))}
    paper_titles = [(norm_title(p.get("title", "")), p) for p in papers]
    print(f"{len(papers)} papers, {len(deposits)} deposits")

    cache = load_cache()
    proposals: dict[str, dict] = {}
    review: list[dict] = []

    for dep in deposits:
        dep_doi = norm_doi(dep.get("doi", ""))
        dep_title = dep.get("title", "")
        parent = None
        method = ""
        score = ""

        if not args.no_datacite and dep_doi:
            for rel, target in datacite_relations(dep_doi, cache):
                if rel.lower() in PARENT_RELATIONS and target in by_doi:
                    parent, method, score = by_doi[target], f"datacite:{rel}", "1.00"
                    break

        if parent is None:
            needle = norm_title(dep_title)
            best, best_ratio = None, 0.0
            if needle:
                for cand_title, cand in paper_titles:
                    if not cand_title:
                        continue
                    ratio = difflib.SequenceMatcher(None, needle, cand_title).ratio()
                    # a deposit title that contains the paper title outright
                    if cand_title and cand_title in needle:
                        ratio = max(ratio, 0.95)
                    if ratio > best_ratio:
                        best, best_ratio = cand, ratio
            if best is not None and best_ratio >= args.min_score:
                parent, method, score = best, "title", f"{best_ratio:.2f}"
            elif best is not None:
                method, score = f"title (below threshold)", f"{best_ratio:.2f}"

        dep_url = dep.get("doi_url") or (f"https://doi.org/{dep_doi}" if dep_doi else "")
        kinds = classify(dep_title, dep.get("type", ""))

        review.append({
            "deposit_title": dep_title,
            "deposit_type": dep.get("type", ""),
            "deposit_doi": dep_doi,
            "deposit_url": dep_url,
            "kinds": "+".join(kinds),
            "match_method": method,
            "match_score": score,
            "parent_doi": norm_doi(parent.get("doi", "")) if parent else "",
            "parent_title": parent.get("title", "") if parent else "",
            "parent_year": parent.get("year", "") if parent else "",
        })

        if parent is None:
            continue
        pdoi = norm_doi(parent.get("doi", ""))
        entry = proposals.setdefault(pdoi, {"title": parent.get("title", ""),
                                            "candidates": {}, "evidence": []})
        for kind in kinds:
            entry["candidates"].setdefault(kind, []).append((dep_title, dep_url))
        entry["evidence"].append(f"{method} {score} [{'+'.join(kinds)}] <- {dep_title[:80]}")

    CACHE.write_text(json.dumps(cache, indent=0) + "\n", encoding="utf-8")

    # ---- proposal file (hand-written YAML so each entry carries its evidence)
    out = ["# PROPOSED code/data links - review, edit, then merge the entries you",
           "# accept into data/paper_links.yml (open-alex.py reads that file only).",
           "# Regenerate with: python _tools/propose-paper-links.py",
           "#",
           "# Each entry is keyed by the PARENT PAPER's DOI. Comments record how the",
           "# pairing was found: datacite:<relation> is registered metadata (reliable);",
           "# title <score> is a similarity match (check these).",
           ""]
    for pdoi in sorted(proposals, key=lambda d: proposals[d]["title"].lower()):
        e = proposals[pdoi]
        out.append(f'# {e["title"]}')
        for ev in e["evidence"]:
            out.append(f"#   {ev}")
        out.append(f'"{pdoi}":')
        for kind in ("code", "data"):
            cands = e["candidates"].get(kind)
            if not cands:
                continue
            cands = sorted(cands, key=lambda c: deposit_rank(c[0], c[1]))
            out.append(f"  {kind}: {cands[0][1]}")
            if len(cands) > 1:
                out.append(f"  # {len(cands)} deposits matched this paper as "
                           f"{kind}; the one above was picked. Others:")
                for title, url in cands[1:]:
                    out.append(f"  #   {url}  {title[:70]}")
        out.append("")
    PROPOSED.write_text("\n".join(out), encoding="utf-8")

    with REVIEW_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(review[0].keys()))
        w.writeheader()
        w.writerows(sorted(review, key=lambda r: (r["match_method"] == "",
                                                  r["match_method"], r["deposit_title"])))

    paired = sum(1 for r in review if r["parent_doi"])
    by_method: dict[str, int] = {}
    for r in review:
        if r["parent_doi"]:
            key = r["match_method"].split(":")[0]
            by_method[key] = by_method.get(key, 0) + 1
    print(f"paired {paired}/{len(deposits)} deposits onto {len(proposals)} papers "
          f"({', '.join(f'{k}={v}' for k, v in sorted(by_method.items())) or 'none'})")
    print(f"  {PROPOSED.relative_to(ROOT)}")
    print(f"  {REVIEW_CSV.relative_to(ROOT)}  ({len(deposits) - paired} unpaired to check)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
