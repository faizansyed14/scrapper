"""
Scrapling UI — Web Scraper Dashboard
Flask app with concurrent page fetching and smart duplicate detection.

Key improvements over v1:
  1. Pre-load DB fingerprints once per scrape run (set lookup, no per-job DB queries).
  2. Page-level duplicate tracking: stop only when N consecutive pages have ZERO new jobs.
     This correctly ignores sponsored/pinned jobs that repeat on every page.
  3. Concurrent page fetching via ThreadPoolExecutor (BATCH_SIZE=3 pages in parallel).
     Results are processed in page-order so stop logic remains accurate.
  4. Batch DB inserts per page — one transaction per page instead of one per job.
"""

import os
import sys
import json
import uuid
import threading
import traceback
import re
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, render_template, request, jsonify, send_file
import database
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'scrapling-ui-secret-key-fallback')

database.init_db()

# In-memory job-run storage
scrape_jobs: dict = {}

# ─── Constants ────────────────────────────────────────────────────────────────

# How many pages to fetch in parallel.
# 3 is safe — aggressive enough to be fast, gentle enough to avoid blocks.
CONCURRENT_PAGES = 3

# Stop when this many consecutive pages contain ZERO new jobs.
# 2 means: we need 2 full pages of 100% old data before we declare "done".
# This handles transition pages (e.g. page where 9 are old, 1 is new).
STOP_AFTER_DUPE_PAGES = 2


# ─── Utilities ────────────────────────────────────────────────────────────────

def get_absolute_date(relative_str: str) -> str:
    """Convert relative time strings to YYYY-MM-DD format."""
    if not relative_str:
        return ""

    relative_str = relative_str.lower().strip()
    now = datetime.now()

    if any(x in relative_str for x in ['active', 'just now', 'today']):
        return now.strftime('%Y-%m-%d')

    if 'yesterday' in relative_str:
        return (now - timedelta(days=1)).strftime('%Y-%m-%d')

    match = re.search(r'(\d+)\s*(min|hour|hr|day|week|month|year)s?', relative_str)
    if match:
        val = int(match.group(1))
        unit = match.group(2)
        if unit == 'min':
            return now.strftime('%Y-%m-%d')
        elif unit in ['hour', 'hr']:
            return now.strftime('%Y-%m-%d')
        elif unit == 'day':
            return (now - timedelta(days=val)).strftime('%Y-%m-%d')
        elif unit == 'week':
            return (now - timedelta(weeks=val)).strftime('%Y-%m-%d')
        elif unit == 'month':
            return (now - timedelta(days=val * 30)).strftime('%Y-%m-%d')
        elif unit == 'year':
            return (now - timedelta(days=val * 365)).strftime('%Y-%m-%d')

    try:
        clean_str = relative_str
        for fmt in ('%d %b %Y', '%d %B %Y', '%d %b', '%d %B',
                    '%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%d'):
            try:
                dt = datetime.strptime(clean_str, fmt)
                if '%Y' not in fmt:
                    dt = dt.replace(year=now.year)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                continue
    except Exception:
        pass

    return relative_str


def make_fingerprint(title: str, company: str, location: str, source: str) -> str:
    """Must match database._make_fingerprint exactly."""
    return (
        f"{(title or '').lower().strip()}"
        f"|{(company or '').lower().strip()}"
        f"|{(location or '').lower().strip()}"
        f"|{(source or '').lower().strip()}"
    )


def parse_relative_time(time_str: str) -> float:
    """Convert time string to minutes-ago float (for sorting)."""
    if not time_str:
        return float('inf')

    time_str = str(time_str).lower()
    if 'active' in time_str or 'just now' in time_str:
        return 0

    match = re.search(r'(\d+)\s*(min|hour|hr|day|week|month|year)s?', time_str)
    if match:
        val = int(match.group(1))
        unit = match.group(2)
        if unit == 'min':      return val
        if unit in ['hour', 'hr']: return val * 60
        if unit == 'day':      return val * 24 * 60
        if unit == 'week':     return val * 7 * 24 * 60
        if unit == 'month':    return val * 30 * 24 * 60
        if unit == 'year':     return val * 365 * 24 * 60

    try:
        dt = datetime.strptime(time_str, '%Y-%m-%d')
        return (datetime.now() - dt).total_seconds() / 60
    except Exception:
        pass

    return float('inf')


# ─── Low-level page fetcher (runs in thread pool) ─────────────────────────────

