#!/usr/bin/env python3
"""Restructure resources.qmd into two-column resource rows.

Same treatment as _tools/format-datasets.py: images are classified by their
real pixel size, large ones become the left-column figure of a

    ::: {.resource-row}
    ![](figure)

    ::: {.resource-text}
    ...
    :::
    :::

and icon-sized ones stay inline with the text. Bullet-icon list items become a
real markdown list; a wide-but-1-line-tall divider GIF is dropped (the row
borders separate entries now). The intro and contact block are kept verbatim.
Run once: `python _tools/format-resources.py`.
"""

import re
import sys
from pathlib import Path

from PIL import Image

SRC = Path("resources.qmd")
LARGE_MIN_WIDTH = 150
LARGE_MIN_HEIGHT = 60          # below this a wide image is a rule, not a figure
IMG = re.compile(r"!\[[^\]]*\]\((static/images/[^)]+)\)")
LINKED_IMG = re.compile(r"\[!\[[^\]]*\]\((static/images/[^)]+)\)\]\(([^)\s]+)[^)]*\)")
BULLET = re.compile(r"!\[bullet_pp[^\]]*\]\([^)]*\)\s*")


def join_lines(lines):
    """Keep the export's line breaks: markdown hard break unless it's a list."""
    if any(l.startswith("- ") for l in lines):
        return "\n".join(lines)
    return "\\\n".join(lines)


def size(path):
    with Image.open(path) as im:
        return im.size


def is_figure(path):
    w, h = size(path)
    return w >= LARGE_MIN_WIDTH and h >= LARGE_MIN_HEIGHT


def is_rule(path):
    w, h = size(path)
    return w >= 200 and h < 24


def alt_text(paragraphs):
    plain = " ".join(paragraphs)
    plain = re.sub(r"!\[[^\]]*\]\([^)]*\)(\{[^}]*\})?(\]\([^)]*\))?", "", plain)
    plain = re.sub(r"\{[^}]*\}", "", plain)
    plain = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", plain)
    plain = re.sub(r"[*_\\#\-\[\]]", " ", plain)
    return " ".join(plain.split())[:70].replace('"', "'")


def emit(figure, link, paragraphs, out):
    text = [p.strip() for p in paragraphs if p.strip()]
    if not text and not figure:
        return 0
    cls = ".resource-row" if figure else ".resource-row .nofigure"
    block = [f"::: {{{cls}}}"]
    if figure:
        img = f'![]({figure}){{fig-alt="{alt_text(text)}"}}'
        block += [f"[{img}]({link})" if link else img, ""]
    block += ["::: {.resource-text}", "\n\n".join(text), ":::", ":::", ""]
    out.append("\n".join(block))
    return 1


def main():
    if not SRC.exists():
        sys.exit(f"{SRC} not found; run from the site root.")
    raw = SRC.read_text(encoding="utf-8")
    front, _, body = raw.partition("---\n")[2].partition("\n---\n")
    out = ["---\n" + front + "\n---\n"]

    intro, started = [], False
    figure, link, paras, current, rows = None, None, [], [], 0

    for line in body.split("\n"):
        line = line.rstrip()
        if line.strip() in {"---", "####"}:
            continue
        if not line:                              # paragraph break
            if current:
                paras.append(join_lines(current))
                current = []
            continue

        # a figure (optionally wrapped in a link) starts a new row
        lm = LINKED_IMG.match(line.strip())
        pm = IMG.match(line.strip())
        src = lm.group(1) if lm else (pm.group(1) if pm else None)
        if src and is_figure(src):
            if current:
                paras.append(join_lines(current))
                current = []
            if not started:
                intro, paras = paras, []
                started = True
            else:
                rows += emit(figure, link, paras, out)
                paras = []
            figure, link = src, (lm.group(2) if lm else None)
            rest = (line.strip()[lm.end():] if lm else line.strip()[pm.end():]).strip()
            if rest:
                current.append(rest)
            continue

        if src and is_rule(src):                  # decorative divider GIF
            continue

        if BULLET.search(line):                   # tutorial list item
            line = "- " + BULLET.sub("", line).strip()

        for m in list(LINKED_IMG.finditer(line)) + list(IMG.finditer(line)):
            if not is_figure(m.group(1)) and ".inline-icon" not in line:
                line = IMG.sub(lambda mm: f"![]({mm.group(1)}){{.inline-icon}}"
                               if not is_figure(mm.group(1)) else mm.group(0), line)
                break

        current.append(line)

    if current:
        paras.append(join_lines(current))
    rows += emit(figure, link, paras, out)

    out.insert(1, "\n\n".join(p.strip() for p in intro if p.strip()) + "\n")
    SRC.write_text("\n".join(out), encoding="utf-8")
    print(f"Rewrote {SRC}: {rows} resource entries")


if __name__ == "__main__":
    main()