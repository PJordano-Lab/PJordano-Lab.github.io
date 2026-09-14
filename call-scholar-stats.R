library(reticulate)

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
