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

# ── Citation / attention badges on article pages ──────────────────────────────
# Dimensions and Altmetric are both rendered client-side from the paper's DOI:
# their loader scripts replace the placeholder elements below with the live
# badge and wire up the link to the corresponding details page
# (badge.dimensions.ai/details/doi/<doi>?domain=<site>, altmetric.com/details/...),
# so nothing needs to be fetched at build time and the counts stay current
# without re-rendering the site.
#
# Both placeholders are wrapped in their own <div> and separated by a blank
# line so Pandoc keeps them as two raw-HTML blocks; the flex rules for
# .article-badges in html/pedroj.scss put them side by side.
# The Altmetric donut is invisible for papers with no recorded attention —
# that is the badge's own behaviour, not a build error.
BADGES_START = "<!-- badges:start -->"
BADGES_END = "<!-- badges:end -->"

# ── Rendered reference block on each paper page ───────────────────────────────
# Same sentinels _tools/add-volume-pages.py uses, so a sync and a backfill
# write the identical block and neither duplicates the other's.
REF_START = "<!-- full-reference:start -->"
REF_END = "<!-- full-reference:end -->"

# Spacer between "Published in:" and "Open Access:" on the same line.
FIELD_GAP = "&emsp;&emsp;"


def badge_block(doi):
    """Dimensions + Altmetric badge markup for one DOI (empty string if none).

    The single source of truth for this markup: _tools/add-badges.py imports
    this function, so patching existing pages is byte-identical to what a sync
    writes and produces no diff.
    """
    doi = re.sub(r'^https?://(dx\.)?doi\.org/', '', (doi or '').strip(), flags=re.I)
    if not doi:
        return ''
    return '\n'.join([
        BADGES_START,
        '::: {.article-badges}',
        '<div class="badge-dimensions">'
        f'<span class="__dimensions_badge_embed__" data-doi="{doi}" '
        'data-legend="always" data-style="small_circle"></span></div>',
        '',
        '<div class="badge-altmetric">'
        f'<div class="altmetric-embed" data-doi="{doi}" data-badge-type="donut" '
        'data-badge-popover="right"></div></div>',
        ':::',
        '',
        '<script async src="https://badge.dimensions.ai/badge.js" charset="utf-8"></script>',
        '<script async src="https://d1bxh8uas1mnw7.cloudfront.net/assets/embed.js"></script>',
        BADGES_END,
    ])


def format_page_range(first_page=None, last_page=None):
    """'1021-1035' (en dash) from OpenAlex's first_page/last_page."""
    fp = str(first_page).strip() if first_page not in (None, '') else ''
    lp = str(last_page).strip() if last_page not in (None, '') else ''
    if fp and lp and fp != lp:
        return f"{fp}\u2013{lp}"
    return fp or lp


def format_citation_detail(year=None, volume=None, pages=None):
    """One compact column for the listing table: '2017, 20: 577-590'.

    Degrades cleanly: year alone -> '2017'; year and pagination but no volume
    -> '2017, 391-406'; volume with no year -> '20: 577-590'.
    """
    year = str(year).strip() if year not in (None, "") else ""
    volume = str(volume).strip() if volume not in (None, "") else ""
    pages = str(pages).strip() if pages not in (None, "") else ""
    tail = f"{volume}: {pages}" if volume and pages else (volume or pages)
    if year and tail:
        return f"{year}, {tail}"
    return year or tail


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


# ── Reference / abstract helpers ──────────────────────────────────────────────
# Everything from format_citation_detail down to the class below is exec'd out
# of this file by _tools/add-volume-pages.py (which cannot import `requests`),
# so these functions must depend on nothing but `re` and the standard builtins.

def reconstruct_abstract(inverted_index):
    """Plain abstract text from OpenAlex's `abstract_inverted_index`.

    OpenAlex stores abstracts as {word: [positions]} for licensing reasons;
    sorting the positions back out is the documented way to recover the text.
    """
    if not inverted_index:
        return ''
    positions = []
    for word, idxs in inverted_index.items():
        for i in idxs or []:
            positions.append((i, word))
    if not positions:
        return ''
    positions.sort()
    return ' '.join(word for _, word in positions)


