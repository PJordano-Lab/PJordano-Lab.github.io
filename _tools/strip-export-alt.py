#!/usr/bin/env python3
"""Remove RapidWeaver export identifiers used as image alt text / captions.

The export wrote alt text like "Stacks Image 2322", which Quarto renders as a
visible figcaption under the figure. They describe nothing, so the alt text is
emptied (the image, its path and its attributes are untouched).

Two shapes have to be handled, because the export wrapped both:

  plain      ![Stacks Image\\n2322](path){fig-align="center"}
  table cell | ![Stacks Image                        |
             | 2297][proj-03]{fig-align="center"}    |

Grid-table cells are rewritten in place, preserving the column width so the
+---+---+ rulers still line up.

Usage:
    python _tools/strip-export-alt.py projects.qmd --dry-run
    python _tools/strip-export-alt.py projects.qmd
"""

import argparse
import importlib.util
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
# identifiers the export used as alt text: "Stacks Image 2322", "bullet_pp_2"
EXPORT_ALT = re.compile(r"^(?:stacks\s*image\s*\d+|bullet_pp[\w-]*)$", re.I)


def helpers():
    """Reuse the grid-table walkers from the sibling repair script."""
    spec = importlib.util.spec_from_file_location(
        "fx", ROOT / "_tools" / "fix-grid-table-images.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pages", nargs="*", default=["projects.qmd"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    fx = helpers()
    total = 0

    for name in args.pages:
        path = ROOT / name
        lines = path.read_text(encoding="utf-8").split("\n")
        stripped = []

        # 1. grid-table cells
        for top, bottom in fx.tables(lines):
            spans = fx.cell_columns(lines[top])
            if not spans:
                continue
            bounds = [n for n in range(top, bottom + 1) if lines[n].startswith("+")]
            for a, b in zip(bounds, bounds[1:]):
                body = list(range(a + 1, b))
                for (cs, ce) in spans:
                    cell = [lines[n][cs:ce] if len(lines[n]) > cs else "" for n in body]
                    joined = " ".join(c.strip() for c in cell).strip()
                    m = re.match(r"^!\[([^\]]*)\]([\[(][^\])]*[\])])(\{[^}]*\})?\s*$",
                                 re.sub(r"\s+", " ", joined))
                    if not m or not EXPORT_ALT.match(m.group(1).strip()):
                        continue
                    repl = f"![]{m.group(2)}{m.group(3) or ''}"
                    width = ce - cs
                    for k, n in enumerate(body):
                        line = lines[n].ljust(max(len(lines[n]), ce))
                        piece = repl if k == 0 else ""
                        lines[n] = line[:cs] + (" " + piece).ljust(width)[:width] + line[ce:]
                    stripped.append(m.group(1).strip())

        text = "\n".join(lines)

        # 2. plain images, alt text possibly wrapped across lines
        def plain(m):
            alt = re.sub(r"\s+", " ", m.group(1)).strip()
            if not EXPORT_ALT.match(alt):
                return m.group(0)
            stripped.append(alt)
            return f"![]({m.group(2)}){m.group(3) or ''}"

        text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)(\{[^}]*\})?", plain, text, flags=re.S)

        # An explicit alt= attribute overrides the (now empty) markdown alt, so
        # export identifiers have to be dropped there as well.
        def attr(m):
            value = m.group(1)
            if not EXPORT_ALT.match(value.strip()):
                return m.group(0)
            stripped.append(value.strip())
            return ""

        text = re.sub(r'\s*alt="([^"]*)"', attr, text)
        text = re.sub(r"\{\s*\}", "", text)          # attribute block left empty

        if not args.dry_run:
            path.write_text(text, encoding="utf-8")
        print(f"{name}: {len(stripped)} export alt texts removed"
              f"{' (dry run)' if args.dry_run else ''}")
        for s in sorted(set(stripped))[:6]:
            print(f"    {s}")
        total += len(stripped)

    print(f"\ntotal: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
