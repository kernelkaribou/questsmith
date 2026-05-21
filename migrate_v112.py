"""
Manual migration script for QuestSmith v1.1.2

Run this against your production database ONCE before deploying v1.1.2.
It copies reward_description into description for party goals where
description is empty, then drops the reward_description column.

Usage:
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

# Recreate table without reward_description column
cur.execute("""
    CREATE TABLE party_goals_new (
        id INTEGER NOT NULL PRIMARY KEY,
        campaign_id INTEGER NOT NULL,
        name VARCHAR(200) NOT NULL,
        description TEXT,
        target_amount INTEGER NOT NULL,
        min_individual_contribution INTEGER NOT NULL DEFAULT 0,
        sort_order INTEGER NOT NULL DEFAULT 0,
        unlocked_at DATETIME,
        created_at DATETIME,
        FOREIGN KEY(campaign_id) REFERENCES campaigns (id)
    )
""")
cur.execute("""
    INSERT INTO party_goals_new
    SELECT id, campaign_id, name, description, target_amount,
           min_individual_contribution, sort_order, unlocked_at, created_at
    FROM party_goals
""")
cur.execute("DROP TABLE party_goals")
cur.execute("ALTER TABLE party_goals_new RENAME TO party_goals")

conn.commit()
conn.close()

print(f"Migrated {migrated} party goal(s): reward_description → description")
print("Dropped reward_description column from party_goals table.")
print("Done. You can now deploy v1.1.2.")
