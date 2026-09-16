#!/usr/bin/env python3
"""Assemble photos/<group>/ for the andrewheiss/photo-gallery extension.

Target layout (one flat folder of originals per group, no nesting):

    photos/
      megafauna-fruits/
        megafauna-001.jpg
        album.yml
      prunus-mahaleb/
      ...

Sources are the photo sets already in the repo:

  * static/images/newgalleries/*   Apple Aperture web exports. pictures/ holds
    the full-size files; each large-N.html carries a "Caption:" line, which is
    harvested into album.yml (titles/descriptions).
  * static/images/galleries/*      older "Galerie" exports plus the folders
    built from gallery.qmd, whose captions come from the page itself.

Images are COPIED (sources untouched) and renamed <tag>-NNN.ext so the
extension's alphabetical order is stable and album.yml keys never collide.
The extension writes thumbs/ inside each folder on first render.

Usage:
    python _tools/build-photo-gallery.py [--dry-run]
"""

import argparse
import pathlib
import re
import shutil
import sys

from PIL import Image

try:
    import piexif
except ImportError:                                  # optional build-time dep
    piexif = None

ROOT = pathlib.Path(__file__).resolve().parent.parent
PHOTOS = ROOT / "photos"
IMAGES = ROOT / "static" / "images"
EXT = {".jpg", ".jpeg", ".png"}

# group -> display title, and the source folders feeding it.
# Each source: (path relative to static/images, filename tag)
GROUPS = [
    ("megafauna-fruits", "Megafauna fruits", [
        ("qmd:Megafauna fruits", "megafauna"),
    ]),
    ("prunus-mahaleb", "Prunus mahaleb", [
        ("galleries/prunus/pictures", "prunus"),
    ]),
    # Study sites is a CONTAINER: the photos live in one album per locality,
    # because the extension reads a single flat folder per gallery. Each entry
    # below carries the parent slug in the 4th field, which puts it inside the
    # Study sites tab as its own sub-gallery.
    ("study-sites", "Study sites", [], None),
    ("study-sites/alcornocales", "Los Alcornocales", [
        ("newgalleries/sites/alcornocales/pictures", "alcornocales"),
    ], "study-sites"),
    ("study-sites/correhuelas", "Las Correhuelas", [
        ("newgalleries/sites/correhuelas/pictures", "correhuelas"),
    ], "study-sites"),
    ("study-sites/guadahornillos", "Nava de las Correhuelas / Guadahornillos", [
        ("newgalleries/sites/guadahornillos/pictures", "guadahornillos"),
    ], "study-sites"),
    ("study-sites/donana", "Doñana", [], "study-sites"),
    ("study-sites/canarias", "Islas Canarias", [], "study-sites"),
    ("networks", "Networks", [
        ("newgalleries/networks/pictures", "networks"),
    ]),
    ("brazil", "Brazil", [
        ("newgalleries/sites/cardoso/pictures", "cardoso"),
        ("newgalleries/sites/pantanal/pictures", "pantanal"),
        ("qmd:Ilha do Cardoso, Brazil|Brazil", "brazil"),
    ]),
    ("the-lab", "The lab", [
        ("newgalleries/ieg_gallery/pictures", "ieg"),
    ]),
    ("fruits-flowers", "Fruits, flowers", [
        ("newgalleries/fruits_spain/pictures", "fruits"),
    ]),
    ("birds", "Birds", [
        ("qmd:Gallery-Bird photos", "birds"),
    ]),
    ("art", "Art", [
        ("newgalleries/other/pictures", "art"),
        ("newgalleries/equipo_57/pictures", "equipo57"),
    ]),
    ("lego", "LEGO", []),
]

# decorative strips from the old RapidWeaver export - never photos
DECORATIVE = re.compile(r"stacks-image-(a56e4e6|d624d4a|02c1105|b0d5deb|c848074)\.gif$")


