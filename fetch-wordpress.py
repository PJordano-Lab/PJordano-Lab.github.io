#!/usr/bin/env python3
"""Mirror the WordPress blog (pedrojordano.wordpress.com) into the Quarto site.

For every published post this writes `blog/posts/<slug>/index.qmd` with the full
post body, downloads every image into `blog/posts/<slug>/images/` and rewrites
the HTML to point at the local copies, so the mirror does not depend on
WordPress staying online. A manifest at `data/wordpress_posts.json` records the
`modified` timestamp of each post; unchanged posts are skipped on later runs.

Usage:
    python fetch-wordpress.py            # incremental sync
    python fetch-wordpress.py --force    # re-render and re-download everything
    python fetch-wordpress.py --limit 5  # only the 5 most recent posts (testing)

The WordPress.com public REST API needs no authentication for a public blog.
A self-hosted WordPress works the same way with API_BASE pointed at
https://<yourdomain>/wp-json/wp/v2 instead.
"""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup

SITE = "pedrojordano.wordpress.com"
API_BASE = f"https://public-api.wordpress.com/wp/v2/sites/{SITE}"

ROOT = Path(__file__).resolve().parent
POSTS_DIR = ROOT / "blog" / "posts"
MANIFEST = ROOT / "data" / "wordpress_posts.json"

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "pjordano-lab-site-sync"
TIMEOUT = 60

# Image extensions we are willing to write into the repo.
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".avif"}


