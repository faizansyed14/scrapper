"""
database.py — Job storage with fast fingerprint-based dedup support.

Key additions vs original:
  - load_fingerprints()  : pre-loads all known job keys into a set for O(1) lookup
  - save_jobs_batch()    : bulk insert many jobs in one transaction (fast)
  - save_job()           : unchanged single-insert API (still used where needed)
"""

import os
import sqlite3
from datetime import datetime

# Optional support for PostgreSQL
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor, execute_values
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

DB_FILE = os.path.join(os.path.dirname(__file__), 'scraped_jobs.db')

COUNTRY_ALIASES = {
    'uae': 'UAE',
    'ksa': 'KSA',
    'qatar': 'Qatar',
    'kuwait': 'Kuwait',
}


def normalize_country(country: str) -> str:
    """Canonical country label — prevents Uae/UAE duplicates."""
    if not country:
        return ''
    return COUNTRY_ALIASES.get(country.strip().lower(), country.strip())


# ─── Connection helpers ────────────────────────────────────────────────────────

def get_db_url():
    return os.environ.get('DATABASE_URL')


def is_postgres():
    url = get_db_url()
    return HAS_POSTGRES and url and url.startswith('postgres')


def get_db_connection():
    if is_postgres():
        conn = psycopg2.connect(get_db_url())
        return conn
    else:
        conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode: much faster concurrent writes without locking
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        return conn


# ─── Schema ───────────────────────────────────────────────────────────────────

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    if is_postgres():
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS jobs (
                id        SERIAL PRIMARY KEY,
                title     TEXT NOT NULL,
                company   TEXT NOT NULL,
                location  TEXT,
                experience TEXT,
                posted    TEXT,
                source    TEXT NOT NULL,
                country   TEXT DEFAULT '',
                scrape_id TEXT DEFAULT '',
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_ict    BOOLEAN DEFAULT FALSE,
                ict_category TEXT,
                date_precision TEXT DEFAULT 'precise',
                UNIQUE(title, company, location, source, country)
            )
        ''')
    else:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS jobs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT NOT NULL,
                company    TEXT NOT NULL,
                location   TEXT,
                experience TEXT,
                posted     TEXT,
                source     TEXT NOT NULL,
                country    TEXT DEFAULT '',
                scrape_id  TEXT DEFAULT '',
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_ict     BOOLEAN DEFAULT 0,
                ict_category TEXT,
                date_precision TEXT DEFAULT 'precise',
                UNIQUE(title, company, location, source, country)
            )
        ''')
        # Auto-migrate: add columns if missing
        for col, col_type in [('country', 'TEXT DEFAULT \'\''), ('scrape_id', 'TEXT DEFAULT \'\''), ('is_ict', 'BOOLEAN DEFAULT 0'), ('ict_category', 'TEXT'), ('date_precision', 'TEXT DEFAULT \'precise\'')]:
            try:
                cursor.execute(f"ALTER TABLE jobs ADD COLUMN {col} {col_type}")
                print(f'[DB] Migrated: added {col} column')
            except Exception:
                pass

    conn.commit()
    conn.close()


# ─── Fingerprint pre-loader (the key to smart dedup) ─────────────────────────

