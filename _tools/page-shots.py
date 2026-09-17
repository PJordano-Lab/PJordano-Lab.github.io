#!/usr/bin/env python3
"""Screenshot and measure rendered pages of the built site.

Run this on your own machine (not in an agent sandbox, where browser binaries
cannot be executed). It writes, for every page listed:

  _screenshots/<page>-light.png   full-page screenshot
  _screenshots/<page>-dark.png    same page with the dark theme forced
  _screenshots/measurements.json  measured vertical gaps, in CSS pixels

The measurements are the numbers that are otherwise guesswork: the gap between
the navbar and the first content element, and between the last content element
and the footer.

Setup (once):
    pip install playwright && playwright install chromium

Usage:
    python _tools/page-shots.py                     # default page set
    python _tools/page-shots.py blog.html research.html
    python _tools/page-shots.py --width 1400 --no-dark
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OUT = ROOT / "_screenshots"

# One page per layout shape on this site.
DEFAULT_PAGES = [
    "index.html",                      # hero + banner + listing
    "research.html",                   # table listing
    "blog.html",                       # default listing with pagination
    "media.html",                      # prose ending in a rule
    "blog/posts/geno/index.html",      # mirrored WordPress post
]

# Measured in the page: navbar -> first content, last content -> footer.
MEASURE_JS = """
() => {
  const px = v => Math.round(v * 10) / 10;
  const main = document.querySelector('main.content');
  const footer = document.querySelector('footer.footer, .nav-footer');
  const nav = document.querySelector('.navbar, #quarto-header');
  const kids = main ? [...main.children].filter(
      el => !['SCRIPT', 'STYLE'].includes(el.tagName)
             && el.getBoundingClientRect().height > 0) : [];
  const first = kids[0], last = kids[kids.length - 1];
  const r = el => el.getBoundingClientRect();
  return {
    page_height: px(document.documentElement.scrollHeight),
    theme: document.documentElement.getAttribute('data-theme'),
    top_gap: (nav && first) ? px(r(first).top - r(nav).bottom) : null,
    bottom_gap: (last && footer) ? px(r(footer).top - r(last).bottom) : null,
    first_element: first ? first.tagName.toLowerCase() + '.' +
        (first.className || '').split(' ')[0] : null,
    last_element: last ? last.tagName.toLowerCase() + '.' +
        (last.className || '').split(' ')[0] : null,
    footer_padding_top: footer
        ? px(parseFloat(getComputedStyle(footer).paddingTop)) : null,
  };
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pages", nargs="*", default=None,
                    help="paths under docs/ (default: one page per layout shape)")
    ap.add_argument("--width", type=int, default=1200, help="viewport width in px")
    ap.add_argument("--no-dark", action="store_true", help="skip the dark-theme pass")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed. Run:\n"
              "    pip install playwright && playwright install chromium",
              file=sys.stderr)
        return 1

    pages = args.pages or DEFAULT_PAGES
    missing = [p for p in pages if not (DOCS / p).exists()]
    if missing:
        print(f"Not found under docs/ (render the site first): {missing}", file=sys.stderr)
        return 1

    OUT.mkdir(exist_ok=True)
    results = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for rel in pages:
            slug = rel.replace("/index.html", "").replace("/", "-").replace(".html", "")
            for theme in (["light"] if args.no_dark else ["light", "dark"]):
                page = browser.new_page(viewport={"width": args.width, "height": 1000})
                # The site stores an explicit choice in localStorage and otherwise
                # follows prefers-color-scheme; set both so the pass is deterministic.
                page.add_init_script(
                    f"try {{ localStorage.setItem('theme', '{theme}'); }} catch (e) {{}}")
                page.emulate_media(color_scheme=theme)
                page.goto((DOCS / rel).as_uri(), wait_until="load")
                page.wait_for_timeout(400)
                shot = OUT / f"{slug}-{theme}.png"
                page.screenshot(path=str(shot), full_page=True)
                results.setdefault(rel, {})[theme] = page.evaluate(MEASURE_JS)
                page.close()
                print(f"  {shot.relative_to(ROOT)}")
        browser.close()

    (OUT / "measurements.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8")

    print("\ngaps in CSS pixels (navbar -> content, content -> footer):")
    for rel, per_theme in results.items():
        m = per_theme.get("light") or next(iter(per_theme.values()))
        print(f"  {rel:32} top={m['top_gap']:>6}  bottom={m['bottom_gap']:>6}"
              f"   last=<{m['last_element']}>")
    print(f"\n{(OUT / 'measurements.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
