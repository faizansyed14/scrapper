"""
Scrapling UI - Web Scraper Dashboard
A Flask-based UI for extracting job data from Naukrigulf, LinkedIn, and custom URLs.
"""

import os
import sys
import json
import uuid
import threading
import traceback
import re
from datetime import datetime

from flask import Flask, render_template, request, jsonify, send_file

# Add parent dir so scrapling imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

app = Flask(__name__)
app.secret_key = 'scrapling-ui-secret-key'

# In-memory storage for scrape jobs
scrape_jobs = {}

# ─── Scraping Logic ──────────────────────────────────────────────────────────


def scrape_naukrigulf(url, max_pages=5):
    """Scrape job listings from Naukrigulf."""
    from scrapling.fetchers import StealthyFetcher

    all_jobs = []

    for page_num in range(1, max_pages + 1):
        try:
            # Naukrigulf pagination pattern
            if page_num == 1:
                page_url = url
            else:
                # Handle both URL formats
                if '?' in url:
                    page_url = f"{url}&page={page_num}"
                else:
                    page_url = f"{url}?page={page_num}"

            print(f"Fetching Naukrigulf page {page_num}: {page_url}")
            page = StealthyFetcher.fetch(page_url, headless=True, network_idle=True)

            if page is None:
                break

            job_cards = page.css('.srp-tuple')

            if not job_cards:
                break

            for card in job_cards:
                job = {}

                title_el = card.css('.designation-title::text') or card.css('.title::text')
                job['title'] = title_el.get('').strip() if title_el else ''

                company_el = card.css('.info-org::text')
                job['company'] = company_el.get('').strip() if company_el else ''

                # Extract experience and location correctly
                spans = card.css('span:not([class])::text').getall()
                job['experience'] = spans[0].strip() if len(spans) > 0 else ''
                job['location'] = spans[1].strip() if len(spans) > 1 else ''

                # Add link check
                link_el = card.css('a.info-position')
                if link_el:
                    href = link_el[0].attrib.get('href', '')
                    if href and not href.startswith('http'):
                        href = 'https://www.naukrigulf.com' + href
                    job['link'] = href
                else:
                    job['link'] = ''

                # Extract time posted
                time_el = card.css('.time::text')
                job['posted'] = time_el.get('').strip() if time_el else ''
                
                job['salary'] = ''
                job['skills'] = ''

                job['source'] = 'Naukrigulf'
                job['page'] = page_num

                if job['title']:  # Only add if we found a title
                    all_jobs.append(job)

        except Exception as e:
            print(f"Error scraping Naukrigulf page {page_num}: {e}")
            traceback.print_exc()
            break

    return all_jobs


def scrape_linkedin(url, max_pages=5):
    """Scrape job listings from LinkedIn."""
    from scrapling.fetchers import StealthyFetcher

    all_jobs = []

    for page_num in range(max_pages):
        try:
            start = page_num * 25
            if page_num == 0:
                page_url = url
            else:
                if '?' in url:
                    page_url = f"{url}&start={start}"
                else:
                    page_url = f"{url}?start={start}"

            print(f"Fetching LinkedIn page {page_num + 1}: {page_url}")
            page = StealthyFetcher.fetch(page_url, headless=True, network_idle=True)

            if page is None:
                break

            # LinkedIn job cards selectors
            job_cards = (
                page.css('.base-card') or
                page.css('.job-search-card') or
                page.css('[data-entity-urn*="jobPosting"]') or
                page.css('.jobs-search__results-list li') or
                page.css('.result-card') or
                page.css('ul.jobs-search__results-list > li')
            )

            if not job_cards:
                break

            for card in job_cards:
                job = {}

                # Title
                title_el = (
                    card.css('.base-search-card__title::text') or
                    card.css('.job-search-card__title::text') or
                    card.css('h3::text') or
                    card.css('[class*="title"]::text')
                )
                job['title'] = title_el.get('').strip() if title_el else ''

                # Company
                company_el = (
                    card.css('.base-search-card__subtitle::text') or
                    card.css('.job-search-card__subtitle-link::text') or
                    card.css('h4 a::text') or
                    card.css('[class*="company"]::text')
                )
                job['company'] = company_el.get('').strip() if company_el else ''

                # Location
                loc_el = (
                    card.css('.job-search-card__location::text') or
                    card.css('.base-search-card__metadata span::text') or
                    card.css('[class*="location"]::text')
                )
                job['location'] = loc_el.get('').strip() if loc_el else ''

                # Link
                link_el = card.css('a.base-card__full-link') or card.css('a[href*="linkedin.com/jobs"]') or card.css('a[href*="/jobs/"]')
                if link_el:
                    href = link_el[0].attrib.get('href', '')
                    if href and not href.startswith('http'):
                        href = 'https://www.linkedin.com' + href
                    job['link'] = href.split('?')[0]  # Clean tracking params
                else:
                    job['link'] = ''

                # Posted date
                date_el = card.css('time::text') or card.css('.job-search-card__listdate::text') or card.css('[class*="date"]::text')
                job['posted'] = date_el.get('').strip() if date_el else ''
                if not job['posted']:
                    time_el = card.css('time')
                    if time_el:
                        job['posted'] = time_el[0].attrib.get('datetime', '')

                job['experience'] = ''
                job['salary'] = ''
                job['skills'] = ''
                job['source'] = 'LinkedIn'
                job['page'] = page_num + 1

                if job['title']:
                    all_jobs.append(job)

        except Exception as e:
            print(f"Error scraping LinkedIn page {page_num + 1}: {e}")
            traceback.print_exc()
            break

    return all_jobs