def aperture_captions(export_dir):
    """{picture filename: caption} from an Aperture export's large-N.html pages."""
    caps = {}
    for page in export_dir.glob("large-*.html"):
        text = page.read_text(encoding="utf-8", errors="replace")
        img = re.search(r'src="pictures/([^"]+)"', text)
        cap = re.search(r"<li>\s*Caption:\s*([^<]+?)\s*</li>", text)
        if img and cap:
            caps[img.group(1)] = re.sub(r"\s+", " ", cap.group(1)).strip()
    return caps


def gallery_qmd_captions():
    """{image basename: caption} harvested from the pre-extension gallery page."""
    src = ROOT / "_tools" / "gallery.qmd.orig"
    if not src.exists():
        return {}
    lines = src.read_text(encoding="utf-8").split("\n")
    caps = {}
    for i, line in enumerate(lines):
        for _, path in re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", line):
            if DECORATIVE.search(path):
                continue
            for nxt in lines[i + 1: i + 4]:
                t = nxt.strip()
                if not t or t.startswith(("#", "---", "![", "[")):
                    continue
                t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
                t = re.sub(r"[*_`]+", "", t).strip()
                if t and not t.startswith("http"):
                    caps[path.rsplit("/", 1)[-1]] = t
                break
    return caps


def qmd_section_images(spec):
    """Image paths under one or more headings of the pre-extension page.

    Megafauna fruits, Birds and the Brazil cover shots were never part of an
    export package - they exist only as loose files in static/images that the
    old gallery.qmd referenced, so they are collected from the page itself.
    `spec` is "qmd:Heading" or "qmd:Heading A|Heading B".
    """
    src = ROOT / "_tools" / "gallery.qmd.orig"
    if not src.exists():
        print(f"  MISSING {src} - cannot resolve {spec}")
        return []
    wanted = {h.strip() for h in spec[4:].split("|")}
    lines = src.read_text(encoding="utf-8").split("\n")
    out, heading = [], None
    for line in lines:
        h = re.match(r"^#{2,4}\s+(.*)$", line)
        if h:
            heading = h.group(1).strip()
            continue
        if heading not in wanted:
            continue
        for _, path in re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", line):
            if DECORATIVE.search(path):
                continue
            p = ROOT / path.lstrip("/")
            if p.is_file() and p not in out:
                out.append(p)
    return out


def split_caption(caption, fallback_title):
    """Aperture captions read 'Corema album. Donana, Huelva.' -> title, rest."""
    if not caption:
        return fallback_title, ""
    parts = re.split(r"(?<=\.)\s+", caption, maxsplit=1)
    title = parts[0].rstrip(".").strip() or fallback_title
    desc = parts[1].strip() if len(parts) > 1 else ""
    return title, desc


def place(srcfile, target):
    """Copy one source image, normalising anything the extension cannot thumb.

    The extension always writes thumbs as JPEG, so an RGBA/palette source
    raises "cannot write mode RGBA as JPEG"; such files are flattened onto
    white and saved as JPEG, carrying their EXIF block across. Truncated
    files are skipped rather than left to break the render.
    Returns the written filename, or None when the source is unreadable.
    """
    try:
        with Image.open(srcfile) as im:
            im.load()
            needs_convert = im.mode not in ("RGB", "L")
            exif = im.info.get("exif")
            if not needs_convert:
                shutil.copy2(srcfile, target)
                return target.name
            flat = Image.new("RGB", im.size, (255, 255, 255))
            rgba = im.convert("RGBA")
            flat.paste(rgba, mask=rgba.split()[-1])
            jpg = target.with_suffix(".jpg")
            flat.save(jpg, "JPEG", quality=92, **({"exif": exif} if exif else {}))
            return jpg.name
    except Exception as exc:
        print(f"  SKIP unreadable {srcfile.name}: {type(exc).__name__}")
        return None


def _rational(v):
    """PIL IFDRational -> (numerator, denominator) ints for piexif."""
    try:
        num, den = v.numerator, v.denominator
        return int(num), int(den) or 1
    except AttributeError:
        return int(round(float(v) * 100)), 100


