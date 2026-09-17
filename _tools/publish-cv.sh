#!/usr/bin/env bash
# Copy the built CV into the rendered site.
#
# This used to be an inline post-render command in _quarto.yml:
#
#     post-render:
#       - "mkdir -p docs/cv && cp cv/cv.pdf docs/cv/cv.pdf"
#
# Quarto does not run post-render strings through a shell, so the `&&` was not
# a command separator: `mkdir -p` received every following word as a path to
# create - including `docs/cv/cv.pdf` - and the `cp` never ran. On a machine
# where docs/cv/cv.pdf already existed, mkdir failed harmlessly and the file
# survived, which is why local renders looked fine. In CI the checkout's copy
# is cleaned before that point, so the render published an empty DIRECTORY
# named cv.pdf; GitHub Pages redirects a directory to its trailing-slash URL
# and then returns 404 - the /cv/cv.pdf/ 404.
#
# A script is executed as a program, so the logic here is shell-interpreted
# and the failure mode cannot come back.
set -euo pipefail

src="cv/cv.pdf"
dst="docs/cv/cv.pdf"

if [ ! -f "$src" ]; then
    echo "publish-cv: $src is missing - the CV will not be published." >&2
    echo "publish-cv: render cv/cv.Rmd (Rscript cv/cv_render.R) or restore the file." >&2
    exit 1
fi

# self-heal: an earlier broken render may have left a directory at the target
if [ -d "$dst" ]; then
    echo "publish-cv: removing stale directory at $dst"
    rm -rf "$dst"
fi

mkdir -p "$(dirname "$dst")"
cp "$src" "$dst"

# a regular file, non-empty, and byte-identical to the source
test -f "$dst"
cmp -s "$src" "$dst"
echo "publish-cv: $dst ($(wc -c < "$dst" | tr -d ' ') bytes)"
