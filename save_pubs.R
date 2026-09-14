source("open-alex.R")

# Configuration
AUTHOR_ID <- "a5024471517"  # Replace with your OpenAlex ID
EMAIL <- "sbwatts@txstate.edu"  # Optional but recommended
CACHE_FILE <- "data/publications.rds"

# Create data directory if it doesn't exist
if (!dir.exists("data")) {
  dir.create("data")
}

# Fetch and save
pubs <- fetch_openalex_publications(AUTHOR_ID, EMAIL)
saveRDS(pubs, CACHE_FILE)

# Also save as CSV for backup/inspection
write.csv(pubs, "data/publications.csv", row.names = FALSE)

cat("Fetched", nrow(pubs), "publications\n")
cat("Saved to", CACHE_FILE, "\n")