import os
import sqlite3
import glob

db_path = r"C:\Users\hawis\OneDrive\Desktop\icici-breeze-api-trading\data\market\historical.db"

print("=== Checking DB ===")
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT interval, instrument_id FROM historical_candles LIMIT 20")
    print("Intervals & instruments:", cur.fetchall())
    
    cur.execute("""
        SELECT instrument_id, interval, MIN(start_time), MAX(start_time), COUNT(*)
        FROM historical_candles
        WHERE instrument_id = 'INST-NIFTY-INDEX'
        GROUP BY interval
    """)
    for row in cur.fetchall():
        print("Range for INST-NIFTY-INDEX:", row)
        
    cur.execute("""
        SELECT DISTINCT substr(start_time, 1, 10) as d
        FROM historical_candles
        WHERE instrument_id = 'INST-NIFTY-INDEX'
        ORDER BY d DESC
        LIMIT 30
    """)
    recent_dates = [r[0] for r in cur.fetchall()]
    print("Recent dates in DB:", recent_dates)
    conn.close()
else:
    print("DB does not exist at:", db_path)

print("\n=== Checking local data folder ===")
spot_files = sorted(glob.glob("data/spot_candles_*.json"))
print(f"Found {len(spot_files)} local spot candle files:")
for f in spot_files[-10:]:
    print(" ", f)

opt_files = sorted(glob.glob("data/option_candles_*.json"))
print(f"Found {len(opt_files)} local option candle files:")
for f in opt_files[-10:]:
    print(" ", f)
