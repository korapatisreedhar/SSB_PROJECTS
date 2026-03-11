import sqlite3

conn = sqlite3.connect("database.db")
cur = conn.cursor()

# coding results table
cur.execute("""
CREATE TABLE IF NOT EXISTS coding_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER,
    score INTEGER
)
""")

conn.commit()
conn.close()

print("coding_results table created successfully")