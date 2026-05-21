"""
Manual migration script for QuestSmith v1.1.2

Run this against your production database ONCE before deploying v1.1.2.
It copies reward_description into description for party goals where
description is empty, so no data is lost.

Usage:
    sqlite3 /path/to/questsmith.db < migrate_v112.py
  OR
    python migrate_v112.py /path/to/questsmith.db
"""
import sqlite3
import sys

if len(sys.argv) < 2:
    print("Usage: python migrate_v112.py /path/to/questsmith.db")
    sys.exit(1)

db_path = sys.argv[1]
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Copy reward_description → description where description is empty
cur.execute("""
    UPDATE party_goals
    SET description = reward_description
    WHERE (description IS NULL OR description = '')
      AND reward_description IS NOT NULL
      AND reward_description != ''
""")
migrated = cur.rowcount

# Clear reward_description (column stays in schema for backwards compat)
cur.execute("UPDATE party_goals SET reward_description = NULL")

conn.commit()
conn.close()

print(f"Migrated {migrated} party goal(s): reward_description → description")
print("Done. You can now deploy v1.1.2.")