def normalize_exif(target):
    """Rewrite an EXIF block that piexif cannot parse but PIL can.

    Several Nikon/Aperture-era JPEGs here carry an EXIF segment piexif
    rejects outright (`piexif.load` raises), so the extension - which reads
    metadata through piexif - reports no camera or capture date for them even
    though the data is there. Rebuild a minimal, valid block with the six
    fields the extension surfaces and insert it; piexif.insert only replaces
    the metadata segment, so the pixels are never re-encoded.
    Returns True when a repair was made.
    """
    if piexif is None:
        return False
    try:
        raw = piexif.load(str(target))
        # the extension falls back to 0th:DateTime when DateTimeOriginal is
        # absent, so BOTH have to be checked for a zeroed stamp
        stamp = raw.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
        alt = raw.get("0th", {}).get(piexif.ImageIFD.DateTime)
        def _zeroed(v):
            return bool(v) and str(v).lstrip("b'\"").startswith("0000")
        if _zeroed(stamp) or _zeroed(alt):
            # drop the zeroed timestamp so the caption shows no date rather
            # than "0000-00-00"; the rest of the block is left untouched
            if _zeroed(stamp):
                del raw["Exif"][piexif.ExifIFD.DateTimeOriginal]
            if _zeroed(alt):
                del raw["0th"][piexif.ImageIFD.DateTime]
            raw.pop("thumbnail", None)
            piexif.insert(piexif.dump(raw), str(target))
            return True
        if raw.get("0th", {}).get(piexif.ImageIFD.Model) or stamp:
            return False                              # already readable
    except Exception:
        pass                                          # unparseable - rebuild

    try:
        with Image.open(target) as im:
            base = im.getexif()
            sub = base.get_ifd(0x8769) if base else {}
        if not base:
            return False
        zeroth, exif_ifd = {}, {}
        if base.get(271):
            zeroth[piexif.ImageIFD.Make] = str(base[271]).strip().encode()
        if base.get(272):
            zeroth[piexif.ImageIFD.Model] = str(base[272]).strip().encode()
        when = sub.get(36867) or base.get(306)
        # some files carry a zeroed timestamp ("0000:00:00 00:00:00"); writing
        # it back would surface "0000-00-00" as the capture date in the caption
        if when and re.match(r"[1-9]\d{3}:\d{2}:\d{2}", str(when).strip()):
            exif_ifd[piexif.ExifIFD.DateTimeOriginal] = str(when).encode()
        if sub.get(37386):
            exif_ifd[piexif.ExifIFD.FocalLength] = _rational(sub[37386])
        if sub.get(33437):
            exif_ifd[piexif.ExifIFD.FNumber] = _rational(sub[33437])
        if sub.get(33434):
            exif_ifd[piexif.ExifIFD.ExposureTime] = _rational(sub[33434])
        iso = sub.get(34855)
        if iso:
            exif_ifd[piexif.ExifIFD.ISOSpeedRatings] = int(iso if not isinstance(iso, tuple) else iso[0])
        if not zeroth and not exif_ifd:
            return False
        piexif.insert(piexif.dump({"0th": zeroth, "Exif": exif_ifd, "1st": {}, "GPS": {}, "Interop": {}}),
                      str(target))
        return True
    except Exception as exc:
        print(f"  EXIF repair failed for {target.name}: {type(exc).__name__}")
        return False


