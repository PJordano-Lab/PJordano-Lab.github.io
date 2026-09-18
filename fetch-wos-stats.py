#!/usr/bin/env python3
"""
Fetch Web of Science (Clarivate) statistics and save to a YAML file for Quarto
integration. Companion to fetch-scholar-stats.py.

Unlike Google Scholar, the Web of Science author record page
(https://www.webofscience.com/wos/author/record/<RID>) is an Angular
application behind Clarivate authentication: an HTTP GET returns an empty
shell, so it cannot be parsed with requests + BeautifulSoup. The data is taken
instead from the Web of Science Starter API, which returns one record per
document with its Core Collection times-cited count; the summary indicators
(total citations, h-index, i10-index) are computed here from those counts.

Setup
-----
1. Register for a free key at https://developer.clarivate.com (Web of Science
   Starter API). The key is tied to your institutional WoS subscription.
2. Make it available to the script in ONE of these ways (checked in order):
     - export WOS_API_KEY=...            (shell / CI secret)
     - a line  WOS_API_KEY=...           in ./.Renviron or ~/.Renviron
   The key is never written to the repository: .Renviron is gitignored and
   only the computed indicators land in data/wos_stats.yml.

Usage
-----
    python3 fetch-wos-stats.py
"""

import os
import re
import time
from datetime import datetime
from pathlib import Path

import requests
import yaml

API_BASE = "https://api.clarivate.com/apis/wos-starter/v1"
# Starter API hard limit per page; the loop below pages through all records.
PAGE_LIMIT = 50


def read_api_key():
    """Resolve the Starter API key from the environment or an .Renviron file."""
    key = os.environ.get("WOS_API_KEY", "").strip()
    if key:
        return key

    for candidate in (Path(".Renviron"), Path.home() / ".Renviron"):
        try:
            if not candidate.is_file():
                continue
            lines = candidate.read_text(encoding="utf-8").splitlines()
        except OSError:
            # Unreadable or restricted path: fall through to the next candidate.
            continue
        for line in lines:
            m = re.match(r"\s*WOS_API_KEY\s*=\s*['\"]?([^'\"#\s]+)", line)
            if m:
                return m.group(1)
    return None


