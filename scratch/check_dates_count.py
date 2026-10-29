import sqlite3

db_path = r"C:\Users\hawis\OneDrive\Desktop\icici-breeze-api-trading\data\market\historical.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

print("--- 1-minute candle counts per date ---")
cur.execute("""
    SELECT substr(start_time, 1, 10) as dt, count(*) 
    FROM historical_candles 
    WHERE instrument_id = 'INST-NIFTY-INDEX' AND interval = '1m'
    GROUP BY dt
    ORDER BY dt DESC
    LIMIT 20
""")
for r in cur.fetchall():
    print(r)

print("\n--- 5-minute candle counts per date ---")
cur.execute("""
    SELECT substr(start_time, 1, 10) as dt, count(*) 
    FROM historical_candles 
    WHERE instrument_id = 'INST-NIFTY-INDEX' AND interval = '5m'
    GROUP BY dt
    ORDER BY dt DESC
    LIMIT 20
""")
for r in cur.fetchall():
    print(r)

conn.close()
