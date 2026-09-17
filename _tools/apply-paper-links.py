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

    links = {norm_doi(str(k)): v for k, v in
             (yaml.safe_load(SIDECAR.read_text(encoding="utf-8")) or {}).items()
             if isinstance(v, dict)}
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
        if re.search(r"^## Links$", text, re.M):
            # append to the existing pipe-separated link line
            def add(match):
                return match.group(0).rstrip() + " | " + " | ".join(parts)
            text = re.sub(r"(?<=^## Links\n\n).*$", add,
                          text, count=1, flags=re.M)
        else:
            text = text.rstrip("\n") + "\n\n## Links\n\n" + " | ".join(parts) + "\n"
        if not args.dry_run:
            qmd.write_text(text, encoding="utf-8")
        patched += 1
        print(f"  + {qmd.relative_to(ROOT).parent.name[:60]}: {', '.join(parts)}")

    verb = "would patch" if args.dry_run else "patched"
    print(f"{verb} {patched}, already current {unchanged}, no page {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