def clean_abstract(text, max_chars=None):
    """Normalise an abstract for a BibTeX field.

    Crossref serves JATS-tagged abstracts (`<jats:p>...`) and both sources
    keep the literal word "Abstract" as the first token; neither belongs in a
    `abstract = {...}` field. Newlines are collapsed because a BibTeX value
    spanning lines confuses some parsers.
    """
    if not text:
        return ''
    t = re.sub(r'<[^>]+>', ' ', str(text))
    t = (t.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
          .replace('&quot;', '"').replace('&apos;', "'").replace('&#x2013;', '\u2013'))
    t = re.sub(r'\s+', ' ', t).strip()
    t = re.sub(r'^abstract[:.\s\u2014-]*', '', t, flags=re.I).strip()
    # braces delimit the BibTeX value itself: an unbalanced one in the text
    # would truncate the field, so they become parentheses
    t = t.replace('{', '(').replace('}', ')')
    if max_chars and len(t) > max_chars:
        t = t[:max_chars].rsplit(' ', 1)[0] + '\u2026'
    return t


def name_initials(given):
    """'Lucas P.' -> 'L. P.'   'Jean-Pierre' -> 'J.-P.'   'Maria' -> 'M.'"""
    out = []
    for token in re.split(r'[\s.]+', (given or '').strip()):
        if not token:
            continue
        parts = [p for p in token.split('-') if p]
        out.append('-'.join(p[0].upper() + '.' for p in parts))
    return ' '.join(out)


# Nobiliary particles that belong to the surname, not to the given names:
# "Marcus A. M. de Aguiar" -> "de Aguiar, M. A. M.", not "Aguiar, M. A. M. D."
NAME_PARTICLES = {'de', 'del', 'della', 'der', 'di', 'da', 'das', 'do', 'dos',
                  'du', 'la', 'le', 'van', 'von', 'ter', 'ten', 'af', 'bin',
                  'ibn', "y", "i"}


def surname_first(name):
    """'Pedro Jordano' -> 'Jordano, P.'  (display-name form, one string)."""
    parts = (name or '').strip().split()
    if not parts:
        return ''
    if len(parts) == 1:
        return parts[0]
    surname = [parts.pop()]
    while parts and parts[-1].lower() in NAME_PARTICLES:
        surname.insert(0, parts.pop())
    if not parts:                       # the whole name was particles
        return ' '.join(surname)
    return f"{' '.join(surname)}, {name_initials(' '.join(parts))}"


def format_name_list(names, style='surname-first'):
    """'Jordano, P., Bascompte, J. and Olesen, J. M.' from display names.

    Reference-list style: every name given, ', ' between them and ' and '
    before the last one (no et al. truncation, as in the site's Oikos-style
    working-paper citations).
    """
    if isinstance(names, str):
        # split on ' and ' / ';' only: names already written surname-first
        # ("Jordano, P.") carry their own comma, which a ',' split would break
        names = [n for n in re.split(r'\s+and\s+|;\s*', names) if n.strip()]
    formatted = []
    for n in names or []:
        n = (n or '').strip()
        if not n:
            continue
        # already "Surname, I." — leave it alone
        formatted.append(n if ',' in n or style != 'surname-first' else surname_first(n))
    if not formatted:
        return ''
    if len(formatted) == 1:
        return formatted[0]
    return ', '.join(formatted[:-1]) + ' and ' + formatted[-1]


def bibtex_entry_type(work_type, venue=''):
    """Map an OpenAlex/Crossref record type to a BibTeX entry type."""
    t = (work_type or '').lower()
    v = (venue or '').lower()
    if (t in ('posted-content', 'preprint', 'posted_content')
            or 'crimrxiv' in v or 'arxiv' in v or 'preprint' in v
            or 'biorxiv' in v or 'ecoevorxiv' in v):
        return 'misc'
    if t in ('book-chapter', 'book_chapter', 'chapter', 'book-part', 'book-section'):
        return 'incollection'
    if t in ('book', 'monograph', 'edited-book', 'reference-book', 'edited_book'):
        return 'book'
    return 'article'


