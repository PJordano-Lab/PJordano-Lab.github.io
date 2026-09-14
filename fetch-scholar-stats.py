#!/usr/bin/env python3
"""
Fetch Google Scholar statistics and save to a YAML file for Quarto integration.
"""

import requests
from bs4 import BeautifulSoup
import yaml
from pathlib import Path
import time
import re

class GoogleScholarStats:
    def __init__(self, user_id):
        self.user_id = user_id
        self.base_url = "https://scholar.google.com/citations"
        self.stats = {}

    def fetch_stats(self):
        """Fetch statistics from Google Scholar profile"""
        url = f"{self.base_url}?user={self.user_id}&hl=en"

        # Add headers to mimic a browser request
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Silicon Mac OS X 27) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # Extract citation stats
            stats_table = soup.find('table', {'id': 'gsc_rsb_st'})
            if stats_table:
                rows = stats_table.find_all('tr')

                # First row: Citations
                citations_row = rows[1] if len(rows) > 1 else None
                if citations_row:
                    cells = citations_row.find_all('td')
                    if len(cells) >= 2:
                        self.stats['citations_all'] = cells[1].text.strip()
                        self.stats['citations_since_2019'] = cells[2].text.strip() if len(cells) > 2 else 'N/A'

                # Second row: h-index
                h_index_row = rows[2] if len(rows) > 2 else None
                if h_index_row:
                    cells = h_index_row.find_all('td')
                    if len(cells) >= 2:
                        self.stats['h_index_all'] = cells[1].text.strip()
                        self.stats['h_index_since_2019'] = cells[2].text.strip() if len(cells) > 2 else 'N/A'

                # Third row: i10-index
                i10_index_row = rows[3] if len(rows) > 3 else None
                if i10_index_row:
                    cells = i10_index_row.find_all('td')
                    if len(cells) >= 2:
                        self.stats['i10_index_all'] = cells[1].text.strip()
                        self.stats['i10_index_since_2019'] = cells[2].text.strip() if len(cells) > 2 else 'N/A'

            # Extract name
            name_elem = soup.find('div', {'id': 'gsc_prf_in'})
            if name_elem:
                self.stats['name'] = name_elem.text.strip()

            # Extract affiliation
            affiliation_elem = soup.find('div', {'class': 'gsc_prf_il'})
            if affiliation_elem:
                self.stats['affiliation'] = affiliation_elem.text.strip()

            # Extract interests
            interests_container = soup.find('div', {'id': 'gsc_prf_int'})
            if interests_container:
                interests = []
                for interest in interests_container.find_all('a', {'class': 'gsc_prf_inta'}):
                    interests.append(interest.text.strip())
                self.stats['interests'] = interests

            # Get the profile URL
            self.stats['profile_url'] = url

            # Add fetch timestamp
            from datetime import datetime
            self.stats['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            return True

        except requests.RequestException as e:
            print(f"Error fetching Google Scholar profile: {e}")
            return False
        except Exception as e:
            print(f"Error parsing Google Scholar data: {e}")
            return False

    def save_to_yaml(self, output_path):
        """Save statistics to a YAML file"""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w') as f:
            yaml.dump(self.stats, f, default_flow_style=False, sort_keys=False)

        print(f"✓ Saved Google Scholar stats to {output_file}")
        return output_file

    def print_stats(self):
        """Print statistics to console"""
        if not self.stats:
            print("No statistics available. Run fetch_stats() first.")
            return

        print("\n" + "="*60)
        print("GOOGLE SCHOLAR STATISTICS")
        print("="*60)

        if 'name' in self.stats:
            print(f"\nName: {self.stats['name']}")
        if 'affiliation' in self.stats:
            print(f"Affiliation: {self.stats['affiliation']}")

        print(f"\n{'Metric':<20} {'All Time':<15} {'Since 2019':<15}")
        print("-" * 60)
        print(f"{'Citations':<20} {self.stats.get('citations_all', 'N/A'):<15} {self.stats.get('citations_since_2019', 'N/A'):<15}")
        print(f"{'h-index':<20} {self.stats.get('h_index_all', 'N/A'):<15} {self.stats.get('h_index_since_2019', 'N/A'):<15}")
        print(f"{'i10-index':<20} {self.stats.get('i10_index_all', 'N/A'):<15} {self.stats.get('i10_index_since_2019', 'N/A'):<15}")

        if 'interests' in self.stats and self.stats['interests']:
            print(f"\nResearch Interests: {', '.join(self.stats['interests'])}")

        if 'last_updated' in self.stats:
            print(f"\nLast Updated: {self.stats['last_updated']}")

        print("="*60 + "\n")


def main():
    # Your Google Scholar user ID
    user_id = "TrKYqaEAAAAJ"

    print("Fetching Google Scholar statistics...")

    # Create instance and fetch stats
    scholar = GoogleScholarStats(user_id)

    if scholar.fetch_stats():
        # Print to console
        scholar.print_stats()

        # Save to YAML file
        output_path = "data/scholar_stats.yml"
        scholar.save_to_yaml(output_path)

        print(f"✓ Google Scholar stats successfully fetched and saved!")
        return True
    else:
        print("✗ Failed to fetch Google Scholar statistics")
        return False


if __name__ == "__main__":
    main()
