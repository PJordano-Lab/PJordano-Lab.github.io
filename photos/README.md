# photos/

Source images for the `andrewheiss/photo-gallery` extension, one flat folder
per gallery group. `gallery.qmd` renders them with

```
{{< photo-gallery photos/<group> id=<group> >}}
```

## Layout

```
photos/<group>/
  <tag>-001.jpg     originals, served full size by the lightbox
  album.yml         optional per-image metadata
  thumbs/           written by the extension on render (git-ignored)
```

Keep images directly in the group folder — the extension does not recurse.

## album.yml

```yaml
images:
  fruits-001.jpg:
    title: "Corema album"
    description: "Doñana, Huelva."
    alt: "Corema album. Doñana, Huelva."
    date: 2004-03-12      # only when you need to override EXIF
```

`title`, `description` and `alt` override whatever the file carries; `date`
overrides the EXIF capture date. Camera, lens focal length, aperture, shutter
and ISO always come from EXIF and are not settable here.

## Adding photos

Copy JPEGs in (any filename), add entries to `album.yml` if you want captions,
and render. The extension regenerates a thumbnail whenever the source is newer
than the existing one.

## Where these files came from, and what is missing

Every image here is a **web-resized export** (300-800 px), because that is all
the repo and the readable parts of `~/Pictures` contain. `_tools/photo-origins.csv`
records, per photo, whether a copy was found in the Pictures archives and at
what scale:

| outcome | photos |
|---|---|
| not in the accessible archives | 430 |
| present, but the same size as the web copy | 133 |
| replaced with a genuinely larger original | 3 |
| hash matched but colour check rejected it | 1 |

The full-resolution originals are not reachable: `Photos Library.photoslibrary`
denies reads (macOS privacy protection) and `LRC-Transfer` holds 2026 RAW
captures, long after these galleries were made. To get real EXIF-rich files
into the lightbox, export originals out of Photos or Lightroom into a plain
folder and re-run:

    python _tools/resource-originals.py --search /path/to/exported_originals

## Regenerating the tree

`python _tools/build-photo-gallery.py --out /tmp/photos_stage` rebuilds the folders from the export
sets under `static/images/{galleries,newgalleries}` and rewrites `gallery.qmd`.
It only deletes files matching its own `<tag>-NNN.ext` naming, so photos you
add by hand survive a re-run. It also:

* flattens RGBA/palette images to RGB JPEG — the extension always writes
  thumbnails as JPEG and raises on an RGBA source;
* skips truncated files rather than letting them break the render;
* repairs EXIF blocks that PIL can read but `piexif` (which the extension
  uses) rejects, and strips zeroed `0000:00:00` timestamps.

**Build into a staging path outside iCloud** (`--out /tmp/photos_stage`) and
copy the result in one pass. Rebuilding in place under `~/Documents` makes
iCloud produce sync-conflict duplicates (`art-001 2.jpg`) for every
delete-then-rewrite cycle; a first attempt left 2,880 of them.

Defaults for thumbnail size, layout and which EXIF fields to show live under
`extensions: photo-gallery:` in `gallery.qmd`'s front matter — not at the
document root, which the extension ignores.
