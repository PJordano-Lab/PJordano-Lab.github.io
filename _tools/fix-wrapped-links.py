#!/usr/bin/env python3
"""Repair hyperlinks that the export mangled inside grid-table cells.

Two faults, both visible in projects.qmd:

1. The URL was broken across cell lines AND an escape artifact was injected at
   the break point:

       | ](http://www.biologie.uni-freibu%2%20 |
       | 0rg.de/data/bio1/schaefer/index.html) |

   Pandoc rejoins cell lines with a space, so the href becomes
   "...uni-freibu%2%20 0rg.de/..." - the %2%20%200 the preview reports. Deleting
   the artifact and the whitespace restores "uni-freiburg.de".

2. The visible link text was broken mid-word ("Scha e fer", "C onservação").
   That cannot be inferred mechanically - a line break between two words and a
   break inside one word look identical after the fact - so the few affected
   strings are corrected from an explicit table below.

Repaired URLs become reference-style links, because a restored URL is far
longer than the 39-character cell and an inline target must not wrap.

Usage:
    python _tools/fix-wrapped-links.py projects.qmd --dry-run
    python _tools/fix-wrapped-links.py projects.qmd
"""

import argparse
import importlib.util
import pathlib
import re
import sys
import textwrap

ROOT = pathlib.Path(__file__).resolve().parent.parent
START = "<!-- image-refs:start -->"
END = "<!-- image-refs:end -->"

# Link text the export broke mid-word. Left side is what the cell rejoins to,
# right side is the correct reading.
TEXT_FIXES = {
    "H. Martin Scha e fer": "H. Martin Schaefer",
    "Laboratório de Biologia da C onservação": "Laboratório de Biologia da Conservação",
    "anachronic seed dispersal syste ms": "anachronic seed dispersal systems",
    "Deutscher Academischer Austausch Diens t": "Deutscher Academischer Austausch Dienst",
}

# the escape artifact the export left at a URL break point
ARTIFACT = re.compile(r"%2%20\s*0?")


def helpers():
    spec = importlib.util.spec_from_file_location(
        "fx", ROOT / "_tools" / "fix-grid-table-images.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def repair_text(cell):
    """Fix URLs and known mid-word text breaks in one cell's joined text."""
    text = re.sub(r"\s+", " ", cell).strip()
    for bad, good in TEXT_FIXES.items():
        text = text.replace(bad, good)

    def target(m):
        # a target may carry a quoted title: ](url "Some title"). Only the URL
        # loses its whitespace - stripping the title would weld its words.
        inner = ARTIFACT.sub("", m.group(1))
        parts = re.match(r'^(.*?)(\s+["\'].*["\'])?$', inner, re.S)
        url = re.sub(r"\s+", "", parts.group(1))
        title = re.sub(r"\s+", " ", parts.group(2)).rstrip() if parts.group(2) else ""
        return "](" + url + title + ")"

    return re.sub(r"\]\(([^)]*)\)", target, text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("page", nargs="?", default="projects.qmd")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    fx = helpers()
    path = ROOT / args.page
    raw = path.read_text(encoding="utf-8")
    lines = raw.split("\n")

    block = re.search(re.escape(START) + r"(.*?)" + re.escape(END), raw, re.S)
    existing = re.findall(r"^\[([^\]]+)\]:\s*(\S+(?:\s+\"[^\"]*\")?)\s*$",
                          block.group(1), re.M) if block else []
    refs = list(existing)
    by_target = {t: l for l, t in existing}
    next_n = 1 + max((int(m.group(1)) for l, _ in existing
                      if (m := re.match(r"link-(\d+)$", l))), default=0)

    fixed, report = 0, []
    for top, bottom in fx.tables(lines):
        spans = fx.cell_columns(lines[top])
        if not spans:
            continue
        bounds = [n for n in range(top, bottom + 1) if lines[n].startswith("+")]
        for a, b in zip(bounds, bounds[1:]):
            body = list(range(a + 1, b))
            for (cs, ce) in spans:
                cell = [lines[n][cs:ce] if len(lines[n]) > cs else "" for n in body]
                joined = " ".join(c.strip() for c in cell)
                if "![" in joined:
                    continue          # images belong to fix-grid-table-images.py
                if not ARTIFACT.search(joined) and not re.search(r"\]\([^)]*\s[^)]*\)", joined):
                    continue
                text = repair_text(joined)
                width = ce - cs

                # long targets move to the definition block
                def to_ref(m):
                    nonlocal next_n
                    label, url = m.group(1), m.group(2)
                    if len(url) <= width - 12:
                        return m.group(0)
                    lab = by_target.get(url)
                    if lab is None:
                        lab = f"link-{next_n:02d}"
                        next_n += 1
                        by_target[url] = lab
                        refs.append((lab, url))
                        report.append((lab, url))
                    return f"[{label}][{lab}]"

                text = re.sub(r"(?<!\!)\[([^\]]*)\]\(([^)\s\"]+)\)", to_ref, text)

                # A link carrying a title cannot survive in a cell either: the
                # title lands on the next line and pandoc folds it into the
                # href ('gallery.html "Megafauna fruits"' -> a 404). Reference
                # definitions hold a title safely, so move the whole target.
                def titled_to_ref(m):
                    nonlocal next_n
                    label, url, title = m.group(1), m.group(2).strip(), m.group(3)
                    target_str = f'{url} "{title}"'
                    lab = by_target.get(target_str)
                    if lab is None:
                        lab = f"link-{next_n:02d}"
                        next_n += 1
                        by_target[target_str] = lab
                        refs.append((lab, target_str))
                        report.append((lab, target_str))
                    return f"[{label}][{lab}]"

                text = re.sub(r'(?<!\!)\[([^\]]*)\]\(([^)"]+)"([^"]*)"\)',
                              titled_to_ref, text)

                wrapped = textwrap.wrap(text, width=width - 1,
                                        break_on_hyphens=False,
                                        break_long_words=False)
                if len(wrapped) > len(body):
                    print(f"  SKIPPED a cell: needs {len(wrapped)} lines, has {len(body)}")
                    continue
                too_wide = [w for w in wrapped if len(w) + 1 > width]
                if too_wide:
                    print(f"  SKIPPED a cell: {len(too_wide[0]) + 1} chars will not fit "
                          f"in {width}; left untouched")
                    continue
                for k, n in enumerate(body):
                    line = lines[n].ljust(max(len(lines[n]), ce))
                    piece = wrapped[k] if k < len(wrapped) else ""
                    lines[n] = line[:cs] + (" " + piece).ljust(width)[:width] + line[ce:]
                fixed += 1

    text = "\n".join(lines)
    if refs:
        new_block = (START + "\n" + "\n".join(f"[{l}]: {t}" for l, t in refs) + "\n" + END + "\n")
        old = re.search(re.escape(START) + r".*?" + re.escape(END) + r"\n?", text, re.S)
        text = (text[: old.start()] + new_block + text[old.end():]) if old else text + "\n" + new_block

    if not args.dry_run:
        path.write_text(text, encoding="utf-8")
    for lab, url in report:
        print(f"  [{lab}] -> {url}")
    print(f"\ncells repaired: {fixed} | new link definitions: {len(report)}"
          f"{' (dry run, nothing written)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
