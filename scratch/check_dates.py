import sqlite3

conn = sqlite3.connect(r'C:\Users\hawis\OneDrive\Desktop\icici-breeze-api-trading\data\market\historical.db')
c = conn.cursor()
c.execute("""
    SELECT DISTINCT SUBSTR(start_time, 1, 10) as d
    FROM historical_candles
    WHERE instrument_id = 'INST-NIFTY-INDEX' AND start_time >= '2026-08-15' AND start_time <= '2026-09-15'
    ORDER BY d
""")
rows = c.fetchall()
print("Dates in historical.db:")
for r in rows:
    print(r[0])
