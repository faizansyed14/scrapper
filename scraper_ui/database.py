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
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(title, company, location, source, country)
            )
        ''')
        # Auto-migrate: add country column if missing (for existing DBs)
        try:
            cursor.execute("ALTER TABLE jobs ADD COLUMN country TEXT DEFAULT ''")
            print('[DB] Migrated: added country column')
        except Exception:
            pass  # Column already exists

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
    country    = job.get('country', '')

    try:
        if is_postgres():
            cursor.execute('''
                INSERT INTO jobs (title, company, location, experience, posted, source, country)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (title, company, location, source, country) DO NOTHING
                RETURNING id
            ''', (title, company, location, experience, posted, source, country))
            inserted = cursor.fetchone() is not None
            conn.commit()
            return inserted
        else:
            cursor.execute('''
                INSERT OR IGNORE INTO jobs (title, company, location, experience, posted, source, country)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (title, company, location, experience, posted, source, country))
            conn.commit()
            return cursor.rowcount > 0

    except Exception as e:
        print(f"[DB] save_job error: {e}")
        return False
    finally:
        conn.close()


# ─── Batch insert (fast) ──────────────────────────────────────────────────────

def save_jobs_batch(jobs: list[dict]) -> int:
    """
    Insert many jobs in a single transaction.
    Returns the count of actually-inserted (new) rows.

    This is ~10-50× faster than calling save_job() in a loop.
    """
    if not jobs:
        return 0

    conn = get_db_connection()
    cursor = conn.cursor()
    inserted = 0

    try:
        if is_postgres():
            rows = [
                (
                    j.get('title', ''),
                    j.get('company', ''),
                    j.get('location', ''),
                    j.get('experience', ''),
                    j.get('posted', ''),
                    j.get('source', ''),
                    j.get('country', ''),
                )
                for j in jobs
            ]
            execute_values(
                cursor,
                '''
                INSERT INTO jobs (title, company, location, experience, posted, source, country)
                VALUES %s
                ON CONFLICT (title, company, location, source, country) DO NOTHING
                ''',
                rows,
            )
            inserted = cursor.rowcount
        else:
            rows = [
                (
                    j.get('title', ''),
                    j.get('company', ''),
                    j.get('location', ''),
                    j.get('experience', ''),
                    j.get('posted', ''),
                    j.get('source', ''),
                    j.get('country', ''),
                )
                for j in jobs
            ]
            cursor.executemany(
                '''
                INSERT OR IGNORE INTO jobs
                    (title, company, location, experience, posted, source, country)
                VALUES (?, ?, ?, ?, ?, ?, ?)
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
        clauses.append(f'country {"ILIKE" if pg else "LIKE"} {ph}')
        params.append(country)
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