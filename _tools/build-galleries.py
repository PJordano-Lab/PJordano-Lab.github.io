#!/usr/bin/env python3
"""Rebuild gallery.qmd as one lightbox gallery per photo group.

Source of truth is the image set already referenced by gallery.qmd (the
RapidWeaver export). Each group's photos are COPIED (originals left in place)
into static/images/galleries/<slug>/, mirroring the layout of the existing
static/images/newgalleries/ tree, and the page is rewritten with one
`.gallery-grid` container per group.

Groups with no photos of their own in the export - their section held only the
"UNDER CONSTRUCTION" strip - get static/images/gallery__files__stacks-image-a56e4e6.gif
(hazard tape) as a placeholder, copied into the group folder so every group
folder exists and is non-empty.

Captions are carried as lightbox `title` text rather than figure captions, so
the grid stays a clean thumbnail wall and the description appears when a photo
is opened.

Usage:
    python _tools/build-galleries.py [--dry-run]
"""

import argparse
import pathlib
import re
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "gallery.qmd"
GALLERIES = ROOT / "static" / "images" / "galleries"
PLACEHOLDER = "static/images/gallery__files__stacks-image-a56e4e6.gif"

# (display title, folder slug, cover image basename or None, source headings)
GROUPS = [
    ("Megafauna fruits", "megafauna-fruits", "stacks-image-37cb4c5-336x252.jpg",
     ["Megafauna fruits"]),
    ("Prunus mahaleb", "prunus-mahaleb", "stacks-image-1d2a609.jpg",
     ["Gallery-Prunus mahaleb"]),
    ("Study sites", "study-sites", "stacks-image-386a8ab-342x266.png",
     ["Study sites gallery", "Do\u00f1ana", "Islas Canarias", "Cazorla", "Alcornocales"]),
    ("Networks", "networks", "stacks-image-cf182a8.png", ["Networks"]),
    ("Brazil", "brazil", "stacks-image-59f2987-264x198.png",
     ["Ilha do Cardoso, Brazil", "Brazil"]),
    ("The lab", "the-lab", "stacks-image-aefbfc4.png", ["IEG"]),
    ("Fruits, flowers", "fruits-flowers", "stacks-image-e6a7cb3-274x206.jpg",
     ["Fruits, flowers"]),
    ("Birds", "birds", "stacks-image-3e89ac4-234x180.jpg", ["Gallery-Bird photos"]),
    ("Art", "art", "stacks-image-7bd0e15-318x208.jpg", ["Art"]),
    ("LEGO", "lego", None, []),
]

# decorative strips from the export: hazard tape and the UNDER CONSTRUCTION
# banner. Never photos, so they are not gallery content.
DECORATIVE = re.compile(r"stacks-image-(a56e4e6|d624d4a|02c1105|b0d5deb|c848074)\.gif$")

INTRO = """Collections of images related to our research. Click any photo to open it
full size and step through the gallery."""


def harvest(text):
    """-> {heading: [(path, caption), ...]} for every image in the page."""
    lines = text.split("\n")
    found, heading = {}, None
    for i, line in enumerate(lines):
        h = re.match(r"^#{2,4}\s+(.*)$", line)
        if h:
            heading = h.group(1).strip()
        for alt, path in re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", line):
            if DECORATIVE.search(path):
                continue
            found.setdefault(heading, []).append((path, caption(lines, i, alt)))
    return found


def caption(lines, idx, alt):
    """Descriptive line under the image; fall back to a meaningful alt text."""
    for line in lines[idx + 1: idx + 4]:
        t = line.strip()
        if not t or t.startswith(("#", "---", "![", "[")):
            continue
        t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)   # markdown link -> its text
        t = re.sub(r"[*_`]+", "", t).strip()
        return "" if t.startswith("http") else t
    return "" if re.fullmatch(r"Stacks Image \d+", alt.strip()) else alt.strip()


def build():
    text = SRC.read_text(encoding="utf-8")
    found = harvest(text)
    # index thumbnails live above the first heading; their filenames carry an
    # export prefix (gallery__files__), so match on suffix not equality
    covers = {p.rsplit("/", 1)[-1]: (p, c) for p, c in found.get(None, [])}

    plan = []
    for title, slug, cover, headings in GROUPS:
        photos, seen = [], set()
        hit = next((b for b in covers if cover and b.endswith(cover)), None)
        if hit:
            photos.append((covers[hit][0], title))   # cover caption = group name
            seen.add(hit)
        elif cover:
            print(f"  WARN cover not found for {slug}: {cover}")
        for h in headings:
            for path, cap in found.get(h, []):
                base = path.rsplit("/", 1)[-1]
                if base in seen:
                    continue
                seen.add(base)
                photos.append((path, cap))
        plan.append((title, slug, photos))
    return plan


def write_page(plan, dry_run=False):
    out = [
        "---",
        'title: "Gallery"',
        "author: Pedro Jordano",
        'description: "Photographs of study systems, field sites, and network figures."',
        'title-block-banner: "#1a1c20"',
        "lightbox: true",
        "hand-edited: true",
        "---",
        "",
        INTRO,
        "",
    ]
    for title, slug, photos in plan:
        out += [f"## {title}", ""]
        if not photos:
            out += [
                "::: {.gallery-empty}",
                f'<img src="{PLACEHOLDER}" alt="Under construction">',
                "",
                "This gallery is being assembled.",
                ":::",
                "",
            ]
            continue
        out += ["::: {.gallery-grid}", ""]
        for path, cap in photos:
            base = path.rsplit("/", 1)[-1]
            new = f"static/images/galleries/{slug}/{base}"
            attrs = [".lightbox", f'group="{slug}"']
            clean = cap[:180].replace(chr(34), chr(39))
            if clean:
                attrs.append(f'desc="{clean}"')
                attrs.append(f'fig-alt="{clean[:120]}"')
            title = f' "{clean}"' if clean else ""
            out.append(f"![]({new}{title}){{{' '.join(attrs)}}}")
        out += ["", ":::", ""]

    if not dry_run:
        SRC.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")
    return "\n".join(out)


def copy_files(plan, dry_run=False):
    copied = 0
    for title, slug, photos in plan:
        dest = GALLERIES / slug
        sources = [p for p, _ in photos] or [PLACEHOLDER]
        if not dry_run:
            dest.mkdir(parents=True, exist_ok=True)
        for rel in sources:
            src = ROOT / rel
            if not src.exists():
                print(f"  MISSING {rel}")
                continue
            if not dry_run:
                shutil.copy2(src, dest / src.name)
            copied += 1
    return copied


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    plan = build()
    for title, slug, photos in plan:
        state = f"{len(photos)} photos" if photos else "empty -> hazard-tape placeholder"
        print(f"  {title:<18} {slug:<18} {state}")
    copied = copy_files(plan, args.dry_run)
    write_page(plan, args.dry_run)
    print(f"\ngroups: {len(plan)} | files copied: {copied}"
          f"{' (dry run, nothing written)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
