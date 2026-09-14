import requests
import csv
import re
import time
from pathlib import Path
from datetime import datetime

try:
    import yaml
except ImportError:
    yaml = None


class OpenAlexArticleSync:
    def __init__(self, bibtex_path="_bibliography/papers.bib"):
        self.base_url = "https://api.openalex.org"
        self.bibtex_path = Path(bibtex_path)
        self.bibtex_path.parent.mkdir(parents=True, exist_ok=True)

    def fetch_author_works(self, author_name=None, orcid=None, limit=50):
        """Fetch works by author from OpenAlex"""
        if orcid:
            url = f"{self.base_url}/works"
            params = {
                'filter': f'author.orcid:{orcid}',
                'per-page': limit,
                'sort': 'publication_date:desc',
                'mailto': 'jordano@ebd.csic.es'
            }
        elif author_name:
            url = f"{self.base_url}/works"
            params = {
                'filter': f'author.search:{author_name}',
                'per-page': limit,
                'sort': 'publication_date:desc',
                'mailto': 'jordano@ebd.csic.es'
            }
        else:
            raise ValueError("Must provide either author_name or orcid")

        print(f"Fetching works from OpenAlex...")
        response = requests.get(url, params=params)
        response.raise_for_status()

        data = response.json()
        works = data.get('results', [])

        print(f"Found {len(works)} works")
        return self._parse_works(works)

    def fetch_by_doi(self, doi):
        """Fetch a specific work by DOI"""
        url = f"{self.base_url}/works/doi:{doi}"
        response = requests.get(url, params={'mailto': 'jordano@ebd.csic.es'})
        response.raise_for_status()

        work = response.json()
        return self._parse_works([work])[0]

    def _parse_works(self, works):
        """Parse OpenAlex works into article format, preferring published versions"""
        works_by_title = {}

        for work in works:
            title = work.get('title', 'Untitled')
            normalized_title = re.sub(r'[^\w\s]', '', title.lower()).strip()

            if normalized_title not in works_by_title:
                works_by_title[normalized_title] = []
            works_by_title[normalized_title].append(work)

        selected_works = []
        for normalized_title, work_group in works_by_title.items():
            if len(work_group) == 1:
                selected_works.append(work_group[0])
            else:
                print(f"  Found {len(work_group)} versions of: {work_group[0].get('title', '')[:50]}...")

                best_work = work_group[0]
                for work in work_group:
                    work_type = work.get('type', '')
                    best_type = best_work.get('type', '')

                    if work_type == 'article' and best_type != 'article':
                        best_work = work
                        print(f"    -> Selecting journal version")
                    elif work_type == best_type and work.get('doi') and not best_work.get('doi'):
                        best_work = work
                    elif work_type == best_type and work.get('cited_by_count', 0) > best_work.get('cited_by_count', 0):
                        best_work = work

                selected_works.append(best_work)

        articles = []
        for work in selected_works:
            # Collect ALL authors for BibTeX
            all_authors = []
            if work.get('authorships'):
                all_authors = [a['author']['display_name'] for a in work['authorships']]

            # Truncated version for CSV (first 3 + et al.)
            author_str_trunc = ', '.join(all_authors[:3])
            if len(all_authors) > 3:
                author_str_trunc += ' et al.'

            pub_date = work.get('publication_date', '')
            if not pub_date:
                pub_year = work.get('publication_year')
                pub_date = f"{pub_year}-01-01" if pub_year else datetime.now().strftime('%Y-%m-%d')

            title = work.get('title', 'Untitled')

            cited_by_count = work.get('cited_by_count', 0)
            if cited_by_count is None:
                cited_by_count = 0

            print(f"  Citations for '{title[:40]}...': {cited_by_count}")

            source = (work.get('primary_location', {}) or {}).get('source', {}) or {}
            venue = source.get('display_name', '') or ''
            venue = venue.rstrip(' :').strip()
            publisher = source.get('host_organization_name', '') or ''

            # Extract PMID if available
            pmid = ''
            ids = work.get('ids', {})
            if isinstance(ids, dict) and 'pmid' in ids:
                pmid = ids['pmid']

            article = {
                'title': title,
                'author': author_str_trunc,
                'all_authors': all_authors,
                'author_count': len(all_authors),
                'date': pub_date,
                'year': int(pub_date[:4]) if pub_date else None,
                'doi': work.get('doi', '').replace('https://doi.org/', ''),
                'doi_url': work.get('doi', ''),
                'open_access': work.get('open_access', {}).get('is_oa', False),
                'pdf_url': work.get('open_access', {}).get('oa_url', '') or '',
                'cited_by_count': cited_by_count,
                'publication_venue': venue,
                'publisher': publisher,
                'openalex_id': work.get('id', ''),
                'work_type': work.get('type', ''),
                'pmid': pmid,
            }

            articles.append(article)

        return articles

    def _convert_authors_to_bibtex(self, all_authors):
        """Convert 'First Last' author list to BibTeX 'Last, First and Last, First' format"""
        bibtex_authors = []
        for name in all_authors:
            parts = name.strip().split()
            if len(parts) == 0:
                continue
            elif len(parts) == 1:
                bibtex_authors.append(parts[0])
            else:
                last = parts[-1]
                first_middle = ' '.join(parts[:-1])
                bibtex_authors.append(f"{last}, {first_middle}")
        return ' and '.join(bibtex_authors)

    def _make_citekey(self, article):
        """Generate a BibTeX citekey: firstauthorlastname + year + firsttitleword"""
        all_authors = article.get('all_authors', [])
        if all_authors:
            first_author = all_authors[0].strip().split()
            last_name = first_author[-1].lower() if first_author else 'unknown'
        else:
            last_name = 'unknown'

        year = str(article.get('year', '0000'))

        title = article.get('title', '')
        skip_words = {'a', 'an', 'the', 'of', 'in', 'on', 'at', 'for', 'and', 'or'}
        words = re.sub(r'[^\w\s]', '', title.lower()).split()
        first_word = next((w for w in words if w not in skip_words), words[0] if words else 'untitled')

        last_name = re.sub(r'[^a-z0-9]', '', last_name)
        first_word = re.sub(r'[^a-z0-9]', '', first_word)

        return f"{last_name}{year}{first_word}"

    def _escape_bibtex(self, text):
        """Escape special characters for BibTeX"""
        if not text:
            return text
        text = text.replace('&', r'\&')
        text = text.replace('%', r'\%')
        text = text.replace('$', r'\$')
        text = text.replace('#', r'\#')
        return text

    def _journal_abbr(self, journal):
        """Create a journal abbreviation from the first letters of significant words"""
        if not journal:
            return ''
        skip = {'a', 'an', 'the', 'of', 'in', 'on', 'at', 'for', 'and', 'or'}
        words = journal.split()
        abbr = ''.join(w[0].upper() for w in words if w.lower().rstrip(':') not in skip and w.replace(':', '').isalpha())
        return abbr if abbr else journal[:6]

    def create_bibtex_entry(self, article):
        """Convert a parsed article dict to a BibTeX entry string"""
        work_type = article.get('work_type', '').lower()
        venue = article.get('publication_venue', '')
        venue_lower = venue.lower()

        is_preprint = (
            work_type in ('posted-content', 'preprint') or
            'crimrxiv' in venue_lower or
            'arxiv' in venue_lower or
            'preprint' in venue_lower
        )

        entry_type = 'misc' if is_preprint else 'article'
        citekey = self._make_citekey(article)

        author_bibtex = self._convert_authors_to_bibtex(article.get('all_authors', []))
        title_escaped = self._escape_bibtex(article.get('title', ''))
        year = article.get('year', '')
        doi = article.get('doi', '')
        doi_url = article.get('doi_url', '') or (f"https://doi.org/{doi}" if doi else '')
        pdf_url = article.get('pdf_url', '')
        abbr = self._journal_abbr(venue) if venue else ''

        fields = []
        fields.append(f"  title     = {{{title_escaped}}}")
        fields.append(f"  author    = {{{author_bibtex}}}")

        if entry_type == 'article':
            venue_escaped = self._escape_bibtex(venue)
            fields.append(f"  journal   = {{{venue_escaped}}}")
        else:
            fields.append(f"  note      = {{Preprint}}")

        fields.append(f"  year      = {{{year}}}")

        if doi:
            fields.append(f"  doi       = {{{doi}}}")
        if doi_url:
            fields.append(f"  url       = {{{doi_url}}}")
        if pdf_url:
            fields.append(f"  pdf       = {{{pdf_url}}}")
        if abbr:
            fields.append(f"  abbr      = {{{abbr}}}")

        fields.append(f"  selected  = {{false}}")

        fields_str = ',\n'.join(fields)
        return f"@{entry_type}{{{citekey},\n{fields_str}\n}}"

    def sync_bibtex(self, articles, output_path=None):
        """Write all articles as BibTeX entries to papers.bib"""
        if output_path is None:
            output_path = self.bibtex_path

        entries = []
        seen_keys = {}
        for article in articles:
            entry = self.create_bibtex_entry(article)
            key_match = re.match(r'@\w+\{(\w+),', entry)
            citekey = key_match.group(1) if key_match else 'unknown'

            if citekey in seen_keys:
                seen_keys[citekey] += 1
                suffix = seen_keys[citekey]
                new_key = f"{citekey}_{suffix}"
                entry = re.sub(r'(@\w+\{)\w+,', rf'\g<1>{new_key},', entry, count=1)
            else:
                seen_keys[citekey] = 0

            entries.append(entry)

        bib_content = '\n\n'.join(entries) + '\n'

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(bib_content)

        print(f"Wrote {len(entries)} BibTeX entries to {output_path}")

    def sync_csv(self, articles, output_path='data/publications.csv'):
        """Write all articles to a CSV file (for backwards compatibility)"""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            'title', 'authors', 'author_count', 'year', 'publication_date',
            'journal', 'publisher', 'type', 'is_oa', 'doi', 'doi_url',
            'pdf_url', 'openalex_id', 'pmid', 'cited_by_count'
        ]

        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for a in articles:
                writer.writerow({
                    'title': a.get('title', ''),
                    'authors': a.get('author', ''),
                    'author_count': a.get('author_count', ''),
                    'year': a.get('year', ''),
                    'publication_date': a.get('date', ''),
                    'journal': a.get('publication_venue', ''),
                    'publisher': a.get('publisher', ''),
                    'type': a.get('work_type', ''),
                    'is_oa': a.get('open_access', False),
                    'doi': a.get('doi_url', ''),
                    'doi_url': a.get('doi_url', ''),
                    'pdf_url': a.get('pdf_url', ''),
                    'openalex_id': a.get('openalex_id', ''),
                    'pmid': a.get('pmid', ''),
                    'cited_by_count': a.get('cited_by_count', 0),
                })

        print(f"Wrote {len(articles)} entries to {output_path}")

    def sync_author_works(self, author_name=None, orcid=None, limit=50):
        """Sync all works: fetch from OpenAlex, write BibTeX and CSV"""
        articles = self.fetch_author_works(author_name=author_name, orcid=orcid, limit=limit)

        self.sync_bibtex(articles)
        self.sync_csv(articles)

        print(f"\nSync complete: {len(articles)} publications processed.")
        return articles


