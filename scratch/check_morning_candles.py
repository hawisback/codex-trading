import urllib.request
import json

req = urllib.request.Request('http://localhost:8000/api/v1/ai/nifty/candles?interval=1m&limit=100', headers={'Accept': 'application/json'})
with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read().decode())

candles = data.get('candles', [])
print(f"Total 1m candles: {len(candles)}")
for c in candles:
    t = c.get('start_time', '')
    if any(k in t for k in ['04:0', '04:1', '04:2', '04:3', '04:4', '04:5', '09:3', '09:4', '09:5']):
        print(f"{t} | O: {c.get('open')} | H: {c.get('high')} | L: {c.get('low')} | C: {c.get('close')}")