class WebOfScienceStats:
    def __init__(self, researcher_id, api_key=None, db="WOS"):
        self.researcher_id = researcher_id
        self.api_key = api_key or read_api_key()
        self.db = db
        self.stats = {}
        self.records = []

    # ------------------------------------------------------------------ fetch
    def fetch_stats(self):
        """Fetch all indexed documents for the ResearcherID and summarise them."""
        if not self.api_key:
            print("Error: no Web of Science API key found.\n"
                  "Set WOS_API_KEY in the environment or in .Renviron "
                  "(see the module docstring).")
            return False

        # AI = Author Identifiers (ResearcherID / ORCID) in WoS query syntax.
        query = f"AI=({self.researcher_id})"
        headers = {"X-ApiKey": self.api_key, "Accept": "application/json"}

        self.records = []
        page = 1
        total = None

        try:
            while True:
                params = {"q": query, "db": self.db,
                          "limit": PAGE_LIMIT, "page": page}
                response = requests.get(f"{API_BASE}/documents",
                                        headers=headers, params=params,
                                        timeout=60)
                if response.status_code in (401, 403):
                    print(f"Error: Web of Science API rejected the key "
                          f"(HTTP {response.status_code}). Check WOS_API_KEY "
                          f"and that your subscription covers the Starter API.")
                    return False
                response.raise_for_status()
                payload = response.json()

                hits = payload.get("hits", []) or []
                self.records.extend(hits)

                if total is None:
                    total = int(payload.get("metadata", {}).get("total", 0))
                    print(f"  {total} records indexed for {self.researcher_id}")

                if not hits or len(self.records) >= total:
                    break
                page += 1
                # Starter API free tier is rate limited; stay well inside it.
                time.sleep(1)

        except requests.RequestException as e:
            print(f"Error fetching Web of Science records: {e}")
            return False

        if not self.records:
            print("Error: the API returned no records. Verify the ResearcherID "
                  "and that the profile is public.")
            return False

        return self.summarise()

    # -------------------------------------------------------------- summarise
    def _citation_count(self, record):
        """Times-cited count for one record, defensively extracted."""
        citations = record.get("citations")
        if isinstance(citations, list):
            # [{"db": "WOS", "count": 42}, ...] — prefer the requested database.
            for entry in citations:
                if isinstance(entry, dict) and entry.get("db") == self.db:
                    return int(entry.get("count") or 0)
            for entry in citations:
                if isinstance(entry, dict) and entry.get("count") is not None:
                    return int(entry["count"])
        elif isinstance(citations, dict):
            return int(citations.get("count") or 0)
        elif isinstance(citations, (int, float)):
            return int(citations)
        return 0

    def summarise(self):
        """Compute the summary indicators from the per-record citation counts."""
        counts = sorted((self._citation_count(r) for r in self.records),
                        reverse=True)

        # h-index: largest h with at least h papers cited >= h times.
        h_index = 0
        for i, c in enumerate(counts, start=1):
            if c >= i:
                h_index = i
            else:
                break

        years = [r.get("source", {}).get("publishYear") for r in self.records]
        years = sorted(int(y) for y in years if y)

        self.stats = {
            "researcher_id": self.researcher_id,
            "database": self.db,
            "documents": len(counts),
            "citations_all": sum(counts),
            "citations_per_item": round(sum(counts) / len(counts), 2) if counts else 0,
            "h_index_all": h_index,
            "i10_index_all": sum(1 for c in counts if c >= 10),
            "cited_documents": sum(1 for c in counts if c > 0),
            "first_year": years[0] if years else None,
            "last_year": years[-1] if years else None,
            "profile_url": (f"https://www.webofscience.com/wos/author/record/"
                            f"{self.researcher_id}"),
            "source": "Web of Science Starter API (Core Collection)",
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        return True

    # ------------------------------------------------------------------- save
    def save_to_yaml(self, output_path):
        """Save statistics to a YAML file"""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w", encoding="utf-8") as f:
            yaml.dump(self.stats, f, default_flow_style=False, sort_keys=False,
                      allow_unicode=True)

        print(f"✓ Saved Web of Science stats to {output_file}")
        return output_file

    def print_stats(self):
        """Print statistics to console"""
        if not self.stats:
            print("No statistics available. Run fetch_stats() first.")
            return

        s = self.stats
        print("\n" + "=" * 60)
        print("WEB OF SCIENCE STATISTICS")
        print("=" * 60)
        print(f"\nResearcherID: {s['researcher_id']}  ({s['database']})")
        if s.get("first_year"):
            print(f"Publication years: {s['first_year']}–{s['last_year']}")

        print(f"\n{'Metric':<24} {'Value':<15}")
        print("-" * 60)
        print(f"{'Documents':<24} {s['documents']:<15}")
        print(f"{'Citations':<24} {s['citations_all']:<15}")
        print(f"{'Citations per item':<24} {s['citations_per_item']:<15}")
        print(f"{'h-index':<24} {s['h_index_all']:<15}")
        print(f"{'i10-index':<24} {s['i10_index_all']:<15}")
        print(f"{'Cited documents':<24} {s['cited_documents']:<15}")
        print(f"\nLast Updated: {s['last_updated']}")
        print("=" * 60 + "\n")


def main():
    # ResearcherID from https://www.webofscience.com/wos/author/record/A-5162-2008
    researcher_id = "A-5162-2008"

    print("Fetching Web of Science statistics...")

    wos = WebOfScienceStats(researcher_id)

    if wos.fetch_stats():
        wos.print_stats()
        wos.save_to_yaml("data/wos_stats.yml")
        print("✓ Web of Science stats successfully fetched and saved!")
        return True

    print("✗ Failed to fetch Web of Science statistics")
    return False


if __name__ == "__main__":
    main()
