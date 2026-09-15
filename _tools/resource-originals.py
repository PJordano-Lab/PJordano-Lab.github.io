#!/usr/bin/env python3
"""Replace the web-resized files in photos/ with their originals from ~/Pictures.

The sets under static/images/{galleries,newgalleries} are RapidWeaver/Aperture
web exports, 500-800 px wide, and most had their EXIF stripped. The originals
live in the user's Pictures library, but the exports record no link back to
them (the paths in Galerie.param point at a library that no longer exists), so
matching is done by perceptual hash:

  * dHash (64-bit) of both sides, robust to downscaling and JPEG requantising
  * a candidate must match within HAMMING_MAX, agree on aspect ratio within
    ASPECT_TOL, and beat the runner-up by UNIQUE_GAP bits, so near-duplicate
    frames from a burst cannot be swapped for one another
  * the original must be at least MIN_SCALE times wider, otherwise there is
    nothing to gain

Matched files replace the current one under the SAME filename, so album.yml
keys and the captions harvested from the exports stay valid. Every decision is
written to _tools/photo-origins.csv.

Usage:
    python _tools/resource-originals.py [--dry-run] [--group birds]
"""

import argparse
import csv
import pathlib
import shutil
import sys

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
PHOTOS = ROOT / "photos"
PICTURES = pathlib.Path.home() / "Pictures"
LOG = ROOT / "_tools" / "photo-origins.csv"

# Places worth searching, deliberately narrow. Excluded on purpose:
#   Photos Library.photoslibrary  - macOS privacy protection denies reads
#   Illustrations_stored/"Illustrations and graphs" - 5.3 GB of figures and
#       plates, not photographs, and slow to hash
#   LRC-Transfer - a 90 GB Lightroom catalogue of 2026 RAW captures, long
#       after these galleries were made
SEARCH_DIRS = [
    "Illustrations_stored/ieg_gallery",
    "Illustrations_stored/thelab",
    "Illustrations_stored/people",
    "Illustrations_stored/pedro_photos",
    "Illustrations_stored/Birds_photos_www",
    "Illustrations_stored/Frugivore assemblages",
    "Illustrations_stored/Collins Guide",
    "Birds.pxvlibrary/Masters",
    "->Exported_Lightroom",
]
MAX_BYTES = 60 * 1024 * 1024        # skip huge scans/composites
RASTER = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

HAMMING_MAX = 6
COLOUR_MAX = 22          # mean per-channel difference allowed on the 4x4 grid
ASPECT_TOL = 0.03
UNIQUE_GAP = 2
MIN_SCALE = 1.25


def colour_grid(path, cells=4):
    """Mean RGB per cell of a 4x4 grid - a descriptor independent of dHash.

    dHash compares neighbouring luminances, so a low-detail image (or one with
    a heavy black film border, as several of these scans have) can collide
    with an unrelated photo of similar layout. Requiring the coarse colour
    layout to agree as well rejects those: a gull on sand cannot pass for a
    white house among pines.
    """
    try:
        with Image.open(path) as im:
            im.draft("RGB", (64, 64))
            small = im.convert("RGB").resize((cells, cells), Image.BILINEAR)
            return list(small.getdata())
    except Exception:
        return None


def colour_distance(a, b):
    """Mean absolute per-channel difference between two colour grids (0-255)."""
    if not a or not b or len(a) != len(b):
        return 255
    total = sum(abs(pa[c] - pb[c]) for pa, pb in zip(a, b) for c in range(3))
    return total / (len(a) * 3)


def dhash(path, size=8):
    """64-bit difference hash, plus (width, height). None if unreadable."""
    try:
        with Image.open(path) as im:
            w, h = im.size
            im.draft("L", (size * 8, size * 8))        # fast partial JPEG decode
            small = im.convert("L").resize((size + 1, size), Image.BILINEAR)
            px = list(small.getdata())
        bits = 0
        for row in range(size):
            base = row * (size + 1)
            for col in range(size):
                bits = (bits << 1) | (px[base + col] > px[base + col + 1])
        return bits, w, h
    except Exception:
        return None


def index_library(verbose=True):
    entries = []
    for rel in SEARCH_DIRS:
        root = pathlib.Path(rel) if pathlib.Path(rel).is_absolute() else PICTURES / rel
        if not root.is_dir():
            if verbose:
                print(f"  skip (absent): {rel}")
            continue
        files = [p for p in root.rglob("*")
                 if p.is_file() and p.suffix.lower() in RASTER
                 and p.stat().st_size <= MAX_BYTES]
        got = 0
        for p in files:
            d = dhash(p)
            if d:
                entries.append((d[0], d[1], d[2], p))
                got += 1
        if verbose:
            print(f"  indexed {got:>5} / {len(files):>5} files from {rel}")
    return entries


