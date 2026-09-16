#!/usr/bin/env python3
"""Repair image links that a Hugo/RapidWeaver export wrapped inside grid tables.

In a pandoc grid table the cell width is fixed by the +---+---+ ruler, so the
export broke long image markdown across several cell lines:

    | ![](static/images/ongf                |
    | igs/endocarp.jpg){fig-align="center"} |

Pandoc joins those fragments with a space, so the link target really is
"static/images/ongf igs/endocarp.jpg", which it percent-encodes to %20... and
the browser gets a 404.

Unwrapping onto one line is not possible - the paths are far longer than the
column. So each image becomes a REFERENCE-style image, which is short enough to
fit, with the real path collected in a definition block at the end of the file:

    | ![][proj-01]                          |
    ...
    [proj-01]: static/images/ongfigs/endocarp.jpg

Idempotent: definitions live between sentinels and are rewritten in place. Every
recovered path is checked against the filesystem and missing files are reported
rather than silently linked.

Usage:
    python _tools/fix-grid-table-images.py projects.qmd --dry-run
    python _tools/fix-grid-table-images.py projects.qmd
"""

import argparse
import pathlib
import re
import sys
import textwrap

ROOT = pathlib.Path(__file__).resolve().parent.parent
START = "<!-- image-refs:start -->"
END = "<!-- image-refs:end -->"


def cell_columns(ruler):
    """Character spans of each column, from a +---+---+ ruler line."""
    spans, start = [], None
    for i, ch in enumerate(ruler):
        if ch == "+":
            if start is not None:
                spans.append((start, i))
            start = i + 1
    return spans


def tables(lines):
    """Yield (first_line, last_line) for each grid-table block."""
    i = 0
    while i < len(lines):
        # a ruler is '+---+', '+===+' or, with alignment markers, '+:--:+'
        if re.match(r"^\+[-=:]", lines[i]):
            j = i
            while j < len(lines) and (lines[j].startswith("+") or lines[j].startswith("|")):
                j += 1
            yield i, j - 1
            i = j
        else:
            i += 1


