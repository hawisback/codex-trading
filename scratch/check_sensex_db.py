import sqlite3

db_path = r"C:\Users\hawis\OneDrive\Desktop\icici-breeze-api-trading\data\market\historical.db"
conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
cursor = conn.cursor()

tables = cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("Tables:", [t[0] for t in tables])

cols = cursor.execute("PRAGMA table_info(historical_candles)").fetchall()
print("historical_candles columns:", [c[1] for c in cols])

count_sensex = cursor.execute("SELECT count(*) FROM historical_candles WHERE instrument_id LIKE '%SENSEX%'").fetchone()[0]
print("Total SENSEX candles in historical_candles:", count_sensex)

spot_dates = cursor.execute("""
    SELECT substr(start_time, 1, 10) as dt, count(*), min(start_time), max(start_time), min(close), max(close)
    FROM historical_candles
    WHERE instrument_id = 'INST-SENSEX-INDEX'
    GROUP BY dt
    ORDER BY dt
""").fetchall()
print("\nSENSEX Spot Candles by Date:")
for d in spot_dates:
    print(" ", d)

opt_dates = cursor.execute("""
    SELECT substr(start_time, 1, 10) as dt, count(distinct instrument_id) as num_instruments, count(*) as num_candles
    FROM historical_candles
    WHERE instrument_id LIKE 'INST-SENSEX-2026%'
    GROUP BY dt
    ORDER BY dt
""").fetchall()
print("\nSENSEX Options Candles by Date:")
for d in opt_dates:
    print(" ", d)

sample_opts = cursor.execute("""
    SELECT distinct instrument_id
    FROM historical_candles
    WHERE instrument_id LIKE 'INST-SENSEX-2026%'
    LIMIT 10
""").fetchall()
print("\nSample SENSEX option IDs:")
for s in sample_opts:
    print(" ", s[0])

conn.close()
