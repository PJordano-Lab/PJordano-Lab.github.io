#!/usr/bin/env python3
"""Restructure people.qmd into two-column person rows.

The page came from a Hugo export where each person is a loose sequence of
paragraphs: a portrait image, then a bullet-icon image followed by the name and
description glued together with no separator. This rewrites each person as

    ::: {.person-row}
    ![](portrait)

    ::: {.person-text}
    **Name**

    Description
    :::
    :::

so the portrait and its text sit in two aligned grid columns (see .person-row
in html/pedroj.scss). Run once: `python _tools/format-people.py`.
"""

import re
import sys
from pathlib import Path

SRC = Path("people.qmd")

BULLET = re.compile(r"!\[[^\]]*\]\(static/images/people__files__bullet_pp[^)]*\)")
PHOTO = re.compile(r"^!\[[^\]]*\]\((static/images/[^)]+)\)$")
LINKED_PHOTO = re.compile(r"^\[!\[[^\]]*\]\((static/images/[^)]+)\)\]\(([^)]+)\)")
# A name at the head of a person entry: **Name**, [**Name**](url) or [Name](url)
NAME_TOKEN = re.compile(r"^(?:\[\*\*(?P<bl>[^*]+)\*\*(?P<tail>[^\]]*)\]\((?P<blu>[^)]+)\)"
                        r"|\[(?P<l>[^\]*]+)\]\((?P<lu>[^)]+)\)"
                        r"|\*\*(?P<b>[^*]+)\*\*)")
# Section markers that the export glued onto the end of a person's description
INLINE_SECTIONS = ["Past PhD students", "Master students (current and past)"]


def unwrap(block):
    """Join the hard-wrapped lines of one paragraph into a single line."""
    out = []
    for line in block.split("\n"):
        line = line.strip()
        if not line:
            continue
        if out and not out[-1].endswith("\\"):
            # a line ending in "\" is a markdown hard break: keep it
            out[-1] = out[-1] + " " + line
        else:
            out.append(line)
    return "\n".join(out)


def split_name(text, raw=None):
    """Return (name_markdown, plain_name, description) for one person entry.

    `raw` keeps the original line breaks: for names that carry no bold or link
    markup, the export's line wrap is the only name/description boundary.
    """
    text = text.strip()
    names, spill = [], ""
    while True:
        m = NAME_TOKEN.match(text)
        if not m:
            break
        if m.group("bl"):
            url = m.group("blu").split(" ")[0]
            names.append((f"[**{m.group('bl')}**]({url})", m.group("bl")))
            # the export sometimes swallowed the description inside the link
            spill += m.group("tail") or ""
        elif m.group("l"):
            names.append((f"[**{m.group('l')}**]({m.group('lu')})", m.group("l")))
        else:
            names.append((f"**{m.group('b')}**", m.group("b")))
        text = text[m.end():]
    if not names:
        # Unmarked name: the export's first line break is the boundary.
        source = raw.strip() if raw and raw.strip() else text
        head, _, tail = source.partition("\n")
        head = head.rstrip("\\").strip()
        if raw:
            tail = unwrap(tail)
        names = [(f"**{head}**", head)]
        text = tail
    name_md = " ".join(n for n, _ in names)
    plain = names[0][1]
    desc = (spill + " " + text).lstrip("\\").strip()
    if desc.startswith(","):
        name_md += desc
        desc = ""
    return name_md, plain, desc


def person_block(photo, entry, raw=None):
    name_md, plain, desc = split_name(entry, raw)
    alt = plain.replace('"', "'")
    cls = ".person-row" if photo else ".person-row .nophoto"
    lines = [f"::: {{{cls}}}"]
    if photo:
        lines += [f'![]({photo}){{fig-alt="{alt}"}}', ""]
    lines += ["::: {.person-text}", name_md]
    if desc:
        lines += ["", desc]
    lines += [":::", ":::", ""]
    return "\n".join(lines)


def main():
    if not SRC.exists():
        sys.exit(f"{SRC} not found; run from the site root.")
    raw = SRC.read_text(encoding="utf-8")
    front, _, body = raw.partition("---\n")[2].partition("\n---\n")
    front = "---\n" + front + "\n---\n"

    # Pull section markers that were glued onto the previous paragraph.
    for sec in INLINE_SECTIONS:
        body = body.replace(f" - {sec}", f"\n\n-   {sec}")

    out, photo, people = [front], None, 0
    for block in re.split(r"\n\s*\n", body):
        block = "\n".join(l[4:] if l.startswith("    ") else l
                          for l in block.split("\n")).strip()
        if not block or block.startswith("---") or block == "Open all":
            continue
        flat = unwrap(block)

        m = re.match(r"^-\s+(?!!)(.{2,60})$", flat)
        if m:                                  # section heading
            if photo:                          # e.g. the page banner
                out.append(f"![]({photo[0]})\n")
                photo = None
            out.append(f"## {m.group(1).strip()}\n")
            continue

        lp = LINKED_PHOTO.match(flat)
        if lp:                                 # portrait that links somewhere
            photo = (lp.group(1), lp.group(2))
            continue
        p = PHOTO.match(flat)
        if p and "bullet_pp" not in flat:      # plain portrait
            photo = (p.group(1), None)
            continue

        if BULLET.search(flat):                # one or more person entries
            raws = BULLET.split(block)
            for i, entry in enumerate(BULLET.split(flat)):
                if not entry.strip():
                    continue
                raw = raws[i] if i < len(raws) else None
                out.append(person_block(photo[0] if photo else None, entry, raw))
                people += 1
                photo = None
            continue

        out.append(flat + "\n")                # anything else, kept verbatim

    SRC.write_text("\n".join(out), encoding="utf-8")
    print(f"Rewrote {SRC}: {people} person entries")


if __name__ == "__main__":
    main()