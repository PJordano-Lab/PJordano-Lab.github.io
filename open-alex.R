# scripts/fetch_openalex.R

library(httr)
library(jsonlite)
library(dplyr)
library(purrr)

# Your OpenAlex Author ID
author_id <- "a5058629427"  # Replace with your ID

fetch_openalex_publications <- function(author_id, email = NULL) {
  # OpenAlex appreciates a polite email in requests
  base_url <- "https://api.openalex.org/works"
  
  query_params <- list(
    filter = paste0("author.id:", author_id),
    per_page = 200,
    sort = "publication_date:desc"
  )
  
  if (!is.null(email)) {
    query_params$mailto <- email
  }
  
  response <- GET(base_url, query = query_params)
  
  if (status_code(response) != 200) {
    stop("Failed to fetch data from OpenAlex: ", status_code(response))
  }
  
  data <- fromJSON(content(response, "text", encoding = "UTF-8"))
  
  # Extract comprehensive publication info
  pubs <- data$results %>%
    mutate(
      # Basic info
      title = display_name,
      year = publication_year,
      publication_date = publication_date,
      type = type,
      
      # Venue info
      journal = primary_location$source$display_name %||% NA_character_,
      publisher = primary_location$source$host_organization_name %||% NA_character_,
      is_oa = primary_location$is_oa %||% FALSE,
      
      # Identifiers
      doi = doi,
      openalex_id = id,
      pmid = if("pmid" %in% names(ids)) ids$pmid else NA_character_,
      
      # URLs
      doi_url = ifelse(!is.null(doi), paste0("https://doi.org/", gsub("https://doi.org/", "", doi)), NA_character_),
      pdf_url = if(!is.null(primary_location$pdf_url)) primary_location$pdf_url else 
        if(!is.null(best_oa_location$pdf_url)) best_oa_location$pdf_url else NA_character_,
      
      # Authors
      authors = map_chr(authorships, function(a) {
        paste(a$author$display_name, collapse = ", ")
      }),
      author_count = map_int(authorships, nrow),
      
      # Metrics
      cited_by_count = cited_by_count %||% 0) %>% 
      
    #   # Abstract
    #   abstract = if("abstract_inverted_index" %in% names(.)) {
    #     map_chr(abstract_inverted_index, function(inv_idx) {
    #       if(is.null(inv_idx) || length(inv_idx) == 0) return(NA_character_)
    #       # Reconstruct abstract from inverted index
    #       words <- names(inv_idx)
    #       positions <- unlist(inv_idx)
    #       if(length(words) == 0) return(NA_character_)
    #       sorted <- words[order(positions)]
    #       paste(sorted, collapse = " ")
    #     })
    #   } else NA_character_
    # ) %>%
    select(title, authors, author_count, year, publication_date, 
           journal, publisher, type, is_oa, 
           doi, doi_url, pdf_url, openalex_id, pmid,
           cited_by_count) %>%
    arrange(desc(year), desc(publication_date))
  
  return(pubs)
}

# Helper function for NULL coalescing
`%||%` <- function(a, b) if (is.null(a)) b else a