def yaml_quote(s):
    """Double-quoted YAML scalar - safe for colons, quotes and accents."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def dump_album(album):
    """Emit the album.yml mapping without requiring PyYAML at build time."""
    out = ["images:"]
    for name in sorted(album):
        out.append(f"  {yaml_quote(name)}:")
        for key in ("title", "description", "alt", "date"):
            if album[name].get(key):
                out.append(f"    {key}: {yaml_quote(album[name][key])}")
    return "\n".join(out) + "\n"


def build(dry_run=False, out_root=None):
    global PHOTOS
    if out_root:
        PHOTOS = pathlib.Path(out_root)
    qmd_caps = gallery_qmd_captions()
    summary = []

    for entry in GROUPS:
        slug, title, sources = entry[0], entry[1], entry[2]
        parent = entry[3] if len(entry) > 3 else None
        dest = PHOTOS / slug
        if not dry_run:
            dest.mkdir(parents=True, exist_ok=True)
            tags = {t for _, t in sources}
            for old in dest.iterdir():
                if old.is_file() and re.match(r"(" + "|".join(tags) + r")-\d{3}\.", old.name):
                    old.unlink()
                elif old.is_dir() and old.name == "thumbs":
                    shutil.rmtree(old)

        album, n, captioned, repaired = {}, 0, 0, 0
        for rel, tag in sources:
            if rel.startswith("qmd:"):
                caps = {}
                files = qmd_section_images(rel)
                if not files:
                    print(f"  MISSING source {rel}")
                    continue
            else:
                src_dir = IMAGES / rel
                if not src_dir.is_dir():
                    print(f"  MISSING source {rel}")
                    continue
                caps = aperture_captions(src_dir.parent) if src_dir.name == "pictures" else {}
                files = sorted(p for p in src_dir.iterdir()
                               if p.is_file() and p.suffix.lower() in EXT
                               and not DECORATIVE.search(p.name))
            for i, srcfile in enumerate(files, 1):
                newname = f"{tag}-{i:03d}{srcfile.suffix.lower()}"
                if not dry_run:
                    written = place(srcfile, dest / newname)
                    if written is None:
                        continue
                    newname = written
                    if newname.lower().endswith((".jpg", ".jpeg")):
                        repaired += normalize_exif(dest / newname)
                n += 1
                cap = caps.get(srcfile.name) or qmd_caps.get(srcfile.name, "")
                if cap:
                    captioned += 1
                    t, d = split_caption(cap, title)
                    entry = {"title": t}
                    if d:
                        entry["description"] = d
                    entry["alt"] = cap[:160]
                    album[newname] = entry

        if not album and n and not dry_run:
            # stub so every folder has a place to add metadata
            (dest / "album.yml").write_text(
                "# Per-image metadata for the photo-gallery extension.\n"
                "# Uncomment and fill in as needed; EXIF supplies camera, lens,\n"
                "# ISO and capture date on its own.\n"
                "#\n"
                "# images:\n"
                f"#   {tag}-001.jpg:\n"
                "#     title: \"Species name\"\n"
                "#     description: \"Locality, notes\"\n"
                "#     date: 2024-05-17\n", encoding="utf-8")
        if album and not dry_run:
            (dest / "album.yml").write_text(
                "# Per-image metadata for the photo-gallery extension.\n"
                "# Keys are filenames; title/description/alt override what EXIF\n"
                "# provides, and `date: YYYY-MM-DD` overrides the capture date.\n"
                + dump_album(album),
                encoding="utf-8")
        summary.append((slug, title, n, captioned, repaired, parent))
    return summary


def seed_folder_titles():
    """Title every uncaptioned photo with its album's display name.

    The extension falls back to the bare filename when album.yml has no title,
    which reads badly on the field-site albums (none of those exports carried
    captions). New entries are APPENDED: captions harvested from the exports
    are never touched, and neither is any title edited by hand.
    """
    for entry in GROUPS:
        slug, title = entry[0], entry[1]
        d = PHOTOS / slug
        if not d.is_dir():
            continue
        imgs = sorted(p.name for p in d.iterdir()
                      if p.is_file() and p.suffix.lower() in EXT)
        if not imgs:
            continue
        album = d / "album.yml"
        existing = album.read_text(encoding="utf-8") if album.exists() else ""
        have = set(re.findall(r'^\s{2}"?([^"\n:]+\.[a-zA-Z]+)"?:', existing, re.M))
        new = [n for n in imgs if n not in have]
        if not new:
            continue
        block = "".join(f'  {yaml_quote(n)}:\n    title: {yaml_quote(title)}\n' for n in new)
        if re.search(r'^images:\s*$', existing, re.M):
            album.write_text(existing.rstrip("\n") + "\n" + block, encoding="utf-8")
        else:
            album.write_text(
                "# Per-image metadata for the photo-gallery extension.\n"
                "# Titles default to the album name; replace any with something\n"
                "# specific, and add `description:` or `date:` as needed.\n"
                "images:\n" + block, encoding="utf-8")
        print(f"  titled {len(new):>3} photos in {slug}")


def survey():
    """Summarise photos/ as it stands on disk, without copying anything.

    Used after the tree has been rearranged by hand: the page is rebuilt to
    match reality instead of the GROUPS source table.
    """
    summary = []
    for entry in GROUPS:
        slug, title, sources = entry[0], entry[1], entry[2]
        parent = entry[3] if len(entry) > 3 else None
        d = PHOTOS / slug
        imgs = ([p for p in d.iterdir()
                 if p.is_file() and p.suffix.lower() in EXT] if d.is_dir() else [])
        album = d / "album.yml"
        captioned = 0
        if album.exists():
            captioned = sum(1 for line in album.read_text(encoding="utf-8").split("\n")
                            if line.startswith("    title:"))
        summary.append((slug, title, len(imgs), captioned, 0, parent))
    return summary


def write_page(summary, dry_run=False):
    out = [
        "---",
        'title: "Gallery"',
        "author: Pedro Jordano",
        'description: "Photographs of study systems, field sites, and network figures."',
        'title-block-banner: "#1a1c20"',
        "hand-edited: true",
        "# photo-gallery defaults. The extension reads them from",
        "# extensions.photo-gallery (NOT the document root); per-gallery",
        "# overrides go on the shortcode itself, e.g. columns=4.",
        "extensions:",
        "  photo-gallery:",
        "    layout: justified",
        "    thumbnail-height: 220",
        "    thumbnail-max-width: 1400",
        "    thumbnail-quality: 88",
        "    gap: 5",
        "    show-exif: true",
        "    show-date: true",
        "    show-download: true",
        "    show-bullets: false",
        "    date-format: \"D MMMM YYYY\"",
        "    transition: zoom",
        "---",
        "",
        "Photographs from our study systems, field sites and lab. Click any image to",
        "open it full size; camera details and capture date come from the files' own",
        "EXIF metadata.",
        "",
        "::: {.panel-tabset}",
        "",
    ]
    for slug, title, n, captioned, repaired, parent in summary:
        if parent is None:
            out += [f"## {title}", ""]
        else:
            out += [f"### {title}", ""]
        if n:
            out += [f"{{{{< photo-gallery photos/{slug} id={slug.replace('/', '-')} >}}}}", ""]
        elif any(p == slug for *_, p in summary):
            # container heading: its sub-galleries follow
            continue
        else:
            out += [
                "Photographs for this gallery are not online yet. Drop JPEGs into",
                f"`photos/{slug}/` and they will appear on the next render.",
                "",
            ]
    out += [":::", ""]
    if not dry_run:
        (ROOT / "gallery.qmd").write_text("\n".join(out), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--titles-from-folder", action="store_true",
                    help="for albums whose photos have no caption, write album.yml "
                         "titles from the album's display name, so tiles read "
                         "'Los Alcornocales' instead of 'alcornocales-001.jpg'")
    ap.add_argument("--page-only", action="store_true",
                    help="rewrite gallery.qmd from what is on disk, copying nothing "
                         "(use after rearranging photos/ by hand)")
    ap.add_argument("--out", help="write the tree here instead of photos/ "
                                  "(use a non-iCloud path to avoid sync-conflict copies, "
                                  "then move it into place in one pass)")
    args = ap.parse_args()

    if args.titles_from_folder:
        seed_folder_titles()
    if args.page_only:
        summary = survey()
    else:
        summary = build(args.dry_run, args.out)
    for slug, title, n, captioned, repaired, parent in summary:
        if not n and any(p == slug for *_, p in summary):
            print(f"  {title:<18} photos/{slug:<28} container")
            continue
        state = (f"{n:>3} photos, {captioned:>3} captioned, {repaired:>3} EXIF repaired"
                 if n else "no photos yet")
        print(f"  {'  ' + title if parent else title:<18} photos/{slug:<28} {state}")
    write_page(summary, args.dry_run)
    total = sum(s[2] for s in summary)
    print(f"\ngroups: {len(summary)} | images: {total} | "
          f"captions: {sum(s[3] for s in summary)} | EXIF repaired: {sum(s[4] for s in summary)}"
          f"{' (dry run, nothing written)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
