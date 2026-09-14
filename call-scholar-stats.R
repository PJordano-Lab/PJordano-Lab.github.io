# Accented affiliations (Estación Biológica de Doñana) crash the embedded
# interpreter if stdout defaults to ASCII under Rscript.
Sys.setenv(PYTHONIOENCODING = "utf-8")

library(reticulate)

# reticulate otherwise picks a project .venv that does not exist here, and the
# fallback interpreter lacks pyyaml/bs4. Use the python3 on PATH (override with
# RETICULATE_PYTHON) and check the dependencies up front.
py_bin <- Sys.getenv("RETICULATE_PYTHON", unset = unname(Sys.which("python3")))
if (!nzchar(py_bin)) stop("No python3 found; set RETICULATE_PYTHON.")
use_python(py_bin, required = TRUE)

missing <- Filter(function(m) !py_module_available(m),
                  c("requests", "yaml", "bs4"))
if (length(missing)) {
  stop(sprintf("%s is missing: %s\nInstall with: %s -m pip install -r requirements.txt",
               py_bin, paste(missing, collapse = ", "), py_bin))
}

# Source the Python file
source_python("fetch-scholar-stats.py")

# Create instance and fetch stats
scholar <- GoogleScholarStats("TrKYqaEAAAAJ")

# Fetch and save stats
if (scholar$fetch_stats()) {
  scholar$print_stats()
  scholar$save_to_yaml("data/scholar_stats.yml")
  cat("✓ Google Scholar stats successfully fetched and saved!\n")
} else {
  cat("✗ Failed to fetch Google Scholar statistics\n")
}