# --------------------------------------------------------------------------- #
# API helpers
# --------------------------------------------------------------------------- #
def get_json(path: str, **params):
    """GET one API endpoint, returning (payload, response)."""
    r = SESSION.get(f"{API_BASE}/{path}", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json(), r


def get_all(path: str, **params) -> list[dict]:
    """GET every page of a paginated collection endpoint."""
    out: list[dict] = []
    page = 1
    while True:
        payload, resp = get_json(path, per_page=100, page=page, **params)
        out.extend(payload)
        total_pages = int(resp.headers.get("X-WP-TotalPages", 1) or 1)
        if page >= total_pages:
            return out
        page += 1


def taxonomy_names(path: str) -> dict[int, str]:
    """Map term id -> human-readable name for categories or tags."""
    terms = get_all(path, _fields="id,name")
    return {t["id"]: html.unescape(t["name"]) for t in terms}


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #
def clean_text(raw_html: str) -> str:
    """Strip tags and decode entities: for titles and excerpts."""
    text = BeautifulSoup(raw_html or "", "html.parser").get_text(" ")
    text = html.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def safe_filename(url: str) -> str:
    """A repo-friendly filename derived from an image URL."""
    name = unquote(Path(urlparse(url).path).name)
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._").lower()
    return name or "image"


# --------------------------------------------------------------------------- #
# Image mirroring
# --------------------------------------------------------------------------- #
MAX_WIDTH = 1600  # set to None (--full-size) to archive the original uploads


def download_image(url: str, dest_dir: Path, force: bool) -> str | None:
    """Download one image into dest_dir, return its local filename."""
    # WordPress serves resized variants via a ?w= query string. Requesting a
    # web-sized one keeps the repo small; the originals (2-4 MB each) are only
    # fetched with --full-size.
    clean_url = url.split("?")[0]
    fetch_url = clean_url
    if MAX_WIDTH and Path(urlparse(clean_url).path).suffix.lower() != ".svg":
        fetch_url = f"{clean_url}?w={MAX_WIDTH}"
    fname = safe_filename(clean_url)
    stem, ext = Path(fname).stem, Path(fname).suffix.lower()
    if ext not in IMAGE_EXTS:
        ext = ""  # decided from Content-Type below
    dest_dir.mkdir(parents=True, exist_ok=True)

    if ext:
        target = dest_dir / f"{stem}{ext}"
        if target.exists() and not force:
            return target.name

    try:
        r = SESSION.get(fetch_url, timeout=TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as exc:
        print(f"    ! image failed {clean_url}: {exc}", file=sys.stderr)
        return None

    if not ext:
        ctype = (r.headers.get("Content-Type") or "").split(";")[0]
        ext = mimetypes.guess_extension(ctype) or ".jpg"
        if ext == ".jpe":
            ext = ".jpg"
        if ext not in IMAGE_EXTS:
            print(f"    ! not an image, skipped: {clean_url}", file=sys.stderr)
            return None
        target = dest_dir / f"{stem}{ext}"

    target.write_bytes(r.content)
    return target.name


def localise_media(content_html: str, post_url: str, post_dir: Path, force: bool) -> str:
    """Rewrite every <img>/image <a> in the post body to a local copy."""
    soup = BeautifulSoup(content_html or "", "html.parser")
    images_dir = post_dir / "images"
    cache: dict[str, str | None] = {}

    def local_for(url: str) -> str | None:
        absolute = urljoin(post_url, url)
        if not absolute.startswith(("http://", "https://")):
            return None
        if absolute not in cache:
            cache[absolute] = download_image(absolute, images_dir, force)
        return cache[absolute]

    for img in soup.find_all("img"):
        # Resolution variants and lazy-loading attributes would keep pointing
        # at WordPress, so they are removed rather than rewritten.
        for attr in ("srcset", "data-orig-file", "data-large-file",
                     "data-medium-file", "data-permalink", "sizes", "loading"):
            img.attrs.pop(attr, None)
        src = img.get("src") or img.get("data-src") or ""
        if not src:
            continue
        name = local_for(src)
        if name:
            img["src"] = f"images/{name}"

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if Path(urlparse(href).path).suffix.lower() in IMAGE_EXTS:
            name = local_for(href)
            if name:
                a["href"] = f"images/{name}"

    return str(soup)


# --------------------------------------------------------------------------- #
# Page writing
# --------------------------------------------------------------------------- #
def safe_slug(slug: str, post_id: int) -> str:
    """A URL- and Quarto-safe directory name for a post.

    WordPress slugs may contain accents or punctuation (e.g. a middle dot),
    which Quarto cannot resolve as link targets, so they are folded to ASCII.
    """
    s = unicodedata.normalize("NFKD", unquote(slug or "")).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or f"post-{post_id}"


def write_post(post: dict, cats: dict[int, str], tags: dict[int, str],
               force: bool) -> Path:
    slug = safe_slug(post["slug"], post["id"])
    post_dir = POSTS_DIR / slug
    post_dir.mkdir(parents=True, exist_ok=True)

    title = clean_text(post["title"]["rendered"]) or "(untitled)"
    excerpt = clean_text(post["excerpt"]["rendered"])
    if len(excerpt) > 300:
        excerpt = excerpt[:297].rsplit(" ", 1)[0] + "…"

    categories = [cats[c] for c in post.get("categories", []) if c in cats]
    categories += [tags[t] for t in post.get("tags", []) if t in tags]
    # De-duplicate while keeping order, and drop the catch-all category.
    seen, keywords = set(), []
    for c in categories:
        if c.lower() != "uncategorized" and c not in seen:
            seen.add(c)
            keywords.append(c)

    body = localise_media(post["content"]["rendered"], post["link"], post_dir, force)

    meta = {
        "title": title,
        "date": post["date"][:10],
        "author": "Pedro Jordano",
        "categories": keywords,
        "description": excerpt,
        "wp-id": post["id"],
        "wp-url": post["link"],
    }
    thumb_url = post.get("jetpack_featured_media_url") or ""
    if thumb_url:
        name = download_image(thumb_url, post_dir / "images", force)
        if name:
            meta["image"] = f"images/{name}"
            meta["image-alt"] = title
    if not meta["categories"]:
        meta.pop("categories")

    front = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False,
                           default_flow_style=False, width=10000)
    page = (
        "---\n"
        f"{front}"
        "---\n\n"
        "<!-- Generated by fetch-wordpress.py from "
        f"{post['link']} — do not edit by hand. -->\n\n"
        "```{=html}\n"
        f"{body}\n"
        "```\n\n"
        "::: {.wp-original}\n"
        f"Originally published on [my WordPress blog]({post['link']}).\n"
        ":::\n"
    )
    (post_dir / "index.qmd").write_text(page, encoding="utf-8")
    return post_dir


# --------------------------------------------------------------------------- #
def main() -> int:
    global MAX_WIDTH
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true",
                    help="re-render every post and re-download every image")
    ap.add_argument("--limit", type=int, default=None,
                    help="only sync the N most recent posts")
    ap.add_argument("--full-size", action="store_true",
                    help=f"archive original uploads instead of {MAX_WIDTH}px-wide copies")
    args = ap.parse_args()

    if args.full_size:
        MAX_WIDTH = None

    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    manifest = {}
    if MANIFEST.exists() and not args.force:
        try:
            manifest = {str(k): v for k, v in
                        json.loads(MANIFEST.read_text()).get("posts", {}).items()}
        except (json.JSONDecodeError, AttributeError):
            manifest = {}

    print(f"Reading {SITE} …")
    cats = taxonomy_names("categories")
    tags = taxonomy_names("tags")
    posts = get_all(
        "posts",
        status="publish",
        orderby="date",
        order="desc",
        _fields=("id,date,modified,slug,link,title,excerpt,content,"
                 "categories,tags,jetpack_featured_media_url"),
    )
    if args.limit:
        posts = posts[: args.limit]
    print(f"{len(posts)} published posts")

    written = skipped = 0
    for post in posts:
        key = str(post["id"])
        known = manifest.get(key, {})
        unchanged = known.get("modified") == post["modified"]
        slug = safe_slug(post["slug"], post["id"])
        if unchanged and (POSTS_DIR / slug / "index.qmd").exists():
            skipped += 1
        else:
            print(f"  + {post['date'][:10]} {slug}")
            write_post(post, cats, tags, args.force)
            written += 1
        manifest[key] = {
            "slug": slug,
            "date": post["date"],
            "modified": post["modified"],
            "title": clean_text(post["title"]["rendered"]),
            "url": post["link"],
        }

    live_slugs = {safe_slug(p["slug"], p["id"]) for p in posts}
    if not args.limit:
        for stale in sorted(POSTS_DIR.iterdir()):
            if stale.is_dir() and stale.name not in live_slugs:
                print(f"  ! {stale.name} is no longer published on WordPress "
                      f"(left in place; delete it manually if intended)")

    MANIFEST.write_text(
        json.dumps({"site": SITE, "count": len(posts),
                    "posts": dict(sorted(manifest.items(), key=lambda kv: int(kv[0])))},
                   indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Done: {written} written, {skipped} unchanged → {POSTS_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
