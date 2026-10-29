import urllib.request
import json

def fetch(path):
    url = f"http://127.0.0.1:8000/api/v1/ai{path}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BacktestScript"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}

c1m = fetch("/nifty/candles?interval=1m&limit=150")
c5m = fetch("/nifty/candles?interval=5m&limit=50")
tech5m = fetch("/nifty/technicals?interval=5m")
opts = fetch("/options/chain")

print("1m candles count:", len(c1m.get("candles", [])))
if c1m.get("candles"):
    print("1m first candle:", c1m["candles"][0].get("start_time"), "close:", c1m["candles"][0].get("close"))
    print("1m last candle:", c1m["candles"][-1].get("start_time"), "close:", c1m["candles"][-1].get("close"))

print("5m candles count:", len(c5m.get("candles", [])))
if c5m.get("candles"):
    print("5m first candle:", c5m["candles"][0].get("start_time"))
    print("5m last candle:", c5m["candles"][-1].get("start_time"))

print("tech5m metrics:", tech5m.get("metrics"))
if isinstance(opts, dict):
    print("atm_strike:", opts.get("atm_strike"))
    print("strikes count:", len(opts.get("strikes", [])))
