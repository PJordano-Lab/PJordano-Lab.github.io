# cv/render_cv.R
rmarkdown::render(
  input = "cv/cv.Rmd",
  output_file = "cv.pdf",
  quiet = TRUE
)