def best_match(target_hash, target_aspect, entries, min_width):
    """Best original for one target, or None when the choice is ambiguous.

    Returns (match, near) where `near` is the closest candidate regardless of
    acceptance, so the caller can say why a file was left alone.
    """
    ranked = []
    for h, w, ht, path in entries:
        if w < min_width or not ht:
            continue
        aspect = w / ht
        if abs(aspect - target_aspect) / target_aspect > ASPECT_TOL:
            continue
        ranked.append((bin(h ^ target_hash).count("1"), -w * ht, h, path, w, ht))
    if not ranked:
        return None, None
    ranked.sort()
    best = ranked[0]
    if best[0] > HAMMING_MAX:
        return None, best

    # Runners-up within UNIQUE_GAP bits are only acceptable if they are other
    # copies of the SAME photo (near-identical to `best`); a genuinely
    # different frame that close means the match is not trustworthy, which is
    # the burst-of-similar-shots case.
    for cand in ranked[1:]:
        if cand[0] > best[0] + UNIQUE_GAP:
            break
        if bin(cand[2] ^ best[2]).count("1") > HAMMING_MAX:
            return None, best
    return best, best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--group", help="limit to one photos/<group>")
    ap.add_argument("--root", help="photo tree to upgrade (default photos/)")
    ap.add_argument("--search", action="append", metavar="DIR",
                    help="extra folder to index, absolute or relative to ~/Pictures "
                         "(repeatable; replaces the built-in list when given)")
    ap.add_argument("--any-size", action="store_true",
                    help="diagnostic: ignore the MIN_SCALE filter and report the closest "
                         "match at any resolution, writing nothing")
    args = ap.parse_args()
    global PHOTOS
    if args.root:
        PHOTOS = pathlib.Path(args.root)

    global SEARCH_DIRS
    if args.search:
        SEARCH_DIRS = args.search
    print("indexing ~/Pictures ..." if not args.any_size
          else "indexing ~/Pictures (diagnostic, nothing will be written) ...")
    entries = index_library()
    print(f"  {len(entries)} candidate originals indexed\n")
    if not entries:
        print("nothing to match against")
        return 1

    rows, replaced, ambiguous, nomatch, toosmall = [], 0, 0, 0, 0
    groups = sorted(d for d in PHOTOS.iterdir()
                    if d.is_dir() and (not args.group or d.name == args.group))
    for gdir in groups:
        targets = sorted(p for p in gdir.iterdir()
                         if p.is_file() and p.suffix.lower() in RASTER)
        hits = 0
        for t in targets:
            d = dhash(t)
            if not d:
                continue
            th, tw, thh = d
            aspect = tw / thh if thh else 0
            if not aspect:
                continue
            match, near = best_match(th, aspect, entries,
                                     1 if args.any_size else int(tw * MIN_SCALE))
            if args.any_size:
                if near and near[0] <= HAMMING_MAX:
                    rows.append([gdir.name, t.name, tw, thh, str(near[3]), near[4], near[5],
                                 f"content-match(dist {near[0]}, scale {near[4]/tw:.2f}x)"])
                    hits += 1
                else:
                    rows.append([gdir.name, t.name, tw, thh, "", "", "",
                                 f"absent(best {near[0] if near else '-'} bits)"])
                continue
            if match is None:
                if near is None:
                    nomatch += 1
                    status = "no-candidate"
                elif near[0] > HAMMING_MAX:
                    nomatch += 1
                    status = f"no-match(best {near[0]} bits)"
                else:
                    ambiguous += 1
                    status = f"ambiguous({near[0]} bits)"
                rows.append([gdir.name, t.name, tw, thh, "", "", "", status])
                continue
            dist, _, _, src, sw, sh = match
            cdist = colour_distance(colour_grid(t), colour_grid(src))
            if cdist > COLOUR_MAX:
                # hash agreed but the images do not look alike: reject
                rows.append([gdir.name, t.name, tw, thh, str(src), sw, sh,
                             f"rejected-colour(hash {dist}, colour {cdist:.0f})"])
                ambiguous += 1
                continue
            rows.append([gdir.name, t.name, tw, thh, str(src), sw, sh,
                         f"replaced(dist {dist})"])
            if not args.dry_run:
                if src.suffix.lower() in {".jpg", ".jpeg"}:
                    shutil.copy2(src, t.with_suffix(".jpg"))
                else:
                    with Image.open(src) as im:
                        exif = im.info.get("exif")
                        im.convert("RGB").save(t.with_suffix(".jpg"), "JPEG", quality=95,
                                               **({"exif": exif} if exif else {}))
                if t.suffix.lower() != ".jpg":
                    t.unlink(missing_ok=True)
            replaced += 1
            hits += 1
        print(f"  {gdir.name:<17} {hits:>3} / {len(targets):>3} upgraded")

    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["group", "file", "cur_w", "cur_h", "original", "orig_w", "orig_h", "status"])
        w.writerows(rows)
    print(f"\nreplaced: {replaced} | ambiguous: {ambiguous} | unmatched: {nomatch}"
          f"{' (dry run, nothing written)' if args.dry_run else ''}")
    print(f"decisions logged to {LOG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
