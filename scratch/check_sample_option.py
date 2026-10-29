import sqlite3

db_path = r"C:\Users\hawis\OneDrive\Desktop\icici-breeze-api-trading\data\market\historical.db"
conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
cursor = conn.cursor()

# Check a sample option candle for 2026-10-12
sample = cursor.execute("""
    SELECT instrument_id, start_time, open, high, low, close, volume
    FROM historical_candles
    WHERE instrument_id LIKE 'INST-SENSEX-2026-10-15-72000-CE'
    LIMIT 5
""").fetchall()
print("Sample CE candle:")
for s in sample:
    print(" ", s)

sample_pe = cursor.execute("""
    SELECT instrument_id, start_time, open, high, low, close, volume
    FROM historical_candles
    WHERE instrument_id LIKE 'INST-SENSEX-2026-10-15-72000-PE'
    LIMIT 5
""").fetchall()
print("Sample PE candle:")
for s in sample_pe:
    print(" ", s)

conn.close()
