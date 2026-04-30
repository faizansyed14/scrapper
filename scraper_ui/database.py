import os
import sqlite3
from datetime import datetime

# Optional support for PostgreSQL
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

DB_FILE = os.path.join(os.path.dirname(__file__), 'scraped_jobs.db')

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
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if is_postgres():
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS jobs (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT,
                experience TEXT,
                posted TEXT,
                source TEXT NOT NULL,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(title, company, location, source)
            )
        ''')
    else:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT,
                experience TEXT,
                posted TEXT,
                source TEXT NOT NULL,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(title, company, location, source)
            )
        ''')
        
    conn.commit()
    conn.close()

def save_job(job):
    """
    Save a job to the database.
    Returns True if the job was inserted (new), False if it already existed (duplicate).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    title = job.get('title', '')
    company = job.get('company', '')
    location = job.get('location', '')
    experience = job.get('experience', '')
    posted = job.get('posted', '')
    source = job.get('source', '')
    
    try:
        if is_postgres():
            # In Postgres, we use %s and ON CONFLICT DO NOTHING
            cursor.execute('''
                INSERT INTO jobs (title, company, location, experience, posted, source)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (title, company, location, source) DO NOTHING
                RETURNING id
            ''', (title, company, location, experience, posted, source))
            
            inserted = cursor.fetchone() is not None
            conn.commit()
            return inserted
        else:
            # SQLite uses ? and raises IntegrityError on UNIQUE conflict
            cursor.execute('''
                INSERT INTO jobs (title, company, location, experience, posted, source)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (title, company, location, experience, posted, source))
            conn.commit()
            return True
            
    except Exception as e:
        if not is_postgres() and isinstance(e, sqlite3.IntegrityError):
            return False
        # If it's another kind of error or Postgres error we didn't catch via ON CONFLICT
        print(f"Database error: {e}")
        return False
    finally:
        conn.close()

def job_exists(title, company, location, source):
    """Check if a job already exists in the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if is_postgres():
        cursor.execute('''
            SELECT 1 FROM jobs 
            WHERE title = %s AND company = %s AND location = %s AND source = %s
        ''', (title, company, location, source))
    else:
        cursor.execute('''
            SELECT 1 FROM jobs 
            WHERE title = ? AND company = ? AND location = ? AND source = ?
        ''', (title, company, location, source))
        
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def get_all_jobs(source=None):
    """Get all saved jobs, optionally filtered by source."""
    conn = get_db_connection()
    
    if is_postgres():
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        if source:
            cursor.execute('SELECT * FROM jobs WHERE source ILIKE %s ORDER BY scraped_at DESC', (source,))
        else:
            cursor.execute('SELECT * FROM jobs ORDER BY scraped_at DESC')
    else:
        cursor = conn.cursor()
        if source:
            cursor.execute('SELECT * FROM jobs WHERE source LIKE ? ORDER BY scraped_at DESC', (source,))
        else:
            cursor.execute('SELECT * FROM jobs ORDER BY scraped_at DESC')
            
    jobs = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jobs

def clear_jobs(source=None):
    """Delete jobs from the database, optionally filtered by source."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if is_postgres():
            if source:
                cursor.execute('DELETE FROM jobs WHERE source ILIKE %s', (source,))
            else:
                cursor.execute('DELETE FROM jobs')
        else:
            if source:
                cursor.execute('DELETE FROM jobs WHERE source LIKE ?', (source,))
            else:
                cursor.execute('DELETE FROM jobs')
        conn.commit()
        return True
    except Exception as e:
        print(f"Error clearing database: {e}")
        return False
    finally:
        conn.close()