def _fetch_page(url: str, page_num: int):
    from scrapling.fetchers import StealthyFetcher
    try:
        print(f"  → Fetching page {page_num}: {url}")
        page = StealthyFetcher.fetch(
            url,
            headless=True,
            network_idle=False,   # don't wait for all network requests to settle
            block_images=True,    # cancel image downloads at browser level
        )
        return page_num, page
    except Exception as e:
        print(f"  ✗ Page {page_num} failed: {e}")
        return page_num, None


def _fetch_pages_concurrent(page_specs: list[tuple[int, str]]) -> dict:
    """
    Fetch a batch of (page_num, url) pairs concurrently.
    Returns dict {page_num: page_object_or_None}.
    """
    results = {}
    with ThreadPoolExecutor(max_workers=len(page_specs)) as executor:
        futures = {
            executor.submit(_fetch_page, url, pn): pn
            for pn, url in page_specs
        }
        for future in as_completed(futures):
            pn, page = future.result()
            results[pn] = page
    return results


# ─── Per-page job processors ──────────────────────────────────────────────────
# Each returns a list of job dicts extracted from the page HTML.

def _parse_naukrigulf_page(page, page_num: int) -> list[dict]:
    jobs = []
    cards = page.css('.srp-tuple')
    for card in cards:
        title_el  = card.css('.designation-title::text') or card.css('.title::text')
        company_el = card.css('.info-org::text')
        spans     = card.css('span:not([class])::text').getall()
        time_el   = card.css('.time::text')

        job = {
            'title':      (title_el.get('') if title_el else '').strip(),
            'company':    (company_el.get('') if company_el else '').strip(),
            'location':   spans[1].strip() if len(spans) > 1 else '',
            'experience': spans[0].strip() if len(spans) > 0 else '',
            'posted':     get_absolute_date((time_el.get('') if time_el else '').strip()),
            'source':     'Naukrigulf',
            'page':       page_num,
        }
        if job['title']:
            jobs.append(job)
    return jobs


def _parse_linkedin_page(page, page_num: int) -> list[dict]:
    jobs = []
    cards = (
        page.css('.base-card') or
        page.css('.job-search-card') or
        page.css('[data-entity-urn*="jobPosting"]') or
        page.css('.jobs-search__results-list li') or
        page.css('.result-card') or
        page.css('ul.jobs-search__results-list > li')
    )
    for card in cards:
        title_el = (
            card.css('.base-search-card__title::text') or
            card.css('.job-search-card__title::text') or
            card.css('h3::text') or
            card.css('[class*="title"]::text')
        )
        company_el = (
            card.css('.base-search-card__subtitle::text') or
            card.css('.job-search-card__subtitle-link::text') or
            card.css('h4 a::text') or
            card.css('[class*="company"]::text')
        )
        loc_el = (
            card.css('.job-search-card__location::text') or
            card.css('.base-search-card__metadata span::text') or
            card.css('[class*="location"]::text')
        )
        date_el    = (
            card.css('time::text') or
            card.css('.job-search-card__listdate::text') or
            card.css('[class*="date"]::text')
        )
        posted_raw = (date_el.get('') if date_el else '').strip()
        if not posted_raw:
            time_tag = card.css('time')
            if time_tag:
                posted_raw = time_tag[0].attrib.get('datetime', '')

        job = {
            'title':      (title_el.get('') if title_el else '').strip(),
            'company':    (company_el.get('') if company_el else '').strip(),
            'location':   (loc_el.get('') if loc_el else '').strip(),
            'experience': '',
            'posted':     get_absolute_date(posted_raw),
            'source':     'LinkedIn',
            'page':       page_num,
        }
        if job['title']:
            jobs.append(job)
    return jobs


def _parse_gulftalent_page(page, page_num: int) -> list[dict]:
    jobs = []
    rows = page.css('tr.content-visibility-auto')
    for row in rows:
        title_el   = row.css('h2.title a::text')
        company_el = row.css('td:first-child a.text-muted::text')
        loc_el     = row.css('td.col-sm-6 span::text')
        date_el    = row.css('td.col-sm-4::text')

        job = {
            'title':      (title_el.get('') if title_el else '').strip(),
            'company':    (company_el.get('') if company_el else '').strip(),
            'location':   (loc_el.get('') if loc_el else '').strip(),
            'experience': '',
            'posted':     get_absolute_date((date_el.get('') if date_el else '').strip()),
            'source':     'GulfTalent',
            'page':       page_num,
        }
        if job['title']:
            jobs.append(job)
    return jobs


