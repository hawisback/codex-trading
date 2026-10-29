import sqlite3

db_path = r"C:\Users\hawis\OneDrive\Desktop\icici-breeze-api-trading\data\market\historical.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("SELECT count(*) FROM historical_candles WHERE instrument_id = 'INST-NIFTY-INDEX' AND start_time LIKE '2026-10-23%'")
print("Candles in DB for 2026-10-23:", cur.fetchall())
conn.close()