def scrape_generic(url):
    """Scrape generic URL and extract structured data."""
    from scrapling.fetchers import Fetcher

    all_data = []

    try:
        page = Fetcher.get(url, stealthy_headers=True, follow_redirects=True)

        if page is None:
            return all_data

        # Try to find tabular data
        tables = page.css('table')
        if tables:
            for table in tables:
                headers = [th.css('::text').get('').strip() for th in table.css('th')]
                rows = table.css('tr')
                for row in rows:
                    cells = row.css('td')
                    if cells:
                        row_data = {}
                        for i, cell in enumerate(cells):
                            key = headers[i] if i < len(headers) else f'Column {i + 1}'
                            row_data[key] = cell.css('::text').get('').strip()
                        if any(row_data.values()):
                            all_data.append(row_data)
            return all_data

        # Try to find list-like items
        items = page.css('article') or page.css('[class*="card"]') or page.css('[class*="item"]') or page.css('[class*="result"]') or page.css('li')

        for item in items[:50]:  # Limit to 50 items
            data = {}

            # Extract headings
            heading = item.css('h1::text, h2::text, h3::text, h4::text').get('')
            if heading:
                data['title'] = heading.strip()

            # Extract links
            link = item.css('a')
            if link:
                data['link'] = link[0].attrib.get('href', '')
                if not data.get('title'):
                    data['title'] = link[0].css('::text').get('').strip()

            # Extract paragraphs
            para = item.css('p::text').get('')
            if para:
                data['description'] = para.strip()

            # Extract spans
            spans = item.css('span::text').getall()
            for i, span in enumerate(spans[:5]):
                if span.strip():
                    data[f'detail_{i + 1}'] = span.strip()

            data['source'] = 'Custom'

            if data.get('title'):
                all_data.append(data)

    except Exception as e:
        print(f"Error scraping generic URL: {e}")
        traceback.print_exc()

    return all_data


def detect_site(url):
    """Detect which site the URL belongs to."""
    url_lower = url.lower()
    if 'naukrigulf' in url_lower:
        return 'naukrigulf'
    elif 'linkedin' in url_lower:
        return 'linkedin'
    else:
        return 'generic'