def _parse_bayt_page(page, page_num: int) -> list[dict]:
    jobs = []
    cards = page.css('li.has-pointer-d')
    for card in cards:
        title_el   = card.css('h2 a::text')
        company_el = card.css('.job-company-location-wrapper a.t-bold::text')
        loc_el     = card.css('.job-company-location-wrapper div.t-small a:first-child span::text')
        date_el    = card.css('.jb-date span::text')
        exp_el     = card.css('.jb-label-careerlevel::text')

        title = (title_el.get('') if title_el else '').strip()
        if not title or 'Mobile App' in title:
            continue

        job = {
            'title':      title,
            'company':    (company_el.get('') if company_el else '').strip(),
            'location':   (loc_el.get('') if loc_el else '').strip(),
            'experience': (exp_el.get('') if exp_el else '').strip(),
            'posted':     get_absolute_date((date_el.get('') if date_el else '').strip()),
            'source':     'Bayt',
            'page':       page_num,
        }
        jobs.append(job)
    return jobs


# ─── Core scraping engine ─────────────────────────────────────────────────────

def _build_page_url(base_url: str, page_num: int, site: str) -> str:
    """Return the correct paginated URL for a given site and page number."""
    if site == 'naukrigulf':
        if page_num == 1:
            return base_url
        if '?' in base_url:
            return f"{base_url}&pageNo={page_num}"
        return f"{base_url.rstrip('/')}-{page_num}"

    elif site == 'linkedin':
        start = (page_num - 1) * 25
        if 'linkedin.com/jobs/search' in base_url:
            api_base = base_url.replace(
                'linkedin.com/jobs/search',
                'linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search'
            )
            sep = '&' if '?' in api_base else '?'
            return f"{api_base}{sep}start={start}"
        if page_num == 1:
            return base_url
        sep = '&' if '?' in base_url else '?'
        return f"{base_url}{sep}start={start}"

    elif site == 'gulftalent':
        if page_num == 1:
            return base_url
        return f"{base_url.rstrip('/')}/{page_num}"

    elif site == 'bayt':
        if page_num == 1:
            return base_url
        sep = '&' if '?' in base_url else '?'
        return f"{base_url}{sep}page={page_num}"

    return base_url


def _get_parser(site: str):
    parsers = {
        'naukrigulf': _parse_naukrigulf_page,
        'linkedin':   _parse_linkedin_page,
        'gulftalent': _parse_gulftalent_page,
        'bayt':       _parse_bayt_page,
    }
    return parsers.get(site)


