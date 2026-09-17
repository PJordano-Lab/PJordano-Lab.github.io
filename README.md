# pjordanolab.github.io

Personal academic website for Pedro Jordano — Research Professor, Estación Biológica de Doñana, CSIC, and Assoc. Professor, Univ. Sevilla.

Built with [Quarto](https://quarto.org/), deployed via [GitHub Actions](https://github.com/features/actions) to GitHub Pages.

**Live site:** [https://pjordanolab.github.io](https://pjordanolab.github.io)
## Project Structure

```
├── index.qmd                  # Home page (hero + recent publications)
├── about.qmd                  # Bio, education, positions
├── research.qmd               # Publications listing
├── projects/
│   ├── truleo.qmd             # Projects page
│   └── orp.qmd                # Project page example
├── teaching/
│   └── cj-4310/               # Talks and courses
├── research/
│   ├── articles/              # Individual published article pages (auto-generated)
│   └── working-papers/        # Working paper pages
├── cv/
│   ├── cv.Rmd                 # CV source (R Markdown)
│   ├── cv_render.R            # CV rendering script
│   └── cv.pdf                 # Built CV (committed)
├── data/
│   ├── publications.csv       # Publications data from OpenAlex
│   └── scholar_stats.yml      # Google Scholar citation stats
├── _bibliography/
│   └── papers.bib             # BibTeX publication list (auto-updated by open-alex.py)
├── styles.css                 # Custom CSS (design tokens, dark mode, components)
├── _quarto.yml                # Quarto config: navbar, theme, output dir
├── open-alex.py               # Fetches publications from OpenAlex API
├── save_pubs.R                # Generates individual article pages from publications.csv
├── headshot.jpeg              # Profile photo
├── CNAME                      # Custom domain for GitHub Pages
└── .github/workflows/
    ├── deploy.yml             # Renders and deploys site on push to main
    └── update-publications.yml # Auto-syncs publications on the 1st and 15th
```

## Local Development

### Prerequisites

- [Quarto](https://quarto.org/docs/get-started/) 1.4+
- [R](https://www.r-project.org/) with `yaml` package
- [Python 3](https://www.python.org/) with packages: `requests`, `pyyaml`

### Preview locally

```bash
quarto preview
```

The site will be available at `http://localhost:4848` with live reload.

### Full build

```bash
quarto render
```

Output goes to `docs/` (committed and served by GitHub Pages).

## Publication Pipeline

Publications are managed through two layers:

1. **Auto-sync** (`open-alex.py`): Fetches the latest publications from the [OpenAlex API](https://openalex.org/) using ORCID `0000-0002-5108-9055`, then writes `data/publications.csv` and `_bibliography/papers.bib`, and generates/removes individual article pages under `research/articles/` and `research/working-papers/`.

2. **Manual pages**: Publication pages not returned by OpenAlex (e.g., works not claimed under your ORCID) are tracked in git and preserved. To add OpenAlex coverage for missing works, claim them at [openalex.org](https://openalex.org/).

To manually sync publications locally:

```bash
python open-alex.py
```

The GitHub Actions workflow (`.github/workflows/update-publications.yml`) runs this automatically on the 1st and 15th of each month, then commits and pushes any changes to `data/`.

## WordPress Blog Mirror

The blog at <https://pedrojordano.wordpress.com/> is mirrored into this site, so
every post is readable at `/blog.html` with the site's own design and is indexed
by the site search. Nothing has to be installed on the WordPress side: the
mirror reads the public WordPress.com REST API.

`fetch-wordpress.py` writes one page per post at `blog/posts/<slug>/index.qmd`
(full body, title, date, categories, excerpt), downloads every post image into
`blog/posts/<slug>/images/` at 1600 px wide and rewrites the `<img>` tags to the
local copies, so the archive keeps working if the WordPress blog ever goes away.
Each page links back to its original.

```bash
python fetch-wordpress.py              # incremental: only new or edited posts
python fetch-wordpress.py --force      # re-render all posts, re-download images
python fetch-wordpress.py --limit 5    # 5 most recent posts only (testing)
python fetch-wordpress.py --full-size  # archive original uploads (2-4 MB each)
```

`data/wordpress_posts.json` is the sync manifest (post id, slug and `modified`
time); unchanged posts are skipped. A post unpublished on WordPress is reported
but never deleted automatically. Generated pages carry a "do not edit" comment:
edit the post on WordPress and re-sync.

The listing page is `blog.qmd` (date-sorted, category cloud, sort/filter UI and
an RSS feed at `/blog.xml`), presentation defaults for posts live in
`blog/posts/_metadata.yml`, and the imported WordPress block markup is styled at
the end of `html/pedroj.scss`.

`.github/workflows/update-blog.yml` runs the sync every Monday and Thursday (or
on demand from the Actions tab), commits what changed and triggers a rebuild.

To mirror a different or self-hosted blog, change `SITE`/`API_BASE` at the top
of `fetch-wordpress.py` — a self-hosted WordPress exposes the same API at
`https://yourdomain/wp-json/wp/v2`.

## CV Updates

The CV is a PDF generated from `cv/cv.Rmd` using R and TinyTeX. To update:

1. Edit `cv/cv.Rmd`
2. Run `Rscript cv/cv_render.R` to produce `cv/cv.pdf`
3. Commit and push `cv/cv.pdf`

## Deployment

The site deploys automatically via GitHub Actions:

- **`deploy.yml`** — Installs Quarto + R, runs `quarto render`, and deploys `docs/` to GitHub Pages on every push to `main`.
- No manual build step needed — push to `main` and the site updates.

### GitHub Pages settings required

In repository Settings > Pages:
- **Source**: GitHub Actions
