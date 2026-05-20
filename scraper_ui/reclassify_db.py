import sys
import os

# Add the parent directory to sys.path so we can import database and classifier
sys.path.insert(0, os.path.dirname(__file__))

import database
import classifier

def bulk_classify():
    print(f"[*] Starting bulk classification of existing jobs...")
    
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    # Get all jobs that haven't been classified or are marked as non-ICT
    # (Actually, we'll just process everything to be sure)
    cursor.execute("SELECT id, title FROM jobs")
    jobs = cursor.fetchall()
    
    total = len(jobs)
    print(f"[*] Found {total} jobs to process.")
    
    count = 0
    ict_count = 0
    
    # Process in batches for efficiency
    batch_size = 1000
    for i in range(0, total, batch_size):
        batch = jobs[i:i+batch_size]
        updates = []
        
        for job_id, title in batch:
            is_ict, category = classifier.classify_job(title)
            # SQLite uses 1/0 for boolean
            updates.append((1 if is_ict else 0, category, job_id))
            if is_ict:
                ict_count += 1
        
        if database.is_postgres():
            # For Postgres, we'd use execute_batch, but we'll stick to a standard loop for compatibility
            for is_ict, category, jid in updates:
                cursor.execute("UPDATE jobs SET is_ict = %s, ict_category = %s WHERE id = %s", (is_ict, category, jid))
        else:
            cursor.executemany("UPDATE jobs SET is_ict = ?, ict_category = ? WHERE id = ?", updates)
        
        conn.commit()
        count += len(batch)
        print(f"    Progress: {count}/{total} (Found {ict_count} ICT so far...)")

    conn.close()
    print(f"\n[+] Done! Total ICT jobs identified: {ict_count}")

if __name__ == "__main__":
    bulk_classify()
