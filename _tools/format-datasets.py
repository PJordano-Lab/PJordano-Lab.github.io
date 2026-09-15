#!/usr/bin/env python3
"""Restructure datasets.qmd into two-column dataset rows.

In the Hugo export every entry is a loose run of lines: a figure, one or more
icon-sized badges, a bullet icon, then the description. This rewrites each
entry as

    ::: {.dataset-row}
    ![](figure)

    ::: {.dataset-text}
    ![](badge){.inline-icon} Description...
    :::
    :::

Images are classified by their real pixel width: anything at least
LARGE_MIN_WIDTH px wide becomes the left-column figure, smaller ones stay
inline with the text. Run once: `python _tools/format-datasets.py`.
"""

import re
import sys
from pathlib import Path

from PIL import Image

SRC = Path("datasets.qmd")
LARGE_MIN_WIDTH = 150
IMG = re.compile(r"^!\[[^\]]*\]\((static/images/[^)]+)\)\s*$")
INLINE_IMG = re.compile(r"!\[[^\]]*\]\((static/images/[^)]+)\)")
BULLET = re.compile(r"!\[bullet_pp[^\]]*\]\([^)]*\)\s*")


def width(path):
    with Image.open(path) as im:
        return im.size[0]


def alt_text(body):
    """A short alt string taken from the start of the entry's description."""
    plain = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)
    plain = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", plain)
    plain = re.sub(r"[*_\\]", "", plain).strip()
    plain = re.split(r"(?<=[a-z])\.\s", plain)[0]
    return plain[:70].strip().replace('"', "'")


def emit(figure, icons, text, out):
    body = " ".join(t.strip() for t in text).strip()
    if not body and not figure:
        return 0
    inline = "".join(f"![]({i}){{.inline-icon}} " for i in icons)
    cls = ".dataset-row" if figure else ".dataset-row .nofigure"
    block = [f"::: {{{cls}}}"]
    if figure:
        block += [f'![]({figure}){{fig-alt="{alt_text(body)}"}}', ""]
    block += ["::: {.dataset-text}", (inline + body).strip(), ":::", ":::", ""]
    out.append("\n".join(block))
    return 1


def main():
    if not SRC.exists():
        sys.exit(f"{SRC} not found; run from the site root.")
    raw = SRC.read_text(encoding="utf-8")
    front, _, body = raw.partition("---\n")[2].partition("\n---\n")
    out = ["---\n" + front + "\n---\n"]

    figure, icons, text, rows = None, [], [], 0
    for line in body.split("\n"):
        line = line.rstrip()
        if not line or line.strip() in {"---", "####"}:
            continue

        m = IMG.match(line)
        if m:                                   # a line holding only an image
            if width(m.group(1)) >= LARGE_MIN_WIDTH:
                if text:                        # figure starts the next entry
                    rows += emit(figure, icons, text, out)
                    figure, icons, text = None, [], []
                figure = m.group(1)
            else:
                icons.append(m.group(1))
            continue

        if BULLET.search(line):                 # start of a description
            if text:
                rows += emit(figure, icons, text, out)
                figure, icons, text = None, [], []
            line = BULLET.sub("", line)
            for src in INLINE_IMG.findall(line):
                if width(src) < LARGE_MIN_WIDTH:
                    icons.append(src)
                    line = INLINE_IMG.sub("", line, count=1)

        text.append(line)

    rows += emit(figure, icons, text, out)
    SRC.write_text("\n".join(out), encoding="utf-8")
    print(f"Rewrote {SRC}: {rows} dataset entries")


if __name__ == "__main__":
    main()