def _scrape_site(url: str, site: str, max_pages: int) -> list[dict]:
    """
    Generic concurrent scraping engine used by all site scrapers.

    Algorithm
    ---------
    1. Load all existing DB fingerprints into a set (single query).
    2. Fetch pages in batches of CONCURRENT_PAGES in parallel.
    3. For each page (processed in order):
       a. Extract all job cards.
       b. Skip intra-session duplicates (sponsored/pinned jobs that repeat every page).
       c. Check each new job against DB fingerprints (O(1)).
       d. Accumulate: new_this_page vs old_this_page counts.
    4. After processing all pages in a batch, decide:
       - If a page had ANY new jobs → reset consecutive-dupe-page counter.
       - If a page had ZERO new jobs → increment counter.
       - If counter >= STOP_AFTER_DUPE_PAGES → stop fetching more pages.
    5. Batch-insert all new jobs from the page into DB at once.
    """
    source_name = {
        'naukrigulf': 'Naukrigulf',
        'linkedin':   'LinkedIn',
        'gulftalent': 'GulfTalent',
        'bayt':       'Bayt',
    }.get(site, site.title())

    parser = _get_parser(site)
    if not parser:
        print(f"[!] No parser for site: {site}")
        return []

    # Step 1: Pre-load fingerprints
    db_fingerprints: set = database.load_fingerprints(source_name)

    all_new_jobs: list[dict] = []
    seen_in_run: set         = set()   # intra-session dedup (handles sponsored jobs)
    consecutive_dupe_pages   = 0
    page_num                 = 1

    while page_num <= max_pages:
        # Build batch of (page_num, url) pairs
        batch: list[tuple[int, str]] = []
        for i in range(CONCURRENT_PAGES):
            pn = page_num + i
            if pn > max_pages:
                break
            batch.append((pn, _build_page_url(url, pn, site)))

        if not batch:
            break

        print(f"\n[{source_name}] Fetching pages {batch[0][0]}–{batch[-1][0]} concurrently...")

        # Step 2: Concurrent fetch
        fetched = _fetch_pages_concurrent(batch)

        # Step 3 & 4: Process in page order
        should_stop = False
        for pn, page_url in batch:
            page = fetched.get(pn)
            if page is None:
                print(f"  ✗ Page {pn} returned None — stopping.")
                should_stop = True
                break

            raw_jobs = parser(page, pn)
            if not raw_jobs:
                print(f"  ✗ Page {pn} had no job cards — stopping.")
                should_stop = True
                break

            new_this_page: list[dict] = []
            new_count  = 0
            dupe_count = 0

            for job in raw_jobs:
                # Intra-session key: catches sponsored/pinned jobs that repeat on every page
                session_key = (
                    job['title'].lower().strip(),
                    job['company'].lower().strip(),
                    job['location'].lower().strip(),
                )
                if session_key in seen_in_run:
                    # Sponsored/pinned — skip silently, do NOT count toward dupe logic
                    continue
                seen_in_run.add(session_key)

                fp = make_fingerprint(
                    job['title'], job['company'], job['location'], job['source']
                )

                if fp in db_fingerprints:
                    dupe_count += 1
                else:
                    new_count += 1
                    new_this_page.append(job)
                    db_fingerprints.add(fp)  # update local cache so intra-batch dupes are caught

            print(
                f"  ✓ Page {pn}: {new_count} new | {dupe_count} already-in-db "
                f"| dupe-page streak: {consecutive_dupe_pages}"
            )

            # Step 5: Batch insert new jobs from this page
            if new_this_page:
                database.save_jobs_batch(new_this_page)
                all_new_jobs.extend(new_this_page)
                consecutive_dupe_pages = 0          # reset — we found something new
            else:
                if dupe_count > 0:
                    # Full page of old data
                    consecutive_dupe_pages += 1
                    print(
                        f"  ⚠ Page {pn} is 100% old data. "
                        f"Streak: {consecutive_dupe_pages}/{STOP_AFTER_DUPE_PAGES}"
                    )
                    if consecutive_dupe_pages >= STOP_AFTER_DUPE_PAGES:
                        print(
                            f"  ⛔ {STOP_AFTER_DUPE_PAGES} consecutive pages of old data — "
                            f"reached previously scraped territory. Stopping."
                        )
                        should_stop = True
                        break
                # else: page was 0 new AND 0 old (e.g. all sponsored) — don't penalise

        if should_stop:
            break

        page_num += CONCURRENT_PAGES

    print(f"\n[{source_name}] Done. {len(all_new_jobs)} new jobs found.")
    return all_new_jobs


# ─── Public scraper functions ─────────────────────────────────────────────────

def scrape_naukrigulf(url: str, max_pages: int = 5) -> list[dict]:
    return _scrape_site(url, 'naukrigulf', max_pages)


def scrape_linkedin(url: str, max_pages: int = 5) -> list[dict]:
    return _scrape_site(url, 'linkedin', max_pages)


def scrape_gulftalent(url: str, max_pages: int = 5) -> list[dict]:
    return _scrape_site(url, 'gulftalent', max_pages)


def scrape_bayt(url: str, max_pages: int = 5) -> list[dict]:
    return _scrape_site(url, 'bayt', max_pages)


