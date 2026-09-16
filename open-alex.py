import os
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

# OpenAlex hard-caps per-page at 200; anything larger is a 400 Bad Request.
MAX_PER_PAGE = 200

# Contact address for the OpenAlex "polite pool" (faster, more reliable queue).
# Override with the OPENALEX_MAILTO environment variable.
DEFAULT_MAILTO = "jordano@ebd.csic.es"


def format_volume_pages(volume=None, first_page=None, last_page=None, pages=None):
    """Combined citation-detail string, e.g. 'Vol. 64: 1021-1035' (en dash).

    Both halves are optional: a volume with no pagination gives 'Vol. 64', and
    pagination with no volume gives 'pp. 1021-1035'. Article-number pages
    (e.g. 'e12345', '20230411') are emitted as-is, since a range dash would be
    wrong there.
    """
    volume = (str(volume).strip() if volume not in (None, '') else '')
    if pages in (None, ''):
        fp = str(first_page).strip() if first_page not in (None, '') else ''
        lp = str(last_page).strip() if last_page not in (None, '') else ''
        if fp and lp and fp != lp:
            pages = f"{fp}\u2013{lp}"
        else:
            pages = fp or lp
    else:
        pages = str(pages).strip()
        # BibTeX writes ranges as 1021--1035; normalise any dash to an en dash
        pages = re.sub(r"\s*(?:--|-|\u2010|\u2012|\u2014)\s*", "\u2013", pages)
        head, _, tail = pages.partition("\u2013")
        if tail and head == tail:
            pages = head

    if volume and pages:
        return f"Vol. {volume}: {pages}"
    if volume:
        return f"Vol. {volume}"
    if pages:
        return f"pp. {pages}"
    return ''


