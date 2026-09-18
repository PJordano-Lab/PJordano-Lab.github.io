#!/usr/bin/env python3
"""Apply data/paper_links.yml to the existing publication pages, in place.

`open-alex.py` writes these links whenever it regenerates the article pages,
but a full sync needs network access and an OpenAlex key. After editing
data/paper_links.yml, this script patches the pages that already exist so the
links appear on the next render.

Idempotent: running it twice changes nothing, and the output matches what
open-alex.py would generate, so the next sync produces no diff.

Usage:
    python _tools/apply-paper-links.py
    python _tools/apply-paper-links.py --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SIDECAR = ROOT / "data" / "paper_links.yml"
PAGE_GLOBS = ("research/articles/*/index.qmd", "research/working-papers/*/index.qmd")


def norm_doi(value: str) -> str:
    v = (value or "").strip().lower()
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", v).strip()


def link_parts(entry: dict) -> list[str]:
    """The Code/Data/extra markdown links for one paper (same order as open-alex.py)."""
    parts = []
    code, data = entry.get("code"), entry.get("data")
    if code and code == data:
        parts.append(f"[Code & data]({code})")
    else:
        if code:
            parts.append(f"[Code]({code})")
        if data:
            parts.append(f"[Data]({data})")
    for item in entry.get("extra") or []:
        if isinstance(item, dict) and item.get("url"):
            parts.append(f"[{item.get('label', 'Link')}]({item['url']})")
    return parts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report without writing")
    args = ap.parse_args()

    try:
        data = yaml.safe_load(SIDECAR.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        # Nearly always a hand-editing slip: a DOI key without its trailing
        # colon, or inconsistent indentation. Point at the line and stop.
        print(f"{SIDECAR.relative_to(ROOT)} is not valid YAML:\n  {exc}",
              file=sys.stderr)
        mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
        if mark is not None:
            lines = SIDECAR.read_text(encoding="utf-8").splitlines()
            for n in range(max(0, mark.line - 2), min(len(lines), mark.line + 2)):
                flag = ">>" if n == mark.line else "  "
                print(f"  {flag} {n + 1:4}| {lines[n]}", file=sys.stderr)
            print("\n  Each paper must be a quoted DOI followed by a colon, e.g.\n"
                  '    "10.1002/ecy.4424":\n'
                  "      code: https://github.com/...", file=sys.stderr)
        return 1
    if not isinstance(data, dict):
        print(f"{SIDECAR.relative_to(ROOT)} should be a mapping of DOI -> links",
              file=sys.stderr)
        return 1

    links = {norm_doi(str(k)): v for k, v in data.items() if isinstance(v, dict)}
    skipped = [k for k, v in data.items() if not isinstance(v, dict)]
    if skipped:
        print(f"  ! ignoring {len(skipped)} malformed entr(ies): {skipped[:3]}")
    if not links:
        print(f"No entries in {SIDECAR.relative_to(ROOT)}; nothing to do.")
        return 0

    pages = {}
    for pattern in PAGE_GLOBS:
        for qmd in ROOT.glob(pattern):
            m = re.search(r"^doi:\s*(\S+)", qmd.read_text(encoding="utf-8"), re.M)
            if m:
                pages[norm_doi(m.group(1))] = qmd

    patched = unchanged = missing = 0
    for doi, entry in sorted(links.items()):
        qmd = pages.get(doi)
        if qmd is None:
            print(f"  ? no page found for {doi}")
            missing += 1
            continue
        text = qmd.read_text(encoding="utf-8")
        parts = [p for p in link_parts(entry) if p not in text]
        if not parts:
            unchanged += 1
            continue
        block = "\n".join(parts)
        if re.search(r"^::: \{\.paper-links\}$", text, re.M):
            # append inside the existing .paper-links div, one link per line
            text = re.sub(r"(?ms)(^::: \{\.paper-links\}\n.*?)(^:::$)",
                          lambda m: m.group(1) + block + "\n" + m.group(2),
                          text, count=1)
        elif re.search(r"^## Links$", text, re.M):
            # legacy pipe-separated line: append to it (run
            # _tools/linkify-paper-links.py to convert the page to buttons)
            def add(match):
                return match.group(0).rstrip() + " | " + " | ".join(parts)
            text = re.sub(r"(?<=^## Links\n\n).*$", add,
                          text, count=1, flags=re.M)
        else:
            text = (text.rstrip("\n") + "\n\n## Links\n\n::: {.paper-links}\n"
                    + block + "\n:::\n")
        if not args.dry_run:
            qmd.write_text(text, encoding="utf-8")
        patched += 1
        print(f"  + {qmd.relative_to(ROOT).parent.name[:60]}: {', '.join(parts)}")

    verb = "would patch" if args.dry_run else "patched"
    print(f"{verb} {patched}, already current {unchanged}, no page {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
