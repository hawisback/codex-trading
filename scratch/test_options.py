import urllib.request
import json

base = 'http://127.0.0.1:8000/api/v1/ai'
url = base + '/nifty/options?strike_window=10'
req = urllib.request.Request(url, headers={'Accept': 'application/json'})
with urllib.request.urlopen(req, timeout=5) as res:
    data = json.loads(res.read().decode('utf-8'))
    print("ATM Strike:", data.get("atm_strike"))
    print("Expiry:", data.get("expiry"))
    for s in data.get("strikes", []):
        c = s.get("call", {})
        p = s.get("put", {})
        print(f"Strike {s.get('strike')}: Call LTP={c.get('last_price')}, IV={c.get('iv')} | Put LTP={p.get('last_price')}, IV={p.get('iv')}")
