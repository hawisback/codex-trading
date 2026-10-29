import os
import sqlite3

# Set BROKER_SESSION_DB explicitly when inspecting a local broker-session database.
db_path = os.getenv("BROKER_SESSION_DB")
if not db_path:
    raise SystemExit("Set BROKER_SESSION_DB to the broker-session database path first.")

conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("SELECT * FROM broker_accounts;")
print(cur.fetchall())