def normalise(markdown):
    """Collapse the whitespace the table introduced into image markdown.

    Alt text keeps single spaces; the link target loses whitespace entirely
    (that is where %20 came from); attribute blocks collapse to single spaces.
    """
    md = re.sub(r"\s+", " ", markdown).strip()
    md = re.sub(r"\]\(([^)]*)\)", lambda m: "](" + re.sub(r"\s+", "", m.group(1)) + ")", md)
    md = re.sub(r"\{([^}]*)\}", lambda m: "{" + re.sub(r"\s+", " ", m.group(1)).strip() + "}", md)
    return md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("page", nargs="?", default="projects.qmd")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    path = ROOT / args.page
    raw = path.read_text(encoding="utf-8")
    lines = raw.split("\n")

    # Existing definitions are kept: a later run that finds one new wrapped
    # image must not rewrite the block with only that one, orphaning the rest.
    existing = []
    block = re.search(re.escape(START) + r"(.*?)" + re.escape(END), raw, re.S)
    if block:
        # a definition may carry a quoted title ([lab]: url "Title"), so the
        # target is not always a single whitespace-free token - matching only
        # \S+ silently dropped those definitions on rewrite
        existing = re.findall(r"^\[([^\]]+)\]:\s*(\S+(?:\s+\"[^\"]*\")?)\s*$",
                              block.group(1), re.M)
    by_target = {tgt: lab for lab, tgt in existing}
    next_n = 1 + max((int(m.group(1)) for lab, _ in existing
                      if (m := re.match(r"proj-(\d+)$", lab))), default=0)

    refs, missing, fixed = list(existing), [], 0

    for top, bottom in tables(lines):
        spans = cell_columns(lines[top])
        if not spans:
            continue
        # row boundaries inside this table
        bounds = [n for n in range(top, bottom + 1) if lines[n].startswith("+")]
        for a, b in zip(bounds, bounds[1:]):
            body = list(range(a + 1, b))
            for (cs, ce) in spans:
                cell = [lines[n][cs:ce] if len(lines[n]) > cs else "" for n in body]
                joined = " ".join(c.strip() for c in cell).strip()
                if "![" not in joined:
                    continue
                md = normalise(joined)
                m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)(\{[^}]*\})?\s*$", md)
                if not m:
                    # One cell's attribute block is truncated in the export
                    # ('{fig-align="center" width=' - no value, no closing
                    # brace), so the strict pattern rejects it. Salvage the
                    # complete key="value" pairs and drop the dangling
                    # fragment; its value is not recoverable from the file.
                    loose = re.match(r'^!\[([^\]]*)\]\(([^)]+)\)\s*\{(.*)$', md)
                    if not loose:
                        continue
                    pairs = re.findall(r'[\w-]+="[^"]*"', loose.group(3))
                    dangling = re.sub(r'[\w-]+="[^"]*"', "", loose.group(3)).strip(" }")
                    if dangling:
                        print(f"  salvaged a truncated attribute block; "
                              f"dropped {dangling!r}")
                    alt, target = loose.group(1), loose.group(2)
                    attrs = "{" + " ".join(pairs) + "}" if pairs else ""
                else:
                    alt, target, attrs = m.group(1), m.group(2), m.group(3) or ""
                label = by_target.get(target)
                if label is None:
                    label = f"proj-{next_n:02d}"
                    next_n += 1
                    by_target[target] = label
                    refs.append((label, target))
                if not (ROOT / target).exists():
                    missing.append(target)
                # keep only layout attributes; alt= duplicates the alt text and
                # would push the cell over its width
                keep = " ".join(x for x in re.findall(r'[\w-]+="[^"]*"', attrs)
                                if not x.startswith("alt="))
                repl = f"![{alt}][{label}]" + (f"{{{keep}}}" if keep else "")
                width = ce - cs

                # The alt text and the attribute block MAY wrap across cell
                # lines - pandoc rejoins them with a space, which is harmless
                # there. Only the link target must stay intact, and that now
                # lives in the definition block. So wrap rather than truncate:
                # dropping the alt would discard real captions.
                # break_on_hyphens must stay off: wrapping 'fig-align="center"'
                # at its hyphen would produce '{fig- align="center"}', which
                # pandoc will not parse as an attribute.
                wrap = lambda t: textwrap.wrap(t, width=width - 1,
                                               break_on_hyphens=False,
                                               break_long_words=False)
                wrapped = wrap(repl) or [repl]
                if len(wrapped) > len(body):
                    wrapped = wrap(f"![{alt}][{label}]")
                if len(wrapped) > len(body):
                    wrapped = [f"![][{label}]"]

                for k, n in enumerate(body):
                    line = lines[n].ljust(max(len(lines[n]), ce))
                    piece = wrapped[k] if k < len(wrapped) else ""
                    content = (" " + piece).ljust(width)
                    lines[n] = line[:cs] + content[:width] + line[ce:]
                fixed += 1

    text = "\n".join(lines).rstrip("\n") + "\n"
    if refs:
        block = (START + "\n" + "\n".join(f"[{lab}]: {tgt}" for lab, tgt in refs)
                 + "\n" + END + "\n")
        old = re.search(re.escape(START) + r".*?" + re.escape(END) + r"\n?", text, re.S)  # noqa
        text = (text[: old.start()] + block + text[old.end():]) if old else text + "\n" + block

    if not args.dry_run:
        path.write_text(text, encoding="utf-8")

    for lab, tgt in refs[:4]:
        print(f"  [{lab}] -> {tgt}")
    print(f"\nimages rewritten: {fixed} | definitions: {len(refs)} | "
          f"missing files: {len(missing)}"
          f"{' (dry run, nothing written)' if args.dry_run else ''}")
    for t in missing:
        print("  MISSING on disk:", t)
    return 0


if __name__ == "__main__":
    sys.exit(main())
