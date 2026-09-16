#!/usr/bin/env python3
"""Replace the grid tables in projects.qmd with CSS-grid figure/text rows.

The page was exported as pandoc grid tables (+---+---+), one row per project:
figure in the left cell, description in the right. That layout is the root
cause of a recurring class of broken links: a cell is a fixed 39 characters
wide, so the export wrapped long image paths and URLs across cell lines, and
pandoc rejoins cell lines with a space - producing targets like
"static/images/ongf igs/endocarp.jpg" that 404 as %20.

Reference-style links worked around it, but the constraint stays as long as the
tables do. This converts each row to the pattern already used by people.qmd,
datasets.qmd and resources.qmd:

    ::: {.project-row}
    ![](static/images/ongfigs/endocarp.jpg){fig-alt="..."}

    Together with José A. Godoy and Cristina García, we are using ...
    :::

Paths then sit on ordinary lines with no width limit, so they cannot be split
again. Everything outside the tables (headings, intro prose, standalone
figures, rules) is copied through untouched.

Usage:
    python _tools/format-projects.py --dry-run
    python _tools/format-projects.py
"""

import argparse
import pathlib
import re
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "projects.qmd"
BACKUP = ROOT / "_tools" / "projects.qmd.pre-grid-removal"

# escape artifact the export left where it broke a URL
ARTIFACT = re.compile(r"%2%20\s*0?")

# Phrases the export broke mid-word. Successive copies of this page break them
# at DIFFERENT positions ("Scha e fer", "Sc haefer", "Diens t", "Dien st"), so
# matching is whitespace-insensitive: each phrase is matched with optional
# whitespace allowed between every character and restored to the form below.
PHRASES = [
    "H. Martin Schaefer",
    "Laboratório de Biologia da Conservação",
    "anachronic seed dispersal systems",
    "Deutscher Academischer Austausch Dienst",
    "Crataegus monogyna fruits with beak marks",
    "Stacks Image 2344",
]


def _loose(phrase):
    """Pattern matching `phrase` however the export split it."""
    parts = []
    for ch in phrase:
        if ch == " ":
            parts.append(r"\s+")
        else:
            parts.append(re.escape(ch) + r"\s*")
    return re.compile("".join(parts))


LOOSE = [(_loose(p), p) for p in PHRASES]


# alt text that is only an export identifier - dropped, it renders as a caption
EXPORT_ALT = re.compile(r"^(?:stacks\s*image\s*\d+|bullet_pp[\w-]*)$", re.I)


def cell_columns(ruler):
    spans, start = [], None
    for i, ch in enumerate(ruler):
        if ch == "+":
            if start is not None:
                spans.append((start, i))
            start = i + 1
    return spans


def tables(lines):
    i = 0
    while i < len(lines):
        if re.match(r"^\+[-=:]", lines[i]):
            j = i
            while j < len(lines) and (lines[j].startswith("+") or lines[j].startswith("|")):
                j += 1
            yield i, j - 1
            i = j
        else:
            i += 1


def clean(text):
    """Join a cell's lines and undo the damage the table layout caused."""
    out = re.sub(r"\s+", " ", text).strip()
    for pattern, good in LOOSE:
        out = pattern.sub(good, out)

    def target(m):
        inner = ARTIFACT.sub("", m.group(1))
        parts = re.match(r'^(.*?)(\s+["\'].*["\'])?$', inner, re.S)
        url = re.sub(r"\s+", "", parts.group(1))
        title = re.sub(r"\s+", " ", parts.group(2)).rstrip() if parts.group(2) else ""
        return "](" + url + title + ")"

    out = re.sub(r"\]\(([^)]*)\)", target, out)
    out = re.sub(r"\{([^}]*)\}", lambda m: "{" + re.sub(r"\s+", " ", m.group(1)).strip() + "}", out)
    return out


def split_image(cell):
    """(image markdown, leftover text) for a cell, with alt/attrs normalised."""
    m = re.match(r"^\s*!\[([^\]]*)\]\(([^)\s]+)\)\s*(\{[^}]*\}|\{.*)?\s*(.*)$", cell, re.S)
    if not m:
        return None, cell.strip()
    alt, url, attrs, rest = m.group(1), m.group(2), m.group(3) or "", m.group(4) or ""

    # the export truncated one attribute block ('{fig-align="center" width=');
    # keep the complete pairs, drop the fragment - its value is not in the file
    pairs = re.findall(r'[\w-]+="[^"]*"', attrs)
    pairs = [p for p in pairs if not p.startswith(("fig-align=", "alt="))]
    if EXPORT_ALT.match(alt.strip()):
        alt = ""
    keep = ("{" + " ".join(pairs) + "}") if pairs else ""
    return f"![{alt}]({url}){keep}", rest.strip()


def convert(lines):
    out, rows, i = [], 0, 0
    table_bounds = {top: bottom for top, bottom in tables(lines)}
    while i < len(lines):
        if i not in table_bounds:
            out.append(lines[i])
            i += 1
            continue

        bottom = table_bounds[i]
        spans = cell_columns(lines[i])
        rulers = [n for n in range(i, bottom + 1) if lines[n].startswith("+")]
        for a, b in zip(rulers, rulers[1:]):
            cells = []
            for cs, ce in spans:
                cells.append(clean(" ".join(
                    (lines[n][cs:ce] if len(lines[n]) > cs else "").strip()
                    for n in range(a + 1, b))))

            figure, text = None, []
            for c in cells:
                img, rest = split_image(c)
                if img and figure is None:
                    figure = img
                    if rest:
                        text.append(rest)
                elif c:
                    text.append(c)

            body = " ".join(t for t in text if t).strip()
            cls = ".project-row" if figure else ".project-row .nofigure"
            out.append(f"::: {{{cls}}}")
            if figure:
                out.append(figure)
                out.append("")
            out.append(body)
            out.append(":::")
            out.append("")
            rows += 1
        i = bottom + 1
    return out, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    text = SRC.read_text(encoding="utf-8")
    lines = text.split("\n")
    converted, rows = convert(lines)
    result = "\n".join(converted)

    # the Hugo converter must not overwrite this page
    if "hand-edited: true" not in result:
        result = re.sub(r"^---\n", "---\nhand-edited: true\n", result, count=1)

    result = re.sub(r"\n{3,}", "\n\n", result).rstrip("\n") + "\n"

    if not args.dry_run:
        if not BACKUP.exists():
            shutil.copy2(SRC, BACKUP)
        SRC.write_text(result, encoding="utf-8")

    imgs = re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", result)
    missing = [p for p in imgs if not (ROOT / p).exists()]
    split = re.findall(r"!?\[[^\]]*\]\(\s*[^)\"]*?\s+[^)\"]*?\)", result)
    print(f"rows converted: {rows} | images referenced: {len(imgs)} | "
          f"missing on disk: {len(missing)} | targets still containing whitespace: {len(split)}")
    print(f"grid-table lines left: {sum(1 for l in result.split(chr(10)) if l.startswith(('+-', '+:', '|')))}"
          f"{'  (dry run, nothing written)' if args.dry_run else ''}")
    for p in missing:
        print("  MISSING:", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