def scrape_generic(url: str) -> list[dict]:
    """Scrape a generic URL and extract structured data."""
    from scrapling.fetchers import Fetcher

    all_data = []
    try:
        page = Fetcher.get(url, stealthy_headers=True, follow_redirects=True)
        if page is None:
            return all_data

        # Try tables first
        tables = page.css('table')
        if tables:
            for table in tables:
                headers = [th.css('::text').get('').strip() for th in table.css('th')]
                for row in table.css('tr'):
                    cells = row.css('td')
                    if cells:
                        row_data = {}
                        for i, cell in enumerate(cells):
                            key = headers[i] if i < len(headers) else f'Column {i + 1}'
                            row_data[key] = cell.css('::text').get('').strip()
                        if any(row_data.values()):
                            all_data.append(row_data)
            return all_data

        # Fall back to card/item heuristics
        items = (
            page.css('article') or
            page.css('[class*="card"]') or
            page.css('[class*="item"]') or
            page.css('[class*="result"]') or
            page.css('li')
        )

        for item in items[:50]:
            data = {}
            heading = item.css('h1::text, h2::text, h3::text, h4::text').get('')
            if heading:
                data['title'] = heading.strip()

            link = item.css('a')
            if link:
                data['link'] = link[0].attrib.get('href', '')
                if not data.get('title'):
                    data['title'] = link[0].css('::text').get('').strip()

            para = item.css('p::text').get('')
            if para:
                data['description'] = para.strip()

            for i, span in enumerate(item.css('span::text').getall()[:5]):
                if span.strip():
                    data[f'detail_{i + 1}'] = span.strip()

            data['source'] = 'Custom'

            if data.get('title'):
                ordered = {
                    'title':      data.get('title', ''),
                    'company':    data.get('company', ''),
                    'location':   data.get('location', ''),
                    'experience': data.get('experience', ''),
                    'posted':     get_absolute_date(data.get('posted', '')),
                    'source':     'Custom',
                }
                if database.save_job(ordered):
                    all_data.append(ordered)

    except Exception as e:
        print(f"[Generic] Error: {e}")
        traceback.print_exc()

    return all_data


# ─── Site detection ───────────────────────────────────────────────────────────

def detect_site(url: str) -> str:
    url_lower = url.lower()
    if 'naukrigulf' in url_lower: return 'naukrigulf'
    if 'linkedin'   in url_lower: return 'linkedin'
    if 'gulftalent' in url_lower: return 'gulftalent'
    if 'bayt'       in url_lower: return 'bayt'
    return 'generic'


# ─── Background runner ────────────────────────────────────────────────────────

