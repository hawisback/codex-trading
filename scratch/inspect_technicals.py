import urllib.request
import json

url = "http://127.0.0.1:8000/api/v1/ai/nifty/technicals?interval=5m&limit=50"
req = urllib.request.Request(url, headers={"User-Agent": "BacktestScript"})
with urllib.request.urlopen(req, timeout=5) as resp:
    data = json.loads(resp.read().decode())
    print("Backend technicals metrics:")
    for k, v in data.get("metrics", {}).items():
        print(f"  {k}: {v}")