def run_scrape(job_id, url, max_pages, site_type):
    """Run scraping in a background thread."""
    try:
        scrape_jobs[job_id]['status'] = 'running'
        scrape_jobs[job_id]['message'] = f'Scraping {site_type}...'

        if site_type == 'naukrigulf':
            results = scrape_naukrigulf(url, max_pages)
        elif site_type == 'linkedin':
            results = scrape_linkedin(url, max_pages)
        else:
            results = scrape_generic(url)

        scrape_jobs[job_id]['results'] = results
        scrape_jobs[job_id]['status'] = 'completed'
        scrape_jobs[job_id]['message'] = f'Found {len(results)} items'
        scrape_jobs[job_id]['completed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    except Exception as e:
        scrape_jobs[job_id]['status'] = 'error'
        scrape_jobs[job_id]['message'] = str(e)
        traceback.print_exc()


# ─── Excel Export ─────────────────────────────────────────────────────────────

def parse_relative_time(time_str):
    if not time_str:
        return float('inf')
    
    time_str = str(time_str).lower()
    if 'active' in time_str or 'just now' in time_str:
        return 0
        
    match = re.search(r'(\d+)\s*(min|hour|hr|day|week|month|year)s?', time_str)
    if match:
        val = int(match.group(1))
        unit = match.group(2)
        
        if unit == 'min': return val
        if unit in ['hour', 'hr']: return val * 60
        if unit == 'day': return val * 24 * 60
        if unit == 'week': return val * 7 * 24 * 60
        if unit == 'month': return val * 30 * 24 * 60
        if unit == 'year': return val * 365 * 24 * 60
        
    try:
        from datetime import datetime as dt_parser
        dt = dt_parser.strptime(time_str, '%Y-%m-%dT%H:%M:%S.%fZ')
        return (datetime.now() - dt).total_seconds() / 60
    except:
        pass
        
    return float('inf')


def generate_excel(data, filename):
    """Generate a styled Excel file from scraped data."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Scraped Data"

    if not data:
        ws['A1'] = 'No data found'
        filepath = os.path.join(os.path.dirname(__file__), 'exports', filename)
        wb.save(filepath)
        return filepath

    # Get all unique keys
    all_keys = []
    for row in data:
        for key in row.keys():
            if key not in all_keys:
                all_keys.append(key)

    # Styling
    header_font = Font(name='Segoe UI', bold=True, color='FFFFFF', size=11)
    header_fill = PatternFill(start_color='1a1a2e', end_color='1a1a2e', fill_type='solid')
    header_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    cell_font = Font(name='Segoe UI', size=10)
    cell_alignment = Alignment(vertical='top', wrap_text=True)
    thin_border = Border(
        left=Side(style='thin', color='E0E0E0'),
        right=Side(style='thin', color='E0E0E0'),
        top=Side(style='thin', color='E0E0E0'),
        bottom=Side(style='thin', color='E0E0E0'),
    )
    alt_fill = PatternFill(start_color='F5F5FA', end_color='F5F5FA', fill_type='solid')

    # Write headers
    for col, key in enumerate(all_keys, 1):
        cell = ws.cell(row=1, column=col, value=key.replace('_', ' ').title())
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    # Write data
    for row_idx, row_data in enumerate(data, 2):
        for col_idx, key in enumerate(all_keys, 1):
            value = row_data.get(key, '')
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.font = cell_font
            cell.alignment = cell_alignment
            cell.border = thin_border
            if row_idx % 2 == 0:
                cell.fill = alt_fill

    # Auto-adjust column widths
    for col_idx, key in enumerate(all_keys, 1):
        max_length = len(key) + 4
        for row in ws.iter_rows(min_row=2, min_col=col_idx, max_col=col_idx):
            for cell in row:
                if cell.value:
                    max_length = max(max_length, min(len(str(cell.value)), 50))
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = max_length + 2

    # Freeze top row
    ws.freeze_panes = 'A2'

    filepath = os.path.join(os.path.dirname(__file__), 'exports', filename)
    wb.save(filepath)
    return filepath


# ─── Routes ───────────────────────────────────────────────────────────────────


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/scrape', methods=['POST'])
def start_scrape():
    """Start a scraping job."""
    data = request.json
    url = data.get('url', '').strip()
    max_pages = int(data.get('max_pages', 5))

    if not url:
        return jsonify({'error': 'URL is required'}), 400

    # Auto-detect site type
    site_type = data.get('site_type', 'auto')
    if site_type == 'auto':
        site_type = detect_site(url)

    job_id = str(uuid.uuid4())[:8]
    scrape_jobs[job_id] = {
        'id': job_id,
        'url': url,
        'site_type': site_type,
        'status': 'queued',
        'message': 'Starting...',
        'results': [],
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'completed_at': None,
        'max_pages': max_pages,
    }

    # Run scraping in background thread
    thread = threading.Thread(target=run_scrape, args=(job_id, url, max_pages, site_type))
    thread.daemon = True
    thread.start()

    return jsonify({'job_id': job_id, 'site_type': site_type})


@app.route('/api/status/<job_id>')
def get_status(job_id):
    """Get the status of a scraping job."""
    job = scrape_jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    return jsonify({
        'id': job['id'],
        'status': job['status'],
        'message': job['message'],
        'result_count': len(job['results']),
        'results': job['results'],
        'site_type': job['site_type'],
        'url': job['url'],
        'created_at': job['created_at'],
        'completed_at': job['completed_at'],
    })


@app.route('/api/export/<job_id>')
def export_excel(job_id):
    """Export scraping results to Excel."""
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
    filename = f"scraped_{job['site_type']}_{timestamp}.xlsx"
    filepath = generate_excel(results_to_export, filename)

    return send_file(filepath, as_attachment=True, download_name=filename)


@app.route('/api/history')
def get_history():
    """Get all scraping jobs."""
    jobs = []
    for job in scrape_jobs.values():
        jobs.append({
            'id': job['id'],
            'url': job['url'],
            'site_type': job['site_type'],
            'status': job['status'],
            'message': job['message'],
            'result_count': len(job['results']),
            'created_at': job['created_at'],
            'completed_at': job['completed_at'],
        })
    return jsonify(jobs)


@app.route('/api/delete/<job_id>', methods=['DELETE'])
def delete_job(job_id):
    """Delete a scraping job."""
    if job_id in scrape_jobs:
        del scrape_jobs[job_id]
        return jsonify({'success': True})
    return jsonify({'error': 'Job not found'}), 404


if __name__ == '__main__':
    print("\n[*] Scrapling UI is running!")
    print("    Open http://localhost:5000 in your browser\n")
    app.run(debug=True, port=5000)
