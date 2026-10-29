import sqlite3

db_path = r"C:\Users\hawis\OneDrive\Desktop\icici-breeze-api-trading\data\market\historical.db"
conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
cursor = conn.cursor()

# Check expiry dates in instrument_id
query = """
    SELECT distinct substr(instrument_id, 13, 10) as expiry
    FROM historical_candles
    WHERE instrument_id LIKE 'INST-SENSEX-2026%'
"""
expiries = cursor.execute(query).fetchall()
print("SENSEX option expiries in DB:", expiries)

# Check candle counts by date and expiry
query2 = """
    SELECT substr(start_time, 1, 10) as trading_date,
           substr(instrument_id, 13, 10) as expiry,
           count(distinct instrument_id) as strikes_count,
           count(*) as candle_count
    FROM historical_candles
    WHERE instrument_id LIKE 'INST-SENSEX-2026%'
    GROUP BY trading_date, expiry
    ORDER BY trading_date, expiry
"""
print("\nCandles by trading date and expiry:")
for row in cursor.execute(query2).fetchall():
    print(" ", row)

conn.close()