def run_scrape(job_id: str, url: str, max_pages: int, site_type: str):
    """Run scraping in a background thread and update scrape_jobs[job_id]."""
    try:
        scrape_jobs[job_id]['status']  = 'running'
        scrape_jobs[job_id]['message'] = f'Scraping {site_type}...'

        dispatch = {
            'naukrigulf': scrape_naukrigulf,
            'linkedin':   scrape_linkedin,
            'gulftalent': scrape_gulftalent,
            'bayt':       scrape_bayt,
        }
        fn = dispatch.get(site_type, scrape_generic)

        if site_type == 'generic':
            results = fn(url)
        else:
            results = fn(url, max_pages)

        scrape_jobs[job_id]['results']      = results
        scrape_jobs[job_id]['status']       = 'completed'
        scrape_jobs[job_id]['message']      = f'Found {len(results)} new items'
        scrape_jobs[job_id]['completed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    except Exception as e:
        scrape_jobs[job_id]['status']  = 'error'
        scrape_jobs[job_id]['message'] = str(e)
        traceback.print_exc()


# ─── Excel export ─────────────────────────────────────────────────────────────

def generate_excel(data: list[dict], filename: str) -> str:
    wb = Workbook()
    ws = wb.active
    ws.title = "Scraped Data"

    os.makedirs(os.path.join(os.path.dirname(__file__), 'exports'), exist_ok=True)
    filepath = os.path.join(os.path.dirname(__file__), 'exports', filename)

    if not data:
        ws['A1'] = 'No data found'
        wb.save(filepath)
        return filepath

    column_order = ['title', 'company', 'location', 'experience', 'posted', 'source']
    actual_keys  = [k for k in column_order if any(k in row for row in data)]

    header_font      = Font(name='Segoe UI', bold=True, color='FFFFFF', size=11)
    header_fill      = PatternFill(start_color='1a1a2e', end_color='1a1a2e', fill_type='solid')
    header_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    cell_font        = Font(name='Segoe UI', size=10)
    cell_alignment   = Alignment(vertical='top', wrap_text=True)
    thin_border      = Border(
        left   = Side(style='thin', color='E0E0E0'),
        right  = Side(style='thin', color='E0E0E0'),
        top    = Side(style='thin', color='E0E0E0'),
        bottom = Side(style='thin', color='E0E0E0'),
    )
    alt_fill = PatternFill(start_color='F5F5FA', end_color='F5F5FA', fill_type='solid')

    for col, key in enumerate(actual_keys, 1):
        cell = ws.cell(row=1, column=col, value=key.replace('_', ' ').title())
        cell.font      = header_font
        cell.fill      = header_fill
        cell.alignment = header_alignment
        cell.border    = thin_border

    for row_idx, row_data in enumerate(data, 2):
        for col_idx, key in enumerate(actual_keys, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=row_data.get(key, ''))
            cell.font      = cell_font
            cell.alignment = cell_alignment
            cell.border    = thin_border
            if row_idx % 2 == 0:
                cell.fill = alt_fill

    for col_idx, key in enumerate(actual_keys, 1):
        max_length = len(key) + 4
        for row in ws.iter_rows(min_row=2, min_col=col_idx, max_col=col_idx):
            for cell in row:
                if cell.value:
                    max_length = max(max_length, min(len(str(cell.value)), 50))
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = max_length + 2

    ws.freeze_panes = 'A2'
    wb.save(filepath)
    return filepath


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/scrape', methods=['POST'])
def start_scrape():
    data      = request.json
    url       = data.get('url', '').strip()
    max_pages = int(data.get('max_pages', 5))

    if not url:
        return jsonify({'error': 'URL is required'}), 400

    site_type = data.get('site_type', 'auto')
    if site_type == 'auto':
        site_type = detect_site(url)

    job_id = str(uuid.uuid4())[:8]
    scrape_jobs[job_id] = {
        'id':           job_id,
        'url':          url,
        'site_type':    site_type,
        'status':       'queued',
        'message':      'Starting...',
        'results':      [],
        'created_at':   datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'completed_at': None,
        'max_pages':    max_pages,
    }

    thread = threading.Thread(target=run_scrape, args=(job_id, url, max_pages, site_type))
    thread.daemon = True
    thread.start()

    return jsonify({'job_id': job_id, 'site_type': site_type})


@app.route('/api/status/<job_id>')
def get_status(job_id):
    job = scrape_jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    return jsonify({
        'id':           job['id'],
        'status':       job['status'],
        'message':      job['message'],
        'result_count': len(job['results']),
        'results':      job['results'],
        'site_type':    job['site_type'],
        'url':          job['url'],
        'created_at':   job['created_at'],
        'completed_at': job['completed_at'],
    })


@app.route('/api/export/<job_id>')
def export_excel(job_id):
    job = scrape_jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    if not job['results']:
        return jsonify({'error': 'No data to export'}), 400

    results_to_export = list(job['results'])
    sort_mode = request.args.get('sort', 'default')

    if sort_mode == 'recent':
        results_to_export.sort(key=lambda x: parse_relative_time(x.get('posted', '')))
    elif sort_mode == 'oldest':
        results_to_export.sort(key=lambda x: parse_relative_time(x.get('posted', '')), reverse=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename  = f"scraped_{job['site_type']}_{timestamp}.xlsx"
    filepath  = generate_excel(results_to_export, filename)
    return send_file(filepath, as_attachment=True, download_name=filename)


@app.route('/api/history')
def get_history():
    jobs = []
    for job in scrape_jobs.values():
        jobs.append({
            'id':           job['id'],
            'url':          job['url'],
            'site_type':    job['site_type'],
            'status':       job['status'],
            'message':      job['message'],
            'result_count': len(job['results']),
            'created_at':   job['created_at'],
            'completed_at': job['completed_at'],
        })
    return jsonify(jobs)


@app.route('/api/database')
def get_database_jobs():
    source = request.args.get('source')
    return jsonify(database.get_all_jobs(source))


@app.route('/api/database/export')
def export_database():
    source = request.args.get('source')
    jobs   = database.get_all_jobs(source)
    if not jobs:
        return jsonify({'error': 'No data in database to export'}), 400

    timestamp  = datetime.now().strftime('%Y%m%d_%H%M%S')
    source_str = source.lower() if source else 'all'
    filename   = f"scraped_{source_str}_db_{timestamp}.xlsx"
    filepath   = generate_excel(jobs, filename)
    return send_file(filepath, as_attachment=True, download_name=filename)


@app.route('/api/database/clear', methods=['DELETE'])
def clear_database():
    source  = request.args.get('source')
    success = database.clear_jobs(source)
    if success:
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to clear database'}), 500


@app.route('/api/delete/<job_id>', methods=['DELETE'])
def delete_job(job_id):
    if job_id in scrape_jobs:
        del scrape_jobs[job_id]
        return jsonify({'success': True})
    return jsonify({'error': 'Job not found'}), 404


if __name__ == '__main__':
    print("\n[*] Scrapling UI is running!")
    print(f"    Concurrent pages : {CONCURRENT_PAGES}")
    print(f"    Stop after dupe pages: {STOP_AFTER_DUPE_PAGES}")
    print("    Open http://localhost:5000 in your browser\n")
    app.run(debug=True, port=5000)