class FilteredOpenAlexSync(OpenAlexArticleSync):
    """Extended version with filtering options"""

    def fetch_author_works(self, author_name=None, orcid=None, limit=50,
                          min_citations=None, publication_year_from=None,
                          only_open_access=False, exclude_types=None):
        """Fetch works with advanced filtering"""
        filters = []

        if orcid:
            filters.append(f'author.orcid:{orcid}')
        elif author_name:
            filters.append(f'author.search:{author_name}')
        else:
            raise ValueError("Must provide either author_name or orcid")

        if min_citations:
            filters.append(f'cited_by_count:>{min_citations}')

        if publication_year_from:
            filters.append(f'publication_year:>{publication_year_from}')

        if only_open_access:
            filters.append('is_oa:true')

        if exclude_types:
            for t in exclude_types:
                filters.append(f'type:!{t}')

        url = f"{self.base_url}/works"
        params = {
            'filter': ','.join(filters),
            'per-page': limit,
            'sort': 'publication_date:desc',
            'mailto': 'jordano@ebd.csic.es'
        }

        print(f"Fetching works with filters: {filters}")
        response = requests.get(url, params=params)
        response.raise_for_status()

        works = response.json().get('results', [])
        print(f"Found {len(works)} works")
        return self._parse_works(works)


if __name__ == "__main__":
    syncer = FilteredOpenAlexSync()
    syncer.sync_author_works(
        orcid="0000-0003-2142-9116",
        limit=50
    )
