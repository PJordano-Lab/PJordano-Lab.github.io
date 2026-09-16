# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Jekyll-based static academic website for Pedro Jordano (Research Professor, Estación Biológica de Doñana, CSIC, and Assoc. Professor, Univ. Sevilla), built with the [al-folio](https://github.com/alshedivat/al-folio) theme and deployed via GitHub Actions to https://pjordanolab.github.io.

## Commands

```bash
# Install Ruby dependencies
bundle install

# Preview locally with live reload
bundle exec jekyll serve

# Full build (renders to _site/)
bundle exec jekyll build
```

## Architecture

### Publication Pipeline

`open-alex.py` fetches publications from the OpenAlex API using ORCID `0000-0002-5108-9055`, writes data to:
- `_bibliography/papers.bib` — BibTeX file used by jekyll-scholar to render the publications page
- `data/publications.csv` — cached CSV for reference

The GitHub Actions workflow (`.github/workflows/update-publications.yml`) runs `python open-alex.py` automatically on the 1st and 15th of each month, then commits and pushes any changes.

### CV Pipeline

`cv/cv.Rmd` is the CV source (R Markdown using `stevetemplates`). To update the CV:
1. Edit `cv/cv.Rmd`
2. Run `Rscript cv/cv_render.R` to produce `cv/cv.pdf`
3. Copy to `assets/pdf/cv.pdf`
4. Commit and push both files

### Key Files

| File | Purpose |
|------|---------|
| `_config.yml` | Jekyll + al-folio config: social links, scholar settings, theme |
| `Gemfile` | Ruby dependencies |
| `_pages/about.md` | Home page with bio, education, positions |
| `_pages/publications.md` | Publications page (rendered from `papers.bib` via jekyll-scholar) |
| `_pages/cv.md` | CV page (links to `assets/pdf/cv.pdf`) |
| `_bibliography/papers.bib` | BibTeX publication list — auto-updated by `open-alex.py` |
| `assets/img/prof_pic.jpg` | Profile photo |
| `assets/pdf/cv.pdf` | CV PDF (manually updated) |
| `open-alex.py` | Fetches publications from OpenAlex; generates `papers.bib` + CSV |

### Dependencies

- **Ruby** 3.2+ with Bundler
- **Jekyll** 4.3 with al-folio remote theme
- **jekyll-scholar** for BibTeX rendering
- **Python**: `requests`, `pyyaml` (for publication sync)
- **R + TinyTeX**: only needed for CV PDF generation (not for site build)

## Deployment

The site deploys automatically via GitHub Actions:
- `.github/workflows/deploy.yml` — builds the Jekyll site and deploys to GitHub Pages on every push to `main`
- No manual build step needed — push to `main` and the site updates

### GitHub Pages Settings

In repository Settings > Pages, the source must be set to **GitHub Actions** (not "Deploy from a branch").

## Git Workflow

All changes to this repository must be committed and pushed to GitHub with clear, descriptive commit messages.

### Commit Message Guidelines

- Use the imperative mood: "Add feature" not "Added feature"
- Keep the first line under 72 characters
- Describe *what* changed and *why*, not *how*
- Examples:
  - `Update publications: sync from OpenAlex (2026-04-15)`
  - `Update CV to reflect new publications`
  - `Fix about page bio text`

### Push Workflow

```bash
git add <file1> <file2>
git commit -m "Short descriptive message"
git push
```

### Important Rules

- **Always push** after committing — local-only commits are not deployed
- **Never force-push** to `main` without explicit confirmation
- **Never skip hooks** (`--no-verify`) unless explicitly requested
