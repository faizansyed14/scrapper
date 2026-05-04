import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), 'scraped_jobs.db')
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("UPDATE jobs SET country = 'UAE' WHERE country = '' OR country IS NULL")
    conn.commit()
    print(f"Success: Updated {cur.rowcount} rows in {db_path}")
    conn.close()
else:
    print("Error: jobs.db not found.")