def load_fingerprints(source: str | None = None, country: str | None = None) -> set:
    """
    Return a set of lowercase fingerprint strings for every job in the DB.
    Fingerprint: "{title}|{company}|{location}|{source}|{country}" (lowercase/stripped)
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    pg = is_postgres()
    where, params = _build_where(source, country, pg)

    cursor.execute(
        f'SELECT title, company, location, source, country FROM jobs {where}',
        params
    )

    fingerprints = set()
    for row in cursor.fetchall():
        row = dict(row)
        fp = _make_fingerprint(
            row['title'], row['company'], row['location'], row['source'], row.get('country', '')
        )
        fingerprints.add(fp)

    conn.close()
    print(f"[DB] Loaded {len(fingerprints)} fingerprints (source={source or 'all'}, country={country or 'all'})")
    return fingerprints


def _make_fingerprint(title: str, company: str, location: str, source: str, country: str = '') -> str:
    """Canonical fingerprint — lowercase, stripped, pipe-separated."""
    return (
        f"{(title or '').lower().strip()}"
        f"|{(company or '').lower().strip()}"
        f"|{(location or '').lower().strip()}"
        f"|{(source or '').lower().strip()}"
        f"|{(country or '').lower().strip()}"
    )


# ─── Single-job insert ────────────────────────────────────────────────────────

def save_job(job: dict) -> bool:
    """
    Insert one job.  Returns True if inserted (new), False if duplicate.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    title      = job.get('title', '')
    company    = job.get('company', '')
    location   = job.get('location', '')
    experience = job.get('experience', '')
    posted     = job.get('posted', '')
    source     = job.get('source', '')
    country    = normalize_country(job.get('country', ''))
    scrape_id  = job.get('scrape_id', '')
    is_ict     = 1 if job.get('_is_ict') else 0
    ict_category = job.get('ict_category', '')

    try:
        if is_postgres():
            cursor.execute('''
                INSERT INTO jobs (title, company, location, experience, posted, source, country, scrape_id, is_ict, ict_category)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (title, company, location, source, country) DO NOTHING
                RETURNING id
            ''', (title, company, location, experience, posted, source, country, scrape_id, is_ict, ict_category))
            inserted = cursor.fetchone() is not None
            conn.commit()
            return inserted
        else:
            cursor.execute('''
                INSERT OR IGNORE INTO jobs (title, company, location, experience, posted, source, country, scrape_id, is_ict, ict_category)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (title, company, location, experience, posted, source, country, scrape_id, is_ict, ict_category))
            conn.commit()
            return cursor.rowcount > 0

    except Exception as e:
        print(f"[DB] save_job error: {e}")
        return False
    finally:
        conn.close()


# ─── Batch insert (fast) ──────────────────────────────────────────────────────

def save_jobs_batch(jobs: list[dict], ignore_duplicates: bool = False) -> int:
    """
    Insert many jobs in a single transaction.
    Returns the count of actually-inserted (new) rows.

    ignore_duplicates=True skips existing fingerprint rows (append import).
    Jobs may include optional 'scraped_at' to preserve original scrape timestamp.
    """
    if not jobs:
        return 0

    conn = get_db_connection()
    cursor = conn.cursor()
    inserted = 0
    has_scraped_at = any(j.get('scraped_at') for j in jobs)

    def _row(j):
        base = (
            j.get('title', ''),
            j.get('company', ''),
            j.get('location', ''),
            j.get('experience', ''),
            j.get('posted', ''),
            j.get('source', ''),
            normalize_country(j.get('country', '')),
            j.get('scrape_id', ''),
            1 if j.get('is_ict') or j.get('_is_ict') else 0,
            j.get('ict_category', ''),
            j.get('date_precision', 'precise'),
        )
        if has_scraped_at:
            return base + (j.get('scraped_at') or None,)
        return base

    try:
        if is_postgres():
            rows = [_row(j) for j in jobs]
            cols = 'title, company, location, experience, posted, source, country, scrape_id, is_ict, ict_category, date_precision'
            if has_scraped_at:
                cols += ', scraped_at'
            conflict = 'DO NOTHING' if ignore_duplicates else '''
                DO UPDATE SET
                    is_ict = EXCLUDED.is_ict,
                    ict_category = EXCLUDED.ict_category,
                    posted = EXCLUDED.posted,
                    date_precision = EXCLUDED.date_precision,
                    scraped_at = COALESCE(EXCLUDED.scraped_at, jobs.scraped_at)
            '''
            execute_values(
                cursor,
                f'''
                INSERT INTO jobs ({cols})
                VALUES %s
                ON CONFLICT (title, company, location, source, country)
                {conflict}
                ''',
                rows,
            )
            inserted = cursor.rowcount
        else:
            rows = [_row(j) for j in jobs]
            verb = 'INSERT OR IGNORE' if ignore_duplicates else 'INSERT OR REPLACE'
            cols = 'title, company, location, experience, posted, source, country, scrape_id, is_ict, ict_category, date_precision'
            placeholders = '?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?'
            if has_scraped_at:
                cols += ', scraped_at'
                placeholders += ', ?'
            cursor.executemany(
                f'''
                {verb} INTO jobs ({cols})
                VALUES ({placeholders})
                ''',
                rows,
            )
            inserted = cursor.rowcount

        conn.commit()
    except Exception as e:
        print(f"[DB] save_jobs_batch error: {e}")
        conn.rollback()
    finally:
        conn.close()

    return inserted


# ─── Read helpers ─────────────────────────────────────────────────────────────

def job_exists(title, company, location, source) -> bool:
    """Point-check. Prefer load_fingerprints() for bulk scraping."""
    conn = get_db_connection()
    cursor = conn.cursor()

    if is_postgres():
        cursor.execute(
            'SELECT 1 FROM jobs WHERE title=%s AND company=%s AND location=%s AND source=%s',
            (title, company, location, source)
        )
    else:
        cursor.execute(
            'SELECT 1 FROM jobs WHERE title=? AND company=? AND location=? AND source=?',
            (title, company, location, source)
        )

    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def _build_where(source, country, pg=False):
    """Build WHERE clause and params for source+country filters."""
    clauses, params = [], []
    ph = '%s' if pg else '?'
    if source:
        clauses.append(f'source {"ILIKE" if pg else "LIKE"} {ph}')
        params.append(source)
    if country:
        norm = normalize_country(country)
        clauses.append(f'LOWER(country) = LOWER({ph})')
        params.append(norm)
    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
    return where, params


def get_job_count(source=None, country=None) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    pg = is_postgres()
    where, params = _build_where(source, country, pg)
    cursor.execute(f'SELECT COUNT(*) FROM jobs {where}', params)
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_jobs(source=None, country=None, page=1, limit=100) -> list[dict]:
    """Fetch one page of jobs ordered newest first."""
    conn = get_db_connection()
    offset = (page - 1) * limit
    pg = is_postgres()
    where, params = _build_where(source, country, pg)

    if pg:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            f'SELECT * FROM jobs {where} ORDER BY scraped_at DESC LIMIT %s OFFSET %s',
            params + [limit, offset]
        )
    else:
        cursor = conn.cursor()
        cursor.execute(
            f'SELECT * FROM jobs {where} ORDER BY scraped_at DESC LIMIT ? OFFSET ?',
            params + [limit, offset]
        )

    jobs = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jobs


def get_all_jobs(source=None, country=None) -> list[dict]:
    """Fetch ALL jobs — used only for Excel export."""
    conn = get_db_connection()
    pg = is_postgres()
    where, params = _build_where(source, country, pg)

    if pg:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(f'SELECT * FROM jobs {where} ORDER BY scraped_at DESC', params)
    else:
        cursor = conn.cursor()
        cursor.execute(f'SELECT * FROM jobs {where} ORDER BY scraped_at DESC', params)

    jobs = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jobs


def clear_jobs(source=None, country=None) -> bool:
    """Delete jobs filtered by source and/or country."""
    conn = get_db_connection()
    cursor = conn.cursor()
    pg = is_postgres()
    where, params = _build_where(source, country, pg)
    try:
        cursor.execute(f'DELETE FROM jobs {where}', params)
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] clear_jobs error: {e}")
        return False
    finally:
        conn.close()


def delete_jobs_by_scrape_id(scrape_id: str) -> bool:
    """Delete all jobs associated with a specific scrape run."""
    if not scrape_id:
        return False
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if is_postgres():
            cursor.execute('DELETE FROM jobs WHERE scrape_id = %s', (scrape_id,))
        else:
            cursor.execute('DELETE FROM jobs WHERE scrape_id = ?', (scrape_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] delete_jobs_by_scrape_id error: {e}")
        return False
    finally:
        conn.close()