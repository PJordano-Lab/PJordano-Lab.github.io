#!/usr/bin/env python3
"""Convert the legacy Hugo pages in content/*.md into top-level Quarto pages.

Rewrites Hugo-era paths to project-relative ones and drops Hugo-only front
matter keys. Run from the project root:  python _tools/convert-hugo-content.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"

# content/<name>.md -> <target>.qmd
PAGES = {
    "projects": "projects",
    "people": "people",
    "resources": "resources",
    "datasets": "datasets",
    "gallery": "gallery",
    "media": "media",
    "teaching": "teaching",
    "pedro": "pedro",
    "papers-figures": "papers-figures",
}

# Hugo pretty-URL links -> rendered Quarto pages
LINK_MAP = {
    "/gallery/": "gallery.html",
    "/pedro/": "pedro.html",
    "/teaching/": "teaching.html",
    "/projects/": "projects.html",
    "/datasets/": "datasets.html",
    "/people/": "people.html",
    "/papers/": "research.html",
    "/resources/": "resources.html",
}

DROP_FRONTMATTER_KEYS = {"hideMeta", "centerImages", "draft", "weight", "layout"}


def split_frontmatter(text):
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, parts[2].lstrip("\n")


def fix_paths(body):
    body = body.replace("](../static/", "](static/")
    body = body.replace('="../static/', '="static/')
    body = body.replace("](/pdfs/", "](static/pdfs/")
    body = body.replace("](/images/", "](static/images/")
    for hugo, page in LINK_MAP.items():
        body = body.replace(f"]({hugo}", f"]({page}")
    return drop_missing_images(body)


def drop_missing_images(body):
    """Remove ![...](static/...) references whose file was never migrated.

    The legacy site used small decorative bullet/arrow GIFs that are absent
    from static/images; leaving them in produces broken-image icons.
    """
    def repl(match):
        target = match.group(1).split()[0].strip('"\'')
        return "" if not (ROOT / target).exists() else match.group(0)

    return re.sub(r"!\[[^\]]*\]\((static/[^)]+)\)", repl, body)


def main():
    for src_name, out_name in PAGES.items():
        src = CONTENT / f"{src_name}.md"
        if not src.exists():
            print(f"skip (missing): {src}")
            continue
        meta, body = split_frontmatter(src.read_text(encoding="utf-8"))
        body = fix_paths(body)

        keep = {k: v for k, v in meta.items() if k not in DROP_FRONTMATTER_KEYS}
        keep.setdefault("title", f'"{out_name.title()}"')
        fm = ["---"]
        for k, v in keep.items():
            fm.append(f"{k}: {v}")
        fm += ['title-block-banner: "#1a1c20"', "---", ""]

        out = ROOT / f"{out_name}.qmd"
        if out.exists() and "hand-edited: true" in out.read_text(encoding="utf-8"):
            print(f"skip (hand-edited): {out.relative_to(ROOT)}")
            continue
        out.write_text("\n".join(fm) + "\n" + body.strip() + "\n", encoding="utf-8")
        print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