class OpenAlexArticleSync:
    def __init__(self, bibtex_path="_bibliography/papers.bib", mailto=None, api_key=None):
        self.base_url = "https://api.openalex.org"
        self.bibtex_path = Path(bibtex_path)
        self.bibtex_path.parent.mkdir(parents=True, exist_ok=True)
        self.mailto = mailto or os.environ.get("OPENALEX_MAILTO") or DEFAULT_MAILTO
        # Optional: only needed if you have an OpenAlex premium/API key.
        self.api_key = api_key or os.environ.get("OPENALEX_API_KEY") or None

    def _base_params(self):
        params = {}
        if self.mailto:
            params['mailto'] = self.mailto
        if self.api_key:
            params['api_key'] = self.api_key
        return params

    def _fetch_all(self, filters, limit=None, max_retries=3):
        """Fetch works matching `filters`, paging with a cursor.

        OpenAlex returns at most 200 records per request, so anything larger
        (or unbounded) has to be walked with `cursor`. `limit` is the maximum
        number of works to return overall; None means "everything".
        """
        url = f"{self.base_url}/works"
        works = []
        cursor = '*'

        while cursor:
            remaining = MAX_PER_PAGE if limit is None else min(MAX_PER_PAGE, limit - len(works))
            if remaining <= 0:
                break

            params = self._base_params()
            params.update({
                'filter': ','.join(filters),
                'per-page': remaining,
                'sort': 'publication_date:desc',
                'cursor': cursor,
            })

            for attempt in range(max_retries):
                response = requests.get(url, params=params, timeout=60)
                if response.status_code in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                    wait = 2 ** attempt
                    print(f"  OpenAlex returned {response.status_code}; retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                break

            if not response.ok:
                # Surface the API's own explanation instead of a bare HTTPError.
                try:
                    detail = response.json().get('message', response.text[:300])
                except ValueError:
                    detail = response.text[:300]
                raise requests.exceptions.HTTPError(
                    f"{response.status_code} from OpenAlex: {detail}\nURL: {response.url}",
                    response=response,
                )

            data = response.json()
            batch = data.get('results', [])
            works.extend(batch)

            meta = data.get('meta', {})
            cursor = meta.get('next_cursor')
            total = meta.get('count')
            if total is not None:
                print(f"  Retrieved {len(works)}/{total} works")
            if not batch:
                break

        return works

    def fetch_author_works(self, author_name=None, orcid=None, limit=50):
        """Fetch works by author from OpenAlex"""
        if orcid:
            filters = [f'author.orcid:{orcid}']
        elif author_name:
            filters = [f'author.search:{author_name}']
        else:
            raise ValueError("Must provide either author_name or orcid")

        print("Fetching works from OpenAlex...")
        works = self._fetch_all(filters, limit=limit)

        print(f"Found {len(works)} works")
        return self._parse_works(works)

    def fetch_by_doi(self, doi):
        """Fetch a specific work by DOI"""
        url = f"{self.base_url}/works/doi:{doi}"
        response = requests.get(url, params=self._base_params(), timeout=60)
        response.raise_for_status()

        work = response.json()
        return self._parse_works([work])[0]

    def _load_exclusions(self, path="_exclude_works.yml"):
        """OpenAlex work IDs (e.g. W2148371894) to drop, if the file exists.

        OpenAlex occasionally attaches another author's records to an ORCID;
        listing the offending IDs here keeps them off the site.
        """
        p = Path(path)
        if not p.exists():
            return set()
        text = p.read_text(encoding="utf-8")
        if yaml is not None:
            try:
                data = yaml.safe_load(text) or {}
                return {str(i).strip().split('/')[-1]
                        for i in (data.get('exclude') or [])}
            except Exception as exc:
                print(f"  Could not parse {path} as YAML ({exc}); falling back to ID scan")
        # PyYAML not installed: pick the bare OpenAlex IDs out of the file.
        return set(re.findall(r'\bW\d+\b', text))

    def _parse_works(self, works):
        """Parse OpenAlex works into article format, preferring published versions"""
        excluded = self._load_exclusions()
        if excluded:
            before = len(works)
            works = [w for w in works
                     if (w.get('id') or '').split('/')[-1] not in excluded]
            print(f"Excluded {before - len(works)} work(s) listed in _exclude_works.yml")

        works_by_title = {}

        for work in works:
            title = work.get('title') or 'Untitled'
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

            # OpenAlex can return explicit nulls for these fields.
            title = work.get('title') or 'Untitled'
            doi_url = work.get('doi') or ''

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

            # OpenAlex carries volume/issue/pagination in `biblio`; any of the
            # four can be absent or an explicit null
            biblio = work.get('biblio') or {}
            volume = biblio.get('volume') or ''
            issue = biblio.get('issue') or ''
            first_page = biblio.get('first_page') or ''
            last_page = biblio.get('last_page') or ''

            article = {
                'title': title,
                'author': author_str_trunc,
                'all_authors': all_authors,
                'author_count': len(all_authors),
                'date': pub_date,
                'year': int(pub_date[:4]) if pub_date else None,
                'doi': doi_url.replace('https://doi.org/', ''),
                'doi_url': doi_url,
                'open_access': work.get('open_access', {}).get('is_oa', False),
                'pdf_url': work.get('open_access', {}).get('oa_url', '') or '',
                'cited_by_count': cited_by_count,
                'publication_venue': venue,
                'publisher': publisher,
                'openalex_id': work.get('id', ''),
                'work_type': work.get('type', ''),
                'pmid': pmid,
                'volume': volume,
                'issue': issue,
                'first_page': first_page,
                'last_page': last_page,
                'volume_pages': format_volume_pages(volume, first_page, last_page),
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
            'pdf_url', 'openalex_id', 'pmid', 'cited_by_count',
            'volume', 'issue', 'first_page', 'last_page', 'volume_pages'
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
                    'volume': a.get('volume', ''),
                    'issue': a.get('issue', ''),
                    'first_page': a.get('first_page', ''),
                    'last_page': a.get('last_page', ''),
                    'volume_pages': a.get('volume_pages', ''),
                })

        print(f"Wrote {len(articles)} entries to {output_path}")

    def _is_preprint(self, article):
        """Return True if the work is a preprint / working paper (e.g. CrimRxiv)."""
        work_type = article.get('work_type', '').lower()
        venue = article.get('publication_venue', '').lower()
        return (
            work_type in ('posted-content', 'preprint') or
            'crimrxiv' in venue or
            'arxiv' in venue or
            'preprint' in venue
        )

    def _make_slug(self, title, max_len=80):
        """Generate a URL-safe directory slug from a title (matches existing convention)."""
        slug = title.lower()
        slug = re.sub(r'[^\w\s-]', '', slug)   # drop punctuation except hyphens
        slug = re.sub(r'\s+', '-', slug)         # spaces → hyphens
        slug = re.sub(r'-+', '-', slug)          # collapse runs
        return slug[:max_len]

    def _make_article_qmd(self, article, is_preprint):
        """Return the text content for an article's index.qmd file."""
        title     = article.get('title', 'Untitled')
        author    = article.get('author', '')
        date      = article.get('date', '')
        venue     = article.get('publication_venue', '')
        doi       = article.get('doi', '')
        doi_url   = article.get('doi_url', '') or (f"https://doi.org/{doi}" if doi else '')
        pdf_url   = article.get('pdf_url', '')
        citations = article.get('cited_by_count', 0)
        is_oa     = article.get('open_access', False)
        openalex_id = article.get('openalex_id', '')

        openalex_url = ''
        if openalex_id:
            oa_key = openalex_id.split('/')[-1]
            openalex_url = f"https://openalex.org/{oa_key}"

        # Quote title safely for YAML
        if '"' in title and "'" in title:
            title_yaml = "'" + title.replace("'", "''") + "'"
        elif '"' in title:
            title_yaml = f"'{title}'"
        else:
            title_yaml = f'"{title}"'

        lines = [
            '---',
            f'title: {title_yaml}',
            f'authors: "{author}"',
            f"date: '{date}'",
            f'pub-journal: "{venue}"',
        ]
        vol_pages = article.get('volume_pages') or format_volume_pages(
            article.get('volume'), article.get('first_page'), article.get('last_page'))
        if vol_pages:
            lines.append(f'volume-pages: "{vol_pages}"')
        if doi:
            lines += [f'doi: {doi}', f'citation-url: {doi_url}']
        lines += ['format:', '  html:', '    toc: true', '---', '']

        if is_preprint:
            lines += [
                '::: {.callout-warning}',
                '## Preprint',
                'This is a preprint and has not undergone peer review. Interpret findings with caution.',
                ':::',
                '',
            ]

        lines += [
            '## Publication Details',
            '',
            f'**Published in:** {venue}',
            '',
            f'**Citations:** {citations}',
        ]

        if is_oa:
            lines += ['', '**Open Access:** Yes']

        link_parts = []
        if doi_url:
            link_parts.append(f'[DOI Link]({doi_url})')
        if pdf_url:
            link_parts.append(f'[PDF]({pdf_url})')
        if openalex_url:
            link_parts.append(f'[OpenAlex]({openalex_url})')

        if link_parts:
            lines += ['', '## Links', '', ' | '.join(link_parts)]

        lines.append('')
        return '\n'.join(lines)

    def save_article_pages(self, articles):
        """Write individual index.qmd files for every article.

        Journal articles → research/articles/<slug>/index.qmd
        Preprints/CrimRxiv → research/working-papers/<slug>/index.qmd

        Stale pages (no longer returned by OpenAlex) are removed.
        """
        articles_dir       = Path('research/articles')
        working_papers_dir = Path('research/working-papers')
        articles_dir.mkdir(parents=True, exist_ok=True)
        working_papers_dir.mkdir(parents=True, exist_ok=True)

        generated = set()

        for article in articles:
            is_wp   = self._is_preprint(article)
            target  = working_papers_dir if is_wp else articles_dir
            slug    = self._make_slug(article.get('title', 'untitled'))
            out_dir = target / slug
            out_dir.mkdir(parents=True, exist_ok=True)
            qmd     = out_dir / 'index.qmd'
            qmd.write_text(self._make_article_qmd(article, is_wp), encoding='utf-8')
            generated.add(qmd)
            label = '[WP] ' if is_wp else '[PUB]'
            print(f"  {label} {article.get('title', '')[:60]}")

        # Remove pages that are no longer in OpenAlex results
        for search_dir in [articles_dir, working_papers_dir]:
            for old_qmd in search_dir.glob('*/index.qmd'):
                if old_qmd not in generated:
                    print(f"  Removing stale page: {old_qmd}")
                    old_qmd.unlink()
                    try:
                        old_qmd.parent.rmdir()
                    except OSError:
                        pass

        print(f"Saved {len(generated)} article pages.")

    def sync_author_works(self, author_name=None, orcid=None, limit=50):
        """Sync all works: fetch from OpenAlex, write BibTeX, CSV, and article pages."""
        articles = self.fetch_author_works(author_name=author_name, orcid=orcid, limit=limit)

        self.sync_bibtex(articles)
        self.sync_csv(articles)
        self.save_article_pages(articles)

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

        print(f"Fetching works with filters: {filters}")
        works = self._fetch_all(filters, limit=limit)

        print(f"Found {len(works)} works")
        return self._parse_works(works)


if __name__ == "__main__":
    syncer = FilteredOpenAlexSync()
    syncer.sync_author_works(
        orcid="0000-0003-2142-9116",
        limit=50
    )
