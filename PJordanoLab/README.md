# Pedro Jordano Lab — Hugo site

Hugo site generated from the live pages of <http://pjordanolab.ebd.csic.es/>, retrieved 2026-09-13.
Theme: [hugo-paper](https://github.com/nanxiaobei/hugo-paper), vendored at `themes/paper`.

## Build

    hugo server -D      # preview at http://localhost:1313
    hugo                # build into public/

Built and verified with Hugo v0.166.0+extended.

## Content

| File | Source page | Menu entry | KB |
|---|---|---|---|
| `content/_index.md` | `http://pjordanolab.ebd.csic.es/` | — (home) | 4.4 |
| `content/people.md` | `http://pjordanolab.ebd.csic.es/people/` | People | 13.5 |
| `content/papers.md` | `http://pjordanolab.ebd.csic.es/papers/` | Papers | 119.2 |
| `content/resources.md` | `http://pjordanolab.ebd.csic.es/resources/` | Resources | 3.8 |
| `content/projects.md` | `http://pjordanolab.ebd.csic.es/projects/` | Projects | 20.7 |
| `content/teaching.md` | `http://pjordanolab.ebd.csic.es/teaching/` | Teaching | 13.8 |
| `content/media.md` | `http://pjordanolab.ebd.csic.es/outreach/` | Media | 4.4 |
| `content/gallery.md` | `http://pjordanolab.ebd.csic.es/gallery/` | Gallery | 19.4 |
| `content/datasets.md` | `http://pjordanolab.ebd.csic.es/datasets/` | Datasets | 6.1 |
| `content/pedro.md` | `http://pjordanolab.ebd.csic.es/Pedro.html` | — (linked from People) | 2.6 |
| `content/papers-copy.md` | `http://pjordanolab.ebd.csic.es/page/` | — (draft, not built) | 117.6 |

`content/gallery.md` folds in the nine gallery sub-pages as `##` sections: Bird photos,
Networks, Megafauna fruits, *Prunus mahaleb*, Study Sites, Brazil, IEG, Art, Fruits & flowers.

`content/papers-copy.md` is the old site's `/page/` duplicate of the Papers page. It is kept
as `draft = true` so it is not published; delete it, or remove the draft flag, as you prefer.

## Images

All 690 images referenced by the imported pages were downloaded to `static/images/`
(67 MB) and every reference rewritten to a site-root path, so nothing points at the old
server. Filenames mirror their original server paths with `/` replaced by `__`
(e.g. `papers__files__thumbnail_image_0-536.png`), which keeps names unique across the
old site's several `files/` directories.

## Local customisations

- `hugo.toml` — `params.mainSections = []` suppresses the theme's blog post list, since this
  site is static pages rather than posts. `markup.goldmark.renderer.unsafe = true` is required
  because the imported pages carry inline HTML.
- `layouts/index.html` — site-level override. The theme's `_default/list.html` renders only a
  post list, which would leave the home page blank; this template renders `_index.md` instead.
- Navigation is defined per page via a `[menu.main]` block in each page's front matter.

## Two-column pages

`papers.md`, `papers-copy.md`, `projects.md`, `resources.md` and `datasets.md` use a
two-column layout: figures in the left column, text in the right column at a reduced size.
The other pages (home, People, Teaching, Media, Gallery, Pedro) are unchanged single-column.

This is implemented inside the `paper` theme rather than by switching themes, in three parts:

- `layouts/_default/twocolumn.html` — page template, selected per page with
  `layout = "twocolumn"` in the front matter. It loads the stylesheet below.
- `static/css/twocolumn.css` — a CSS grid, left column 34% / right column the remainder,
  collapsing to a single column under 720px. Text column is `0.8125rem`; full-width prose
  between rows is `0.875rem`, both below the theme's default body size. The page also widens
  the theme's `--w` from 744px to 1120px, since two columns do not fit the theme's default
  measure.
- `layouts/shortcodes/{row,figs,txt}.html` — the wrappers that mark up one row. Content uses
  the `{{%` ... `%}}` form so the text inside stays ordinary Markdown (links and
  emphasis still work).

### How the content was restructured

The imported pages carried three different markup shapes: `papers` paired each thumbnail with
its citation in a list item, `projects` put an entire section inside one list item, and
`resources`/`datasets` were flat sequences of paragraphs. No single CSS rule can pair a figure
with its text across all three, so the Markdown was regrouped instead. The old site's lists
were presentational containers only, so they were flattened, blocks were classified as
image-only or text, and each run of figures was grouped with the text that follows it into a
`row` shortcode. Result: 182 rows in `papers`, 181 in `papers-copy`, 15 in `projects`, 9 each
in `resources` and `datasets`. Three rows in each papers page are figure-only (thumbnail
strips on the old site that had no accompanying text); those keep the left-column width.

To restyle, edit `static/css/twocolumn.css`. To put a page back to one column, delete its
`layout = "twocolumn"` line — the `row`/`figs`/`txt` wrappers then render as plain stacked
blocks, so nothing breaks.

## Known issues

- Hugo prints one deprecation warning (`.Site.LanguageCode`). It originates in the theme's
  `layouts/partials/head.html`, not in this site's config, and is harmless until the theme updates.
- Non-image links (journal DOIs, external sites, PDFs under the old `/pdfs/` directory) remain
  absolute URLs to the old server. Those PDFs were not mirrored.
- Page content is a faithful conversion of the old pages' HTML. Expect to hand-tidy `people.md`
  if you want idiomatic Markdown.
- The two-column layout was verified structurally (row counts, figure/text pairing, image
  resolution, per-page scoping) but not visually: browsers cannot launch in the environment it
  was built in. Run `hugo server` and eyeball the column proportions and text size.
