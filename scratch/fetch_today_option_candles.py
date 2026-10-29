import sys
import json
import asyncio
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, r"C:\Users\hawis\OneDrive\Desktop\icici-breeze-api-trading")
load_dotenv(r"C:\Users\hawis\OneDrive\Desktop\icici-breeze-api-trading\.env")

from libs.config.settings import get_platform_settings
from services.broker_gateway.zerodha_kite_adapter import ZerodhaKiteAdapter

async def main():
    s = get_platform_settings()
    a = ZerodhaKiteAdapter(s)
    await a.initialize()
    auth_ok = await a.authenticate_access_token(
        api_key=s.kite_api_key.get_secret_value(),
        access_token=s.kite_access_token.get_secret_value()
    )
    print("Kite Auth OK:", auth_ok)
    if not auth_ok:
        return

    instruments = await a._run(lambda: a._kite.instruments("NFO"))
    target_symbols = ["NIFTY26O1922900CE", "NIFTY26O1922950CE"]
    token_map = {}
    for inst in instruments:
        if inst["tradingsymbol"] in target_symbols:
            token_map[inst["tradingsymbol"]] = inst["instrument_token"]
            print(f"Found {inst['tradingsymbol']}: token={inst['instrument_token']}")

    start_dt = datetime(2026, 10, 15, 9, 15)
    end_dt = datetime(2026, 10, 15, 15, 30)

    results = {}
    for sym, token in token_map.items():
        candles = await a._run(lambda t=token: a._kite.historical_data(
            instrument_token=t,
            from_date=start_dt,
            to_date=end_dt,
            interval="minute"
        ))
        print(f"Fetched {len(candles)} candles for {sym}")
        results[sym] = [
            {
                "date": c["date"].isoformat(),
                "open": c["open"],
                "high": c["high"],
                "low": c["low"],
                "close": c["close"],
                "volume": c["volume"]
            }
            for c in candles
        ]

    # Also fetch spot index
    idx_token = 256265 # NIFTY 50
    spot_candles = await a._run(lambda: a._kite.historical_data(
        instrument_token=idx_token,
        from_date=start_dt,
        to_date=end_dt,
        interval="minute"
    ))
    print(f"Fetched {len(spot_candles)} candles for NIFTY 50")
    results["NIFTY 50"] = [
        {
            "date": c["date"].isoformat(),
            "open": c["open"],
            "high": c["high"],
            "low": c["low"],
            "close": c["close"],
            "volume": c["volume"]
        }
        for c in spot_candles
    ]

    out_path = Path("data/today_actual_candles_20261015.json")
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Saved actual candles to {out_path}")

if __name__ == "__main__":
    asyncio.run(main())
