# Refresh data/wos_stats.yml from the Web of Science Starter API.
# Companion to call-scholar-stats.R; see fetch-wos-stats.py for the API key
# setup (WOS_API_KEY in the environment or in .Renviron).

Sys.setenv(PYTHONIOENCODING = "utf-8")

library(reticulate)

# reticulate otherwise picks a project .venv that does not exist here, and the
# fallback interpreter lacks pyyaml. Use the python3 on PATH (override with
# RETICULATE_PYTHON) and check the dependencies up front.
py_bin <- Sys.getenv("RETICULATE_PYTHON", unset = unname(Sys.which("python3")))
if (!nzchar(py_bin)) stop("No python3 found; set RETICULATE_PYTHON.")
use_python(py_bin, required = TRUE)

missing <- Filter(function(m) !py_module_available(m),
                  c("requests", "yaml"))
if (length(missing)) {
  stop(sprintf("%s is missing: %s\nInstall with: %s -m pip install -r requirements.txt",
               py_bin, paste(missing, collapse = ", "), py_bin))
}

# R reads .Renviron at startup, Python does not inherit it automatically, so
# pass the key through explicitly when it is set there.
wos_key <- Sys.getenv("WOS_API_KEY")
if (nzchar(wos_key)) Sys.setenv(WOS_API_KEY = wos_key)

source_python("fetch-wos-stats.py")

wos <- WebOfScienceStats("A-5162-2008")

if (wos$fetch_stats()) {
  wos$print_stats()
  wos$save_to_yaml("data/wos_stats.yml")
  cat("✓ Web of Science stats successfully fetched and saved!\n")
} else {
  cat("✗ Failed to fetch Web of Science statistics\n")
  cat("  Get a key at https://developer.clarivate.com and set WOS_API_KEY.\n")
}