def format_full_reference(entry_type='article', authors='', year='', title='',
                          journal='', volume='', pages='', booktitle='',
                          editors='', publisher='', place='', doi='', url='',
                          note=''):
    """One rendered reference line (Pandoc markdown) for a paper page.

    Shape follows the entry type, so the block on the page carries the same
    information as the BibTeX record it was built from:

      article      Authors YEAR. Title. *Journal* Vol: pages. <doi>
      incollection Authors YEAR. Title. In: Eds (eds.) *Book title*,
                   pp. pages. Publisher, Place. <doi>
      book         Authors YEAR. *Title*. Publisher, Place. <doi>
      misc         Authors YEAR. Title. *Venue*. <doi>     (preprints)
    """
    authors = format_name_list(authors)
    year = str(year or '').strip()
    title = (title or '').strip().rstrip('.')
    volume = str(volume or '').strip()
    pages = str(pages or '').strip()
    pages = re.sub(r'\s*(?:--|-|\u2010|\u2012|\u2014)\s*', '\u2013', pages)

    bits = []
    if authors:
        # kept verbatim: the trailing initial's period is part of the name
        # ("Jordano, P. 2000. ...")
        bits.append(authors)
    if year:
        bits.append(f"{year}.")

    if entry_type == 'book':
        if title:
            bits.append(f"*{title}*.")
        imprint = ', '.join(p for p in (publisher, place) if p)
        if imprint:
            bits.append(imprint.rstrip('.') + '.')
        if booktitle and booktitle.strip().lower() != title.lower():
            bits.append(f"*{booktitle.strip().rstrip('.')}*.")
    elif entry_type == 'incollection':
        if title:
            bits.append(f"{title}.")
        host = []
        ed_names = ([e for e in editors if str(e).strip()]
                    if isinstance(editors, (list, tuple))
                    else [e for e in re.split(r'\s+and\s+|;\s*', editors or '') if e.strip()])
        eds = format_name_list(editors)
        if eds:
            host.append(f"In: {eds} ({'eds.' if len(ed_names) > 1 else 'ed.'})")
        elif booktitle:
            host.append('In:')
        if booktitle:
            host.append(f"*{booktitle.strip().rstrip('.')}*")
        if host:
            tail = ' '.join(host)
            bits.append(tail + (f", pp. {pages}." if pages else '.'))
        elif pages:
            bits.append(f"pp. {pages}.")
        imprint = ', '.join(p for p in (publisher, place) if p)
        if imprint:
            bits.append(imprint.rstrip('.') + '.')
    else:
        if title:
            bits.append(f"{title}.")
        tail = []
        venue = journal or booktitle
        if venue:
            tail.append(f"*{venue.strip().rstrip(' :.')}*")
        if volume and pages:
            tail.append(f"{volume}: {pages}")
        elif volume:
            tail.append(volume)
        elif pages:
            tail.append(pages)
        if tail:
            bits.append(' '.join(tail) + '.')

    if note:
        bits.append(note.rstrip('.') + '.')
    link = url or (f"https://doi.org/{doi}" if doi else '')
    if link:
        bits.append(f"<{link}>")
    return ' '.join(b for b in bits if b).strip()


class OpenAlexArticleSync:
    def __init__(self, bibtex_path="_bibliography/papers.bib", mailto=None, api_key=None):
        self.base_url = "https://api.openalex.org"
        self.bibtex_path = Path(bibtex_path)
        self.bibtex_path.parent.mkdir(parents=True, exist_ok=True)
        self.mailto = mailto or os.environ.get("OPENALEX_MAILTO") or DEFAULT_MAILTO
        # Optional: only needed if you have an OpenAlex premium/API key.
        self.api_key = api_key or os.environ.get("OPENALEX_API_KEY") or None
        # Hand-curated code/data links per paper, keyed by DOI. Article pages
        # are regenerated on every sync, so these live outside them.
        self.paper_links = self._load_paper_links()

    @staticmethod
    def _norm_doi(value):
        """Bare lowercase DOI from a DOI or a doi.org URL."""
        v = (value or '').strip().lower()
        return re.sub(r'^https?://(dx\.)?doi\.org/', '', v).strip()

    def _load_paper_links(self, path="data/paper_links.yml"):
        """Load DOI -> {code, data, extra: [{label, url}]} from the sidecar file.

        Proposals for this file are generated by
        `python _tools/propose-paper-links.py`; it is otherwise hand-edited and
        is never overwritten by a sync.
        """
        p = Path(path)
        if not p.exists():
            return {}
        if yaml is None:
            print("  ! pyyaml not installed: skipping data/paper_links.yml")
            return {}
        try:
            data = yaml.safe_load(p.read_text(encoding='utf-8')) or {}
        except yaml.YAMLError as exc:
            print(f"  ! could not parse {path}: {exc}")
            return {}
        if not isinstance(data, dict):
            print(f"  ! {path} should be a mapping of DOI -> links; ignoring")
            return {}
        links = {}
        for doi, entry in data.items():
            if isinstance(entry, dict):
                links[self._norm_doi(str(doi))] = entry
        if links:
            print(f"  Loaded code/data links for {len(links)} paper(s) from {path}")
        return links

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

    # ── Crossref supplement ───────────────────────────────────────────────
    # OpenAlex carries no ISBN, no editors, no publisher place, and its
    # `abstract_inverted_index` is empty for many older records. Crossref has
    # all four for the same DOI, so book/chapter records — and any record
    # missing an abstract or pagination — are topped up from there.
    CROSSREF_API = "https://api.crossref.org/works"

    def _crossref(self, doi):
        """Crossref `message` for a DOI, or {} (cached per run)."""
        doi = self._norm_doi(doi)
        if not doi:
            return {}
        if not hasattr(self, '_crossref_cache'):
            self._crossref_cache = {}
        if doi in self._crossref_cache:
            return self._crossref_cache[doi]
        msg = {}
        try:
            params = {'mailto': self.mailto} if self.mailto else {}
            r = requests.get(f"{self.CROSSREF_API}/{doi}", params=params, timeout=30)
            if r.ok:
                msg = r.json().get('message') or {}
        except (requests.exceptions.RequestException, ValueError) as exc:
            print(f"  ! Crossref lookup failed for {doi}: {exc}")
        self._crossref_cache[doi] = msg
        time.sleep(0.1)          # stay polite on a few hundred lookups
        return msg

    @staticmethod
    def _crossref_names(entries):
        """['Fenner, M.', ...] from Crossref author/editor objects."""
        names = []
        for person in entries or []:
            family = (person.get('family') or person.get('name') or '').strip()
            given = (person.get('given') or '').strip()
            if not family:
                continue
            names.append(f"{family}, {name_initials(given)}" if given else family)
        return names

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

            entry_type = bibtex_entry_type(work_type=work.get('type', ''), venue=venue)
            abstract = clean_abstract(
                reconstruct_abstract(work.get('abstract_inverted_index')))

            # A chapter's `source` is the platform or series ("CABI Publishing
            # eBooks"); `raw_source_name` holds the actual volume title.
            raw_source = (work.get('primary_location') or {}).get('raw_source_name') or ''
            booktitle = raw_source if entry_type in ('incollection', 'book') else ''
            editors, place, isbn = [], '', ''

            needs_crossref = (
                entry_type in ('incollection', 'book')
                or not abstract
                or (entry_type == 'article' and not (volume and (first_page or last_page)))
            )
            if needs_crossref and doi_url:
                msg = self._crossref(doi_url)
                if msg:
                    containers = [c for c in (msg.get('container-title') or []) if c]
                    if entry_type in ('incollection', 'book') and containers:
                        # Elsevier-style chapters list the series first and the
                        # volume title second; the volume title is the booktitle.
                        booktitle = containers[-1]
                    editors = self._crossref_names(msg.get('editor'))
                    place = (msg.get('publisher-location') or '').strip()
                    cr_publisher = (msg.get('publisher') or '').strip()
                    if entry_type in ('incollection', 'book') and cr_publisher:
                        # the imprint as the book carries it ("Elsevier") reads
                        # better in a reference than OpenAlex's corporate name
                        # for the same host organisation ("Elsevier BV")
                        publisher = cr_publisher
                    else:
                        publisher = publisher or cr_publisher
                    isbns = [i for i in (msg.get('ISBN') or []) if i]
                    isbn = isbns[0] if isbns else ''
                    if not abstract:
                        abstract = clean_abstract(msg.get('abstract'))
                    if not volume:
                        volume = (msg.get('volume') or '').strip()
                    if not (first_page or last_page):
                        cr_pages = (msg.get('page') or '').strip()
                        if cr_pages:
                            halves = re.split(r'\s*[-\u2010\u2012\u2013\u2014]+\s*',
                                              cr_pages, maxsplit=1)
                            first_page = halves[0]
                            last_page = halves[1] if len(halves) > 1 else ''

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
                'pages': format_page_range(first_page, last_page),
                'volume_pages': format_volume_pages(volume, first_page, last_page),
                'entry_type': entry_type,
                'abstract': abstract,
                'booktitle': booktitle,
                'editors': editors,
                'place': place,
                'isbn': isbn,
            }
            article['full_reference'] = format_full_reference(
                entry_type=entry_type,
                authors=all_authors,
                year=article['year'],
                title=title,
                journal=venue if entry_type in ('article', 'misc') else '',
                volume=volume,
                pages=article['pages'],
                booktitle=booktitle,
                editors=editors,
                publisher=publisher,
                place=place,
                doi=article['doi'],
                url=doi_url,
                note='Preprint' if entry_type == 'misc' else '',
            )

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

    def create_bibtex_entry(self, article, include_abstract=True):
        """Convert a parsed article dict to a complete BibTeX entry string.

        The field set follows the entry type, so every record carries what a
        reference list needs without a manual top-up:

          @article      author, year, title, journal, volume, number, pages,
                        abstract, doi, url
          @incollection author, year, title, booktitle, editor, pages,
                        publisher, address, isbn, abstract, doi/url
          @book         author, year, title, booktitle (series, when it
                        differs), publisher, address, isbn, abstract, doi/url
          @misc         preprints: author, year, title, venue as `note`,
                        abstract, doi/url

        Absent values are omitted rather than written empty, so a missing
        volume or ISBN never leaves a stray `volume = {}` behind.
        """
        venue = article.get('publication_venue', '')
        entry_type = article.get('entry_type') or bibtex_entry_type(
            article.get('work_type', ''), venue)
        citekey = self._make_citekey(article)

        author_bibtex = self._convert_authors_to_bibtex(article.get('all_authors', []))
        editor_bibtex = ' and '.join(article.get('editors') or [])
        title_escaped = self._escape_bibtex(article.get('title', ''))
        booktitle = self._escape_bibtex(article.get('booktitle', '') or '')
        year = article.get('year', '')
        doi = article.get('doi', '')
        doi_url = article.get('doi_url', '') or (f"https://doi.org/{doi}" if doi else '')
        pdf_url = article.get('pdf_url', '')
        # `abbr` is a journal shorthand, so it is written for journal articles
        # and preprints only — not for a book's publishing platform.
        abbr = (self._journal_abbr(venue)
                if venue and entry_type in ('article', 'misc') else '')
        pages = article.get('pages', '') or format_page_range(
            article.get('first_page'), article.get('last_page'))
        # BibTeX writes ranges with a double hyphen
        pages = re.sub(r'\s*[\u2010\u2012\u2013\u2014-]+\s*', '--', str(pages or ''))
        publisher = self._escape_bibtex(article.get('publisher', '') or '')
        place = self._escape_bibtex(article.get('place', '') or '')
        abstract = self._escape_bibtex(clean_abstract(article.get('abstract', '')))

        def put(fields, name, value):
            if value not in (None, '', []):
                fields.append(f"  {name:<9} = {{{value}}}")

        fields = []
        put(fields, 'title', title_escaped)
        put(fields, 'author', author_bibtex)

        if entry_type == 'article':
            put(fields, 'journal', self._escape_bibtex(venue))
        elif entry_type == 'incollection':
            put(fields, 'booktitle', booktitle or self._escape_bibtex(venue))
            put(fields, 'editor', editor_bibtex)
        elif entry_type == 'book':
            put(fields, 'editor', editor_bibtex)
            # a monograph in a series keeps the series title as booktitle
            if booktitle and booktitle.strip().lower() != title_escaped.strip().lower():
                put(fields, 'booktitle', booktitle)
        else:
            put(fields, 'note', f"Preprint: {venue}" if venue else 'Preprint')

        put(fields, 'year', year)
        if entry_type == 'article':
            put(fields, 'volume', article.get('volume', ''))
            put(fields, 'number', article.get('issue', ''))
        if entry_type in ('article', 'incollection'):
            put(fields, 'pages', pages)
        if entry_type in ('incollection', 'book'):
            put(fields, 'publisher', publisher)
            put(fields, 'address', place)
            put(fields, 'isbn', article.get('isbn', ''))
        if include_abstract:
            put(fields, 'abstract', abstract)
        put(fields, 'doi', doi)
        put(fields, 'url', doi_url)
        put(fields, 'pdf', pdf_url)
        put(fields, 'abbr', abbr)
        fields.append("  selected  = {false}")

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
            'volume', 'issue', 'first_page', 'last_page', 'pages', 'volume_pages',
            'citation_detail'
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
                    'pages': a.get('pages', '') or format_page_range(
                        a.get('first_page'), a.get('last_page')),
                    'volume_pages': a.get('volume_pages', ''),
                    'citation_detail': format_citation_detail(
                        a.get('year'), a.get('volume'),
                        a.get('pages') or format_page_range(
                            a.get('first_page'), a.get('last_page'))),
                })

        print(f"Wrote {len(articles)} entries to {output_path}")

    def _is_preprint(self, article):
        """Return True if the work is a preprint / working paper (e.g. CrimRxiv)."""
        entry_type = article.get('entry_type') or bibtex_entry_type(
            article.get('work_type', ''), article.get('publication_venue', ''))
        return entry_type == 'misc'

    def _make_slug(self, title, max_len=80):
        """Generate a URL-safe directory slug from a title (matches existing convention)."""
        slug = title.lower()
        slug = re.sub(r'[^\w\s-]', '', slug)   # drop punctuation except hyphens
        slug = re.sub(r'\s+', '-', slug)         # spaces → hyphens
        slug = re.sub(r'-+', '-', slug)          # collapse runs
        return slug[:max_len]

    # Record types and DOI prefixes that identify a deposit (dataset, code
    # archive, journal appendix) rather than a publication of its own.
    DEPOSIT_TYPES = {'dataset', 'software', 'supplementary-material',
                     'supplementary-materials'}
    DEPOSIT_DOI_PREFIXES = ('10.5281/',   # Zenodo
                            '10.6084/',   # figshare
                            '10.5061/',   # Dryad
                            '10.15468/')  # GBIF

    def _is_deposit(self, article):
        """True for datasets, code archives and journal appendices.

        These get no page of their own: they are surfaced as Code/Data links on
        the parent paper's page via data/paper_links.yml, so listing them
        separately in research.qmd would duplicate the same work.
        """
        if (article.get('work_type') or article.get('type') or '').lower() in self.DEPOSIT_TYPES:
            return True
        return self._norm_doi(article.get('doi')).startswith(self.DEPOSIT_DOI_PREFIXES)

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
        # Reference fields, each also a column in data/publications.csv so the
        # two stay in step: year / volume / pages feed the listing table in
        # research.qmd, volume-pages is the combined form.
        year = str(date)[:4]
        if year:
            lines.append(f'year: "{year}"')
        if article.get('volume'):
            lines.append(f"volume: \"{article['volume']}\"")
        page_range = format_page_range(article.get('first_page'), article.get('last_page'))
        if page_range:
            lines.append(f'pages: "{page_range}"')
        detail = format_citation_detail(year, article.get('volume'), page_range)
        if detail:
            lines.append(f'citation-detail: "{detail}"')
        vol_pages = article.get('volume_pages') or format_volume_pages(
            article.get('volume'), article.get('first_page'), article.get('last_page'))
        if vol_pages:
            lines.append(f'volume-pages: "{vol_pages}"')
        # Book / chapter fields: the host volume, its editors and imprint, plus
        # the ISBN. They carry the same values as the BibTeX record, so the
        # rendered reference below can be rebuilt from the page alone (that is
        # what _tools/add-volume-pages.py does on a backfill run).
        entry_type = article.get('entry_type') or bibtex_entry_type(
            article.get('work_type', ''), venue)
        all_authors = article.get('all_authors') or []
        authors_full = format_name_list(all_authors) if all_authors else author
        editors = article.get('editors') or []
        if entry_type != 'article':
            lines.append(f'pub-type: "{entry_type}"')
        if authors_full:
            lines.append(f'authors-full: "{self._yaml_escape(authors_full)}"')
        for key, value in (('booktitle', article.get('booktitle')),
                           ('editors', ' and '.join(editors)),
                           ('publisher', article.get('publisher')),
                           ('place', article.get('place')),
                           ('isbn', article.get('isbn'))):
            if value:
                lines.append(f'{key}: "{self._yaml_escape(str(value))}"')
        if doi:
            lines += [f'doi: {doi}', f'citation-url: {doi_url}']
        lines += ['format:', '  html:', '    toc: true', '---', '']

        # The rendered reference, between sentinels so a backfill run replaces
        # it instead of stacking a second copy. Styling: .full-reference in
        # html/pedroj.scss.
        full_ref = article.get('full_reference') or format_full_reference(
            entry_type=entry_type,
            authors=all_authors or author,
            year=year,
            title=title,
            journal=venue if entry_type in ('article', 'misc') else '',
            volume=article.get('volume'),
            pages=article.get('pages') or format_page_range(
                article.get('first_page'), article.get('last_page')),
            booktitle=article.get('booktitle'),
            editors=editors,
            publisher=article.get('publisher'),
            place=article.get('place'),
            doi=doi,
            url=doi_url,
            note='Preprint' if entry_type == 'misc' else '',
        )
        if full_ref:
            lines += [REF_START, '::: {.full-reference}', full_ref, ':::', REF_END, '']

        if is_preprint:
            lines += [
                '::: {.callout-warning}',
                '## Preprint',
                'This is a preprint and has not undergone peer review. Interpret findings with caution.',
                ':::',
                '',
            ]

        # Venue and open-access status share one line: two short fields read
        # better side by side than as two stacked paragraphs.
        # For a chapter the useful "where" is the host volume, not the
        # publishing platform OpenAlex records as the source ("CABI Publishing
        # eBooks"); for a book it is the imprint.
        venue_display = venue
        if entry_type == 'incollection' and article.get('booktitle'):
            venue_display = article['booktitle']
        elif entry_type == 'book' and article.get('publisher'):
            venue_display = article['publisher']
        venue_line = f'**Published in:** {venue_display}' if venue_display else ''
        oa_line = f"**Open Access:** {'Yes' if is_oa else 'No'}"
        lines += [
            '## Publication Details',
            '',
            f'{venue_line}{FIELD_GAP}{oa_line}' if venue_line else oa_line,
            '',
        ]
        # The badges carry the citation count themselves (Dimensions) plus the
        # attention score, so they stand in for the static "Citations:" line —
        # which came from the OpenAlex snapshot and went stale between syncs.
        # Papers with no DOI get no badges, so they keep the plain count.
        badges = badge_block(doi)
        lines.append(badges if badges else f'**Citations:** {citations}')

        # Links are emitted as a .paper-links div with per-link classes; the
        # grey button styling lives in html/pedroj.scss. The DOI link carries
        # .paper-link-primary (darker fill) as the primary action.
        link_parts = []
        if doi_url:
            link_parts.append(f'[DOI Link]({doi_url}){{.paper-link-primary}}')
        if pdf_url:
            link_parts.append(f'[PDF]({pdf_url})')
        if openalex_url:
            link_parts.append(f'[OpenAlex]({openalex_url})')

        # Code / data / other links for this paper, from data/paper_links.yml
        extra = self.paper_links.get(self._norm_doi(doi), {})
        code_url, data_url = extra.get('code'), extra.get('data')
        if code_url and code_url == data_url:
            link_parts.append(f'[Code & data]({code_url})')
        else:
            if code_url:
                link_parts.append(f'[Code]({code_url})')
            if data_url:
                link_parts.append(f'[Data]({data_url})')
        for item in extra.get('extra') or []:
            if isinstance(item, dict) and item.get('url'):
                link_parts.append(f"[{item.get('label', 'Link')}]({item['url']})")

        if link_parts:
            lines += ['', '## Links', '', '::: {.paper-links}',
                      *link_parts, ':::']

        # The page's own BibTeX record, built from the same fields as the entry
        # in _bibliography/papers.bib. The abstract is left out here only: it
        # belongs in the .bib file, but would swamp the code block on the page.
        bib_entry = self.create_bibtex_entry(article, include_abstract=False)
        if bib_entry:
            lines += ['', '## BibTeX', '', '```bibtex', bib_entry, '```']

        lines.append('')
        return '\n'.join(lines)

    @staticmethod
    def _yaml_escape(value):
        """Escape a scalar for a double-quoted YAML front-matter value."""
        return str(value).replace('\\', '\\\\').replace('"', '\\"')

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
        skipped_deposits = 0

        for article in articles:
            # Deposits are linked from their parent paper (data/paper_links.yml)
            # instead of getting a page, so they stay out of the publications
            # listing. Any page previously generated for one is removed by the
            # stale-page pass below.
            if self._is_deposit(article):
                skipped_deposits += 1
                continue
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

        if skipped_deposits:
            print(f"  Skipped {skipped_deposits} deposit record(s) "
                  f"(datasets/code/appendices - linked from their parent paper)")
